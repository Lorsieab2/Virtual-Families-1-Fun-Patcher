"""The Family Tree Maker's canvas tools: stickers, text boxes, fonts, undo and the Windows shortcuts.

The owner (2026-10-07): "have the option to choose 'Stickers' aka any image file on the computer
where people can drag and place them like a scrapbook"; "an option to resize any graphic,
microsoft-powerpoint style"; "resize, rotate, transform"; "add text boxes too! can resize, rotate,
transform"; "Use any font for anything!  maximum customizability"; "CTRL C and CTRL V please! ...
you know, standard windows shortcuts".

TreeEditor (src/vf1_family_tree_window.py) mixes this in.  A sticker or text box is selected by a
click and then:
* dragged by its middle to move it (the arrow keys nudge it, Shift by 10);
* resized by its eight handles -- a corner keeps its shape (Shift stretches it freely), an edge
  stretches one side;
* turned by the round handle above it (Shift turns in steps of 15 degrees);
* flipped, faded, layered, duplicated and typed into exactly from the Pictures & Text tab.
The canvas cannot turn or fade a picture, so each sticker is drawn by GDI+ (the same code that
saves the picture) into a small clear PNG, and that is what the canvas shows.
"""
from __future__ import annotations

import ctypes
import json
import math
import shutil
import struct
import tempfile
import tkinter as tk
import zlib
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

import vf1_family_tree as ft
import vf1_gdiplus

SELECT = "#1f6fd1"
CLIP_MARK = "VVFP Family Tree Maker sticker:"
# Each handle's place on the box, from its middle: (-1, -1) is the top left corner.
HANDLES = {"nw": (-1, -1), "n": (0, -1), "ne": (1, -1), "e": (1, 0), "se": (1, 1), "s": (0, 1),
           "sw": (-1, 1), "w": (-1, 0)}
ROTATE_GAP = 28                         # the turning handle above the box
GRAB = 8                                # how near a handle a click must be
UNDO_STEPS = 100
OWN_FONT = "(the patcher's own)"
SAME_FONT = "(the font for every word)"
# The words drawn bold unless the player says otherwise.
BOLD_ROLES = {"title", "names"}
HANDLE_LINE = "#5f6368"                 # PowerPoint's grey


def png_from_dib(dib: bytes) -> bytes | None:
    """A copied picture (Windows' clipboard bitmap, 24 or 32 bits a pixel) as PNG bytes; None for
    any other kind.  A 32-bit bitmap whose every pixel says it is see-through is taken as solid --
    that is how most programs copy a picture without transparency."""
    if len(dib) < 40:
        return None
    size, width, height, _planes, bits, compression = struct.unpack("<IiiHHI", dib[:20])
    if bits not in (24, 32) or compression not in (0, 3) or width <= 0 or height == 0:
        return None
    colours = struct.unpack("<I", dib[32:36])[0]
    start = size + (12 if compression == 3 and size == 40 else 0) + colours * 4
    stride = (width * bits // 8 + 3) & ~3
    rows = abs(height)
    if len(dib) < start + stride * rows:
        return None
    pixels = dib[start:start + stride * rows]
    order = range(rows - 1, -1, -1) if height > 0 else range(rows)
    step = bits // 8
    solid = bits == 24 or all(pixels[r * stride + 3 + c * 4] == 0 for r in range(rows) for c in range(width))
    out = bytearray()
    for r in order:
        line = pixels[r * stride:r * stride + width * step]
        out.append(0)
        for c in range(width):
            b, g, rr = line[c * step], line[c * step + 1], line[c * step + 2]
            a = 255 if solid else line[c * step + 3]
            out += bytes((rr, g, b, a))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, rows, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(out), 6)) + chunk(b"IEND", b""))


def clipboard_files_and_picture() -> tuple[list[Path], bytes | None]:
    """What Windows' clipboard holds besides text: files copied in File Explorer, and a copied
    picture (as PNG bytes).  Nothing on another system."""
    if not vf1_gdiplus.available():
        return [], None
    user32, kernel32, shell32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32"), ctypes.WinDLL("shell32")
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
    shell32.DragQueryFileW.restype = ctypes.c_uint
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
    if not user32.OpenClipboard(None):
        return [], None
    files: list[Path] = []
    picture = None
    try:
        drop = user32.GetClipboardData(15)                          # CF_HDROP
        if drop:
            for k in range(shell32.DragQueryFileW(drop, 0xFFFFFFFF, None, 0)):
                buffer = ctypes.create_unicode_buffer(1024)
                shell32.DragQueryFileW(drop, k, buffer, 1024)
                files.append(Path(buffer.value))
        handle = user32.GetClipboardData(8)                         # CF_DIB
        if handle:
            pointer = kernel32.GlobalLock(handle)
            if pointer:
                try:
                    picture = png_from_dib(ctypes.string_at(pointer, kernel32.GlobalSize(handle)))
                finally:
                    kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
    return files, picture


class ScrollingTab(ttk.Frame):
    """A notebook page that scrolls when its controls are taller than the window."""

    def __init__(self, notebook: ttk.Notebook, text: str) -> None:
        outer = ttk.Frame(notebook)
        notebook.add(outer, text=text)
        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        super().__init__(canvas, padding=8)
        window = canvas.create_window(0, 0, window=self, anchor="nw")
        self.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        # The wheel scrolls this page while the pointer is over it; leaving gives back whatever the
        # wheel did before (the patcher's window scrolls with it -- Codex, #555).
        before: dict[str, str] = {}

        def enter(_event) -> None:
            before["wheel"] = canvas.bind_all("<MouseWheel>")
            canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        def leave(_event) -> None:
            canvas.unbind_all("<MouseWheel>")
            if before.get("wheel"):
                canvas.tk.call("bind", "all", "<MouseWheel>", before["wheel"])

        canvas.bind("<Enter>", enter)
        canvas.bind("<Leave>", leave)


def scrollable_frame(window: tk.Toplevel, padding: int = 0) -> ttk.Frame:
    """The frame a window's controls go in. The content scrolls with a vertical scroll bar once it is
    taller than the screen allows; the wheel scrolls it while the pointer is over the window. The
    window's own size is the content's requested size, as before, capped at the screen."""
    canvas = tk.Canvas(window, highlightthickness=0, borderwidth=0,
                       background=ttk.Style(window).lookup("TFrame", "background"))
    bar = ttk.Scrollbar(window, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    frame = ttk.Frame(canvas, padding=padding)
    item = canvas.create_window((0, 0), window=frame, anchor="nw")

    def fit(_event=None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))
        height = min(frame.winfo_reqheight(), window.winfo_screenheight() - 160)
        canvas.configure(width=frame.winfo_reqwidth(), height=height)

    def wheel(event) -> str:
        # Text, Listbox and Canvas scroll themselves (their class binding has run already); the
        # window's own wheel then stops here, so the patcher's page behind it does not scroll too.
        if not isinstance(getattr(event, "widget", None), (tk.Text, tk.Listbox, tk.Canvas)):
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    frame.bind("<Configure>", fit)
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
    window.bind("<MouseWheel>", wheel)
    return frame


def _font_shown(name: str) -> str:
    """The font a font's name is written in: its own (the patcher's for "its own" choices)."""
    return vf1_gdiplus.FONT if name in (OWN_FONT, SAME_FONT, "") else name


def choose_font(parent, fonts: list[str], current: str) -> str | None:
    """A font from the list, each name written in its own font (the owner), with a search box;
    None when nothing is chosen."""
    window = tk.Toplevel(parent)
    window.title("Choose a font")
    window.transient(parent)
    search = tk.StringVar()
    ttk.Label(window, text="Search:").pack(anchor="w", padx=8, pady=(8, 0))
    entry = ttk.Entry(window, textvariable=search)
    entry.pack(fill="x", padx=8)
    frame = ttk.Frame(window)
    frame.pack(fill="both", expand=True, padx=8, pady=6)
    text = tk.Text(frame, width=42, height=20, wrap="none", cursor="hand2", spacing1=2, spacing3=2)
    bar = ttk.Scrollbar(frame, command=text.yview)
    text.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    text.tag_configure("pick", background="#cfe3ff")
    shown: list[str] = []
    result = {"font": current}

    def fill(*_args) -> None:
        wanted = search.get().strip().casefold()
        shown[:] = [f for f in fonts if wanted in f.casefold()]
        text.configure(state="normal")
        text.delete("1.0", "end")
        for k, name in enumerate(shown):
            tag = f"font{fonts.index(name)}"
            text.tag_configure(tag, font=(_font_shown(name), 14))
            text.insert("end", name + ("\n" if k < len(shown) - 1 else ""), (tag,))
            if name == result["font"]:
                text.tag_add("pick", f"{k + 1}.0", f"{k + 1}.end")
        text.configure(state="disabled")
        if result["font"] in shown:
            text.see(f"{shown.index(result['font']) + 1}.0")

    def pick(event) -> None:
        line = int(text.index(f"@{event.x},{event.y}").split(".")[0])
        if 1 <= line <= len(shown):
            result["font"] = shown[line - 1]
            text.tag_remove("pick", "1.0", "end")
            text.tag_add("pick", f"{line}.0", f"{line}.end")

    chosen = {"done": False}

    def done(_event=None) -> None:
        chosen["done"] = True
        window.destroy()

    text.bind("<Button-1>", pick)
    text.bind("<Double-Button-1>", lambda e: (pick(e), done()))
    search.trace_add("write", fill)
    buttons = ttk.Frame(window)
    buttons.pack(fill="x", padx=8, pady=(0, 8))
    ttk.Button(buttons, text="OK", command=done).pack(side="left")
    ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="left", padx=(6, 0))
    window.bind("<Return>", done)
    window.bind("<Escape>", lambda _e: window.destroy())
    fill()
    entry.focus_set()
    window.grab_set()
    parent.wait_window(window)
    return result["font"] if chosen["done"] else None


class FontButton(tk.Button):
    """A font choice: its name, written in that font; a click opens the font list."""

    def __init__(self, master, fonts: list[str], value: str, on_change) -> None:
        super().__init__(master, anchor="w", relief="groove", padx=6, command=self._pick)
        self.fonts, self.on_change = fonts, on_change
        self.set(value)

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value
        self.configure(text=value, font=(_font_shown(value), 12))

    def _pick(self) -> None:
        chosen = choose_font(self, self.fonts, self.value)
        if chosen is not None and chosen != self.value:
            self.set(chosen)
            self.on_change(chosen)


def picture_scene(path: Path, width: int, height: int, background: str) -> ft.Scene:
    """A picture whole, as large as fits, on `background`: for a thumbnail."""
    pw, ph = ft._picture_size(path)
    scale = min(width / max(1, pw), height / max(1, ph))
    picture = ft.Sticker(0, path, width / 2, height / 2, max(1.0, pw * scale), max(1.0, ph * scale))
    return ft.Scene(width, height, background, [ft.Backdrop(background), picture])


def panel_colour(widget) -> str:
    """The panel's colour as "#rrggbb" (Windows names it "SystemButtonFace", which a picture cannot
    be drawn on: the logos' thumbnails came out blank)."""
    r, g, b = widget.winfo_rgb(ttk.Style(widget).lookup("TFrame", "background") or "SystemButtonFace")
    return f"#{r >> 8:02x}{g >> 8:02x}{b >> 8:02x}"


class CanvasTools:
    """Mixed into TreeEditor, which provides canvas, edits, sc, images, library, folder, game,
    slot, notebook, status, selected, dirty, redraw(), _select(), _export(), _save_tree()."""

    # ---- setting up -----------------------------------------------------------
    def _tools_setup(self) -> None:
        self.obj: int | None = None             # the selected sticker's place in edits.stickers
        self.drag: dict | None = None
        self.sticker_photos: dict = {}
        self._scratch()
        self.history: list[str] = []
        self.future: list[str] = []
        self.last_state = self._state()
        self.fonts = [OWN_FONT] + sorted({f for f in tkfont.families(self) if not f.startswith("@")},
                                         key=str.casefold)
        self._stickers_tab()
        self._fonts_tab()
        self._shortcuts()

    def _scratch(self) -> Path:
        """The editor's own folder for the pictures it draws (removed when it closes)."""
        if getattr(self, "sticker_dir", None) is None:
            self.sticker_dir = Path(tempfile.mkdtemp(prefix="vvfp-tree-"))
        return self.sticker_dir

    def _thumb(self, key, scene: ft.Scene):
        """A small picture of `scene` (kept), or None where it cannot be drawn."""
        cache = self.__dict__.setdefault("thumb_cache", {})
        if key not in cache:
            path = self._scratch() / f"thumb{len(cache)}.png"
            try:
                cache[key] = (tk.PhotoImage(master=self, file=str(path))
                              if vf1_gdiplus.save_scene(scene, {}, path) else None)
            except (OSError, ValueError, tk.TclError):
                cache[key] = None
        return cache[key]

    def _thumb_grid(self, parent, items: list, on_pick, size: tuple[int, int], columns: int) -> list:
        """Clickable thumbnails, `items` being (name, a function giving its scene); the name shows
        in the status bar under the pointer.  They are drawn a few at a time after the window
        opens, so it opens at once."""
        width, height = size
        blank = tk.PhotoImage(master=self, width=width, height=height)
        labels = []
        for k, (name, _make) in enumerate(items):
            label = tk.Label(parent, image=blank, bd=0, highlightthickness=3,
                             highlightbackground=panel_colour(parent), cursor="hand2")
            label.blank = blank
            label.grid(row=k // columns, column=k % columns, padx=2, pady=2)
            label.bind("<Button-1>", lambda _e, k=k: on_pick(k))
            label.bind("<Enter>", lambda _e, n=name: self.status.set(n))
            labels.append(label)

        def fill(k: int = 0) -> None:
            if k >= len(items) or not labels[k].winfo_exists():
                return
            photo = self._thumb(("grid", items[k][0], size), items[k][1]())
            if photo is not None:
                labels[k].configure(image=photo)
                labels[k].photo = photo
            self.after(1, fill, k + 1)

        self.after(60, fill)
        return labels

    def _tools_close(self) -> None:
        shutil.rmtree(self.sticker_dir, ignore_errors=True)

    def _state(self) -> str:
        return json.dumps(self.edits.to_data(), sort_keys=True)

    # ---- undo and redo ----------------------------------------------------------
    def _record(self) -> None:
        """Called before every save: the state before it becomes a step to undo."""
        now = self._state()
        if now != self.last_state:
            self.history.append(self.last_state)
            del self.history[:-UNDO_STEPS]
            self.future.clear()
            self.last_state = now

    def _undo(self, _event=None):
        if self._typing():
            return None
        if not self.history:
            self.status.set("Nothing to undo.")
            return "break"
        self.future.append(self.last_state)
        self._restore(self.history.pop())
        self.status.set("Undone.")
        return "break"

    def _redo(self, _event=None):
        if self._typing():
            return None
        if not self.future:
            self.status.set("Nothing to redo.")
            return "break"
        self.history.append(self.last_state)
        self._restore(self.future.pop())
        self.status.set("Redone.")
        return "break"

    def _restore(self, state: str) -> None:
        self.last_state = state
        self.edits = ft.Edits.from_data(json.loads(state))
        if self.obj is not None and self.obj >= len(self.edits.stickers):
            self.obj = None
        self.dirty = True
        self.redraw()
        self._refresh_panels()

    # ---- drawing ----------------------------------------------------------------
    def _draw_stickers(self) -> None:
        c = self.canvas
        z = self.z
        for st in self.sc.stickers:
            tags = ("sticker", f"st{st.index}")
            shown = self._sticker_photo(st)
            if shown is not None:
                photo, (x0, y0) = shown
                c.create_image(x0, y0, image=photo, anchor="nw", tags=tags)
            else:                                   # no GDI+: its outline and words
                pts = [v * z for point in st.corners() for v in point]
                c.create_polygon(*pts, fill="", outline="#888888", dash=(4, 3), tags=tags)
                c.create_text(st.cx * z, st.cy * z, text=st.text or st.picture.name, angle=-st.angle, tags=tags)
        self._draw_handles()

    def _sticker_photo(self, st: ft.Sticker):
        raw = self.edits.stickers[st.index]
        try:
            stamp = st.picture.stat().st_mtime if st.picture is not None else 0
        except OSError:
            stamp = 0
        key = json.dumps(raw, sort_keys=True) + f"|{st.picture}|{stamp}|{self.z}"
        if key not in self.sticker_photos:
            path = self.sticker_dir / f"sticker{len(self.sticker_photos)}.png"
            try:
                where = vf1_gdiplus.render_sticker(st, path, self.z)
                if where is None:
                    return None
                self.sticker_photos[key] = (tk.PhotoImage(master=self, file=str(path)), where)
            except (OSError, tk.TclError):
                return None
        return self.sticker_photos[key]

    def _sticker(self) -> ft.Sticker | None:
        return next((s for s in self.sc.stickers if s.index == self.obj), None)

    def _handle_points(self, box: tuple) -> dict[str, tuple[float, float]]:
        """Where each handle of a box (middle x and y, width, height, angle) is."""
        cx, cy, w, h, angle = box
        out = {}
        for name, (sx, sy) in HANDLES.items():
            dx, dy = ft.turn(sx * w / 2, sy * h / 2, angle)
            out[name] = (cx + dx, cy + dy)
        dx, dy = ft.turn(0, -h / 2 - ROTATE_GAP, angle)
        out["rotate"] = (cx + dx, cy + dy)
        return out

    def _handled(self) -> tuple | None:
        """The box the handles are on: the selected sticker's, else the one selected family member's
        portrait frame (the owner: "drag their corners to resize them and rotate them with a little
        rotator thing at the top")."""
        st = self._sticker()
        if st is not None:
            return st.cx, st.cy, st.w, st.h, st.angle
        if self.obj is None and len(self.selected) == 1 and self.selected[0] in self.lay.x:
            x, y, w, h, angle = self.lay.frame(self.selected[0])
            s = self.sc.fit[0]                  # as the page draws it (a custom canvas)
            return (*ft.to_page(self.sc, x + w / 2, y + h / 2), w * s, h * s, angle)
        return None

    def _draw_handles(self) -> None:
        c = self.canvas
        c.delete("handles")
        box = self._handled()
        if box is None:
            return
        z = self.z
        pts = [v * z for point in ft.box_corners(*box) for v in point]
        c.create_polygon(*pts, fill="", outline=HANDLE_LINE, width=1, tags="handles")
        points = {name: (x * z, y * z) for name, (x, y) in self._handle_points(box).items()}
        rx, ry = points["rotate"]
        nx, ny = points["n"]
        c.create_line(nx, ny, rx, ry, fill=HANDLE_LINE, width=1, tags="handles")
        c.create_oval(rx - 10, ry - 10, rx + 10, ry + 10, fill="#ffffff", outline="", tags="handles")
        c.create_arc(rx - 7, ry - 7, rx + 7, ry + 7, start=110, extent=290, style="arc", outline=HANDLE_LINE,
                     width=2.5, tags="handles")
        c.create_polygon(rx + 1, ry - 10, rx + 7, ry - 6, rx + 1, ry - 2, fill=HANDLE_LINE, outline="",
                         tags="handles")
        for name in HANDLES:
            x, y = points[name]
            c.create_oval(x - 6, y - 6, x + 6, y + 6, fill="#ffffff", outline=HANDLE_LINE, width=1.5, tags="handles")

    # ---- the mouse ----------------------------------------------------------------
    def _where(self, event) -> tuple[float, float]:
        """Where the pointer is on the tree (in the tree's own units, whatever the zoom)."""
        return self.canvas.canvasx(event.x) / self.z, self.canvas.canvasy(event.y) / self.z

    def _sticker_at(self, x: float, y: float) -> ft.Sticker | None:
        for st in reversed(self.sc.stickers):
            if st.contains(x, y):
                return st
        return None

    def _tools_press(self, event) -> bool:
        """A click on a sticker or its handles: True when the click is the tools'."""
        x, y = self._where(event)
        st = self._sticker()
        box = self._handled()
        if box is not None:
            for name, (hx, hy) in self._handle_points(box).items():
                if abs(x - hx) * self.z <= GRAB and abs(y - hy) * self.z <= GRAB:
                    if st is None:              # the selected villager's frame
                        self.drag = {"mode": "turn" if name == "rotate" else "size", "handle": name, "box": box,
                                     "pid": self.selected[0]}
                    else:
                        self.drag = {"mode": "rotate" if name == "rotate" else "resize", "handle": name,
                                     "start": dict(self.edits.stickers[self.obj])}
                    return True
        hit = self._sticker_at(x, y)
        if hit is None:
            if self.obj is not None:
                self._select_obj(None)
            return False
        self._select_obj(hit.index)
        self.drag = {"mode": "move", "x": x, "y": y, "dx": 0.0, "dy": 0.0, "box": hit.bounds()}
        return True

    def _tools_drag(self, event) -> bool:
        if self.drag is None:
            return False
        x, y = self._where(event)
        shift = bool(event.state & 0x1)
        d = self.drag
        if d["mode"] == "move":
            dx, dy = self._snap(d["box"], x - d["x"], y - d["y"], event, sticker=self.obj)
            step_x, step_y = dx - d["dx"], dy - d["dy"]
            self.canvas.move(f"st{self.obj}", step_x * self.z, step_y * self.z)
            self.canvas.move("handles", step_x * self.z, step_y * self.z)
            d["dx"], d["dy"] = dx, dy
            return True
        if d["mode"] in ("size", "turn"):
            d["now"] = frame_dragged(d["box"], d["mode"], d["handle"], x, y, shift,
                                     free=shift == bool(self.lock_shape.get()))
            _cx, _cy, w, h, angle = d["now"]
            self.status.set(f"Width {w:.0f}, height {h:.0f}" if d["mode"] == "size" else f"Turned {angle:.0f} degrees")
            self.canvas.delete("ghost")
            pts = [v * self.z for point in ft.box_corners(*d["now"]) for v in point]
            self.canvas.create_polygon(*pts, fill="", outline=SELECT, width=2, tags="ghost")
            return True
        start = d["start"]
        if d["mode"] == "resize":
            d["now"] = resized(start, d["handle"], x, y, free=shift == bool(self.lock_shape.get()))
            self.status.set(f"Width {d['now']['w']:.0f}, height {d['now']['h']:.0f}"
                            + ("" if shift or len(d["handle"]) == 1 else "  (hold Shift to stretch freely)"))
        else:
            angle = math.degrees(math.atan2(y - start["cy"], x - start["cx"])) + 90
            if shift:
                angle = round(angle / 15) * 15
            d["now"] = {**start, "angle": angle % 360}
            self.status.set(f"Turned {d['now']['angle']:.0f} degrees" + ("" if shift else "  (hold Shift for steps of 15)"))
        self.canvas.delete("ghost")
        pts = [v * self.z for point in ft.box_corners(d["now"]["cx"], d["now"]["cy"], d["now"]["w"], d["now"]["h"],
                                                      d["now"]["angle"]) for v in point]
        self.canvas.create_polygon(*pts, fill="", outline=SELECT, width=2, tags="ghost")
        return True

    def _tools_release(self, _event) -> bool:
        if self.drag is None:
            return False
        d, self.drag = self.drag, None
        self.canvas.delete("ghost")
        self.canvas.delete("guide")
        if d["mode"] in ("size", "turn"):
            if "now" in d:
                _cx, _cy, w, h, angle = d["now"]
                p = self.village.people[d["pid"]]
                if d["mode"] == "size":
                    s = self.lay.shrink or 1.0            # the size before Shrink to fit (it is applied on top)
                    s *= self.sc.fit[0]                   # and before a custom canvas shrank the tree
                    self._set_entry(p, w=round(w / s, 1), h=round(h / s, 1))
                else:
                    self._set_entry(p, angle=round(angle, 1) % 360)
                self._saved()
            return True
        raw = self.edits.stickers[self.obj]
        if d["mode"] == "move":
            if d["dx"] or d["dy"]:
                raw["cx"] += d["dx"]
                raw["cy"] += d["dy"]
                self._saved()
        elif "now" in d:
            self.edits.stickers[self.obj] = ft.clean_sticker(d["now"])
            self._saved()
        return True

    def _double_click(self, event) -> None:
        st = self._sticker_at(*self._where(event))
        if st is not None and st.picture is None:
            self._select_obj(st.index)
            self._edit_text()
            return
        if st is None:                          # any words the tree writes: retyped where they are
            c = self.canvas
            x, y = c.canvasx(event.x), c.canvasy(event.y)
            iid = next((i for i in reversed(c.find_overlapping(x - 4, y - 4, x + 4, y + 4)) if i in self.editable),
                       None)
            if iid is not None:
                self._edit_in_place(iid, self.editable[iid])

    # ---- selecting ----------------------------------------------------------------
    def _select_obj(self, index: int | None) -> None:
        self.obj = index
        if index is not None and self.selected:
            self.selected = []
            self._draw_selection()
            self._refresh_selected()
        self._draw_handles()
        self._refresh_obj_panel()
        if index is not None:
            self.notebook.select(self.stickers_tab.master.master)

    # ---- the Pictures & Text tab ------------------------------------------------------
    def _stickers_tab(self) -> None:
        tab = ScrollingTab(self.notebook, "Pictures")
        self.stickers_tab = tab
        ttk.Label(tab, text="Put pictures, logos and text boxes on the tree.  Click one to select it, then "
                            "drag it to move it, drag a square to resize it, or drag the circle to rotate it.",
                  wraplength=320, justify="left").pack(anchor="w")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Add Picture...", command=self._add_picture).pack(side="left")
        ttk.Button(row, text="Add Text Box", command=self._add_text_box).pack(side="left", padx=(6, 0))
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(6, 0))
        self.logos = [(name, ref) for name, ref in ft.LOGOS
                      if ft.picture_path(ref, self.images, self.library) is not None]
        if self.logos:
            ttk.Label(row, text="Click a logo to add it:").pack(anchor="w")
            grid = ttk.Frame(tab)
            grid.pack(anchor="w")
            back = panel_colour(tab)
            self._thumb_grid(grid, [(name, lambda r=ref: picture_scene(
                ft.picture_path(r, self.images, self.library), 140, 80, back)) for name, ref in self.logos],
                lambda k: self._add_logo(self.logos[k][1]), (140, 80), 2)

        self.obj_frame = ttk.LabelFrame(tab, text="Selected item", padding=6)
        self.obj_frame.pack(fill="x", pady=(10, 0))
        f = self.obj_frame
        self.obj_label = tk.StringVar(value="Nothing selected.")
        self.obj_thumb = tk.Label(f, bd=0)
        self.obj_thumb.grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(f, textvariable=self.obj_label, wraplength=300).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(f, text="Drag the circles to resize, the arrow to rotate.  Right-click for more.",
                  wraplength=300, justify="left").grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 4))
        ttk.Checkbutton(f, text="Keep aspect ratio", variable=self.lock_shape).grid(row=2, column=0, columnspan=4,
                                                                                   sticky="w")
        self.flip_vars = {name: tk.BooleanVar() for name in ("flip_h", "flip_v")}
        for k, (name, words) in enumerate((("flip_h", "Flip horizontally"), ("flip_v", "Flip vertically"))):
            ttk.Checkbutton(f, text=words, variable=self.flip_vars[name],
                            command=lambda n=name: self._set_obj(**{n: bool(self.flip_vars[n].get())})
                            ).grid(row=3 + k, column=0, columnspan=4, sticky="w")
        self.opacity_text = tk.StringVar(value="Opacity: 100%")
        ttk.Label(f, textvariable=self.opacity_text).grid(row=7, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.obj_opacity = ttk.Scale(f, from_=0, to=100, orient="horizontal",
                                     command=lambda v: self.opacity_text.set(f"Opacity: {int(float(v))}%"))
        self.obj_opacity.grid(row=8, column=0, columnspan=4, sticky="ew")
        self.obj_opacity.bind("<ButtonRelease-1>", lambda _e: self._set_obj(opacity=float(int(self.obj_opacity.get()))))

        self.text_frame = ttk.LabelFrame(tab, text="Text box", padding=6)
        self.text_frame.pack(fill="x", pady=(10, 0))
        t = self.text_frame
        self.box_text = tk.Text(t, height=4, width=34, undo=True, wrap="word")
        self.box_text.grid(row=0, column=0, columnspan=4, sticky="ew")
        ttk.Button(t, text="Save text", command=self._apply_box_text).grid(row=1, column=0, sticky="w", pady=(2, 6))
        ttk.Label(t, text="Font:").grid(row=2, column=0, sticky="w")
        self.box_font = FontButton(t, self.fonts, OWN_FONT, lambda f: self._set_obj(font=self._font_name(f)))
        self.box_font.grid(row=2, column=1, columnspan=3, sticky="ew")
        ttk.Label(t, text="Size:").grid(row=3, column=0, sticky="w")
        self.box_size = tk.StringVar()
        spin = ttk.Spinbox(t, textvariable=self.box_size, from_=4, to=400, width=6,
                           command=lambda: self._set_number("size", self.box_size))
        spin.grid(row=3, column=1, sticky="w")
        spin.bind("<Return>", lambda _e: self._set_number("size", self.box_size))
        self.box_flags = {name: tk.BooleanVar() for name in ("bold", "italic", "underline", "strike")}
        flags = ttk.Frame(t)
        flags.grid(row=4, column=0, columnspan=4, sticky="w")
        for name in self.box_flags:
            ttk.Checkbutton(flags, text="Strikethrough" if name == "strike" else name.capitalize(),
                            variable=self.box_flags[name],
                            command=lambda n=name: self._set_obj(**{n: bool(self.box_flags[n].get())})
                            ).pack(side="left", padx=(0, 6))
        ttk.Label(t, text="Text colour:").grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.box_colour = self.ColourField(t, ft.INK, lambda c: self._set_obj(colour=c or ft.INK), allow_default=False)
        self.box_colour.grid(row=6, column=0, columnspan=4, sticky="w")
        ttk.Label(t, text="Align:").grid(row=7, column=0, sticky="w", pady=(4, 0))
        self.box_align = tk.StringVar()
        box = ttk.Combobox(t, textvariable=self.box_align, values=list(ft.ALIGNS.values()), state="readonly", width=8)
        box.grid(row=7, column=1, sticky="w", pady=(4, 0))
        box.bind("<<ComboboxSelected>>", lambda _e: self._set_obj(
            align=next(k for k, v in ft.ALIGNS.items() if v == self.box_align.get())))
        ttk.Label(t, text="Vertical:").grid(row=7, column=2, sticky="w", pady=(4, 0))
        self.box_valign = tk.StringVar()
        box = ttk.Combobox(t, textvariable=self.box_valign, values=list(ft.VALIGNS.values()), state="readonly", width=8)
        box.grid(row=7, column=3, sticky="w", pady=(4, 0))
        box.bind("<<ComboboxSelected>>", lambda _e: self._set_obj(
            valign=next(k for k, v in ft.VALIGNS.items() if v == self.box_valign.get())))
        ttk.Label(t, text="Shape:").grid(row=8, column=2, sticky="w", pady=(4, 0))
        self.box_shape = tk.StringVar()
        shape = ttk.Combobox(t, textvariable=self.box_shape, values=ft.alphabetical(ft.SHAPES.values()), state="readonly", width=10)
        shape.grid(row=8, column=3, sticky="w", pady=(4, 0))
        shape.bind("<<ComboboxSelected>>", lambda _e: self._set_obj(
            shape=next(k for k, v in ft.SHAPES.items() if v == self.box_shape.get())))
        ttk.Label(t, text="Background:").grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.box_fill = self.ColourField(t, "", lambda c: self._set_obj(fill=c), default_text="None")
        self.box_fill.grid(row=9, column=0, columnspan=4, sticky="w")
        self.fill_text = tk.StringVar(value="Background opacity: 100%")
        ttk.Label(t, textvariable=self.fill_text).grid(row=10, column=0, columnspan=4, sticky="w")
        self.box_fill_opacity = ttk.Scale(t, from_=0, to=100, orient="horizontal",
                                          command=lambda v: self.fill_text.set(f"Background opacity: {int(float(v))}%"))
        self.box_fill_opacity.grid(row=11, column=0, columnspan=4, sticky="ew")
        self.box_fill_opacity.bind("<ButtonRelease-1>", lambda _e: self._set_obj(
            fill_opacity=float(int(self.box_fill_opacity.get()))))
        ttk.Label(t, text="Border:").grid(row=12, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.box_border = self.ColourField(t, "", lambda c: self._set_obj(border=c), default_text="None")
        self.box_border.grid(row=13, column=0, columnspan=4, sticky="w")
        ttk.Label(t, text="Border width:").grid(row=14, column=0, sticky="w")
        self.box_border_width = tk.StringVar()
        spin = ttk.Spinbox(t, textvariable=self.box_border_width, from_=0, to=40, width=6,
                           command=lambda: self._set_number("border_width", self.box_border_width))
        spin.grid(row=14, column=1, sticky="w")
        spin.bind("<Return>", lambda _e: self._set_number("border_width", self.box_border_width))
        t.columnconfigure(3, weight=1)
        self._refresh_obj_panel()

    def _refresh_obj_panel(self) -> None:
        raw = self.edits.stickers[self.obj] if self.obj is not None else None
        if raw is None:
            self.obj_label.set("Nothing selected.  Click a picture or text box on the tree.")
            self.obj_thumb.grid_remove()
            return
        what = raw["picture"] if raw["kind"] == "picture" else "Text box"
        if raw["kind"] == "picture" and ft.picture_path(raw["picture"], self.images, self.library) is None:
            what += "  (not found on this computer)"
        self.obj_label.set("" if raw["kind"] == "picture" and "not found" not in what else what)
        path = ft.picture_path(raw.get("picture", ""), self.images, self.library) if raw["kind"] == "picture" else None
        photo = (self._thumb(("selected", str(path)), picture_scene(path, 160, 100, panel_colour(self.obj_thumb)))
                 if path is not None else None)
        self.obj_thumb.configure(image=photo or "")
        self.obj_thumb.photo = photo
        self.obj_thumb.grid() if photo is not None else self.obj_thumb.grid_remove()
        for name, var in self.flip_vars.items():
            var.set(raw[name])
        self.obj_opacity.set(raw["opacity"])
        self.opacity_text.set(f"Opacity: {int(raw['opacity'])}%")
        if raw["kind"] != "text":
            return
        self.box_text.delete("1.0", "end")
        self.box_text.insert("1.0", raw["text"])
        self.box_font.set(raw["font"] or OWN_FONT)
        self.box_size.set(f"{raw['size']:g}")
        for name, var in self.box_flags.items():
            var.set(raw[name])
        self.box_colour.set_quietly(raw["colour"])
        self.box_align.set(ft.ALIGNS[raw["align"]])
        self.box_valign.set(ft.VALIGNS[raw["valign"]])
        self.box_shape.set(ft.SHAPES[raw["shape"]])
        self.box_fill.set_quietly(raw["fill"])
        self.box_fill_opacity.set(raw["fill_opacity"])
        self.fill_text.set(f"Background opacity: {int(raw['fill_opacity'])}%")
        self.box_border.set_quietly(raw["border"])
        self.box_border_width.set(f"{raw['border_width']:g}")

    @staticmethod
    def _font_name(text: str) -> str:
        return "" if text in (OWN_FONT, SAME_FONT) else text.strip()

    # ---- changing stickers -------------------------------------------------------------
    def _set_obj(self, **values) -> None:
        if self.obj is None:
            return
        raw = dict(self.edits.stickers[self.obj])
        if raw["kind"] != "text" and set(values) - {"opacity", "angle", "flip_h", "flip_v", "cx", "cy", "w", "h"}:
            return
        raw.update(values)
        self.edits.stickers[self.obj] = ft.clean_sticker(raw)
        self._saved()

    def _set_number(self, name: str, var: tk.StringVar) -> None:
        try:
            self._set_obj(**{name: float(var.get())})
        except ValueError:
            self.bell()

    def _turn(self, degrees: float) -> None:
        if self.obj is not None:
            self._set_obj(angle=(self.edits.stickers[self.obj]["angle"] + degrees) % 360)

    def _toggle(self, name: str) -> None:
        if self.obj is not None:
            self._set_obj(**{name: not self.edits.stickers[self.obj][name]})

    def _layer(self, where: str) -> None:
        if self.obj is None:
            return
        items = self.edits.stickers
        item = items.pop(self.obj)
        place = {"front": len(items), "back": 0, "forward": min(len(items), self.obj + 1),
                 "backward": max(0, self.obj - 1)}[where]
        items.insert(place, item)
        self.obj = place
        self._saved()

    def _original_shape(self) -> None:
        if self.obj is None:
            return
        raw = self.edits.stickers[self.obj]
        path = ft.picture_path(raw.get("picture", ""), self.images, self.library) if raw["kind"] == "picture" else None
        if path is None:
            return
        pw, ph = ft._picture_size(path)
        self._set_obj(h=raw["w"] * ph / max(1, pw))

    def _reset_sticker(self) -> None:
        """The selected picture or text box as it was first added, where it is now: a picture its
        own shape and size, a text box the plain look with its words."""
        if self.obj is None:
            return
        raw = self.edits.stickers[self.obj]
        if raw["kind"] == "picture":
            path = ft.picture_path(raw["picture"], self.images, self.library)
            fresh = ft.new_sticker(raw["picture"], path, raw["cx"], raw["cy"]) if path is not None else None
        else:
            fresh = ft.new_text_box(raw["cx"], raw["cy"], raw["text"], self.edits.font)
        if fresh is not None:
            if "page" in raw:
                fresh["page"] = raw["page"]     # still on its own page
            self.edits.stickers[self.obj] = fresh
            self._saved()

    def _place_new(self, raw: dict | None) -> None:
        if raw is None:
            return
        raw["page"] = int(self._pkey())         # on this page alone
        self.edits.stickers.append(raw)
        self.obj = len(self.edits.stickers) - 1
        self.selected = []
        self._saved()
        self.notebook.select(self.stickers_tab.master.master)

    def _view_middle(self) -> tuple[float, float]:
        c = self.canvas
        return c.canvasx(c.winfo_width() / 2) / self.z, c.canvasy(c.winfo_height() / 2) / self.z

    def _add_picture(self, path: Path | None = None) -> None:
        if path is None:
            chosen = filedialog.askopenfilename(parent=self, title="A picture to put on the tree",
                                                filetypes=[("Pictures", "*.png *.jpg *.jpeg *.bmp *.gif"),
                                                           ("All files", "*.*")])
            if not chosen:
                return
            path = Path(chosen)
        if path.suffix.lower() not in ft.PICTURE_TYPES or not path.is_file():
            messagebox.showerror("Family Tree Maker", f"{path.name} is not a PNG, JPG, BMP or GIF picture.", parent=self)
            return
        self._place_new(ft.new_sticker(str(path), path, *self._view_middle()))

    def _add_text_box(self) -> None:
        self._place_new(ft.new_text_box(*self._view_middle(), font=self.edits.font))
        self._edit_text()

    def _add_logo(self, ref: str) -> None:
        path = ft.picture_path(ref, self.images, self.library)
        if path is not None:
            self._place_new(ft.new_sticker(ref, path, *self._view_middle()))

    def _edit_text(self, _event=None):
        if self._typing():
            return None
        if self.obj is not None and self.edits.stickers[self.obj]["kind"] == "text":
            self.notebook.select(self.stickers_tab.master.master)
            self.box_text.focus_set()
            self.box_text.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _apply_box_text(self) -> None:
        self._set_obj(text=self.box_text.get("1.0", "end-1c"))

    def _duplicate(self, _event=None):
        if self._typing():
            return None
        if self.obj is not None:
            raw = dict(self.edits.stickers[self.obj])
            raw["cx"] += 20
            raw["cy"] += 20
            self._place_new(raw)
        return "break"

    def _delete(self, _event=None):
        if self._typing():
            return None
        if self.obj is not None:
            del self.edits.stickers[self.obj]
            self.obj = None
            self._saved()
        elif self.selected:
            self._delete_people(list(self.selected[:1]))
        return "break"

    def _nudge(self, dx: int, dy: int):
        def act(event):
            if self._typing() or self.obj is None:
                return None
            step = 10 if event.state & 0x1 else 1
            raw = self.edits.stickers[self.obj]
            self._set_obj(cx=raw["cx"] + dx * step, cy=raw["cy"] + dy * step)
            return "break"
        return act

    def _style_key(self, name: str):
        def act(_event):
            if self._typing() or self.obj is None or self.edits.stickers[self.obj]["kind"] != "text":
                return None
            self._toggle(name)
            return "break"
        return act

    def _layer_key(self, where: str):
        def act(_event):
            if self._typing():
                return None
            self._layer(where)
            return "break"
        return act

    # ---- copy and paste --------------------------------------------------------------------
    def _copy(self, _event=None):
        if self._typing():
            return None
        if self.obj is not None:
            self.clipboard_clear()
            self.clipboard_append(CLIP_MARK + json.dumps(self.edits.stickers[self.obj]))
            self.status.set("Copied.  Ctrl+V pastes it, here or in another family's tree.")
        elif self.selected:
            people = [self.village.people[q] for q in self.selected]
            self.clipboard_clear()
            self.clipboard_append("\n\n".join("\n".join(ft.node_text(self.lay, p)) for p in people))
            self.status.set(f"Copied the words of {len(people)} portrait(s).")
        return "break"

    def _cut(self, _event=None):
        if self._typing():
            return None
        if self.obj is not None:
            self._copy()
            self._delete()
        return "break"

    def _paste(self, _event=None):
        """A copied sticker; else files copied in File Explorer; else a copied picture; else
        copied words, which become a text box."""
        if self._typing():
            return None
        try:
            text = self.clipboard_get()
        except tk.TclError:
            text = ""
        cx, cy = self._view_middle()
        if text.startswith(CLIP_MARK):
            try:
                raw = ft.clean_sticker(json.loads(text[len(CLIP_MARK):]))
            except ValueError:
                raw = None
            if raw is not None:
                raw["cx"] += 20
                raw["cy"] += 20
                self._place_new(raw)
            return "break"
        files, picture = clipboard_files_and_picture()
        pictures = [f for f in files if f.suffix.lower() in ft.PICTURE_TYPES and f.is_file()]
        if pictures:
            for k, path in enumerate(pictures):
                self._place_new(ft.new_sticker(str(path), path, cx + 24 * k, cy + 24 * k))
            return "break"
        if picture is not None:
            folder = ft.Edits.path(self.folder, self.game, self.slot).parent / "Pictures"
            try:
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"Pasted {datetime.now():%Y-%m-%d %H-%M-%S-%f}.png"
                path.write_bytes(picture)
            except OSError as exc:
                messagebox.showerror("Family Tree Maker", f"The picture could not be kept: {exc}", parent=self)
                return "break"
            self._place_new(ft.new_sticker(str(path), path, cx, cy))
            return "break"
        if text.strip():
            path = Path(text.strip().strip('"'))
            if path.suffix.lower() in ft.PICTURE_TYPES and path.is_file():
                self._place_new(ft.new_sticker(str(path), path, cx, cy))
            else:
                self._place_new(ft.new_text_box(cx, cy, text.strip(), self.edits.font))
            return "break"
        self.status.set("There is nothing to paste.")
        return "break"

    # ---- the Fonts tab ----------------------------------------------------------------------
    def _fonts_tab(self) -> None:
        tab = ScrollingTab(self.notebook, "Fonts")
        ttk.Label(tab, text="Any font on this computer, for any words on the tree.", wraplength=320).pack(anchor="w")
        ttk.Label(tab, text="Font for all text:").pack(anchor="w", pady=(8, 1))
        self.all_font = FontButton(tab, self.fonts, self.edits.font or OWN_FONT,
                                   lambda f: self._change(font=self._font_name(f)))
        self.all_font.pack(fill="x")
        frame = ttk.LabelFrame(tab, text="Font for one part of the tree", padding=6)
        frame.pack(fill="x", pady=(12, 0))
        self.role_var = tk.StringVar(value=list(ft.ROLES.values())[0])
        roles = ttk.Combobox(frame, textvariable=self.role_var, values=ft.alphabetical(ft.ROLES.values()), state="readonly")
        roles.grid(row=0, column=0, columnspan=2, sticky="ew")
        roles.bind("<<ComboboxSelected>>", lambda _e: self._show_role())
        ttk.Label(frame, text="Font:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.role_font = FontButton(frame, [SAME_FONT] + self.fonts[1:], SAME_FONT, lambda _f: self._set_role())
        self.role_font.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ttk.Label(frame, text="Size (%):").grid(row=2, column=0, sticky="w")
        self.role_scale = tk.StringVar()
        spin = ttk.Spinbox(frame, textvariable=self.role_scale, from_=25, to=400, increment=5, width=6,
                           command=self._set_role)
        spin.grid(row=2, column=1, sticky="w")
        spin.bind("<Return>", lambda _e: self._set_role())
        self.role_flags = {name: tk.BooleanVar() for name in ("bold", "italic", "underline", "strike")}
        for k, (name, words) in enumerate((("bold", "Bold"), ("italic", "Italic"), ("underline", "Underline"),
                                           ("strike", "Strikethrough"))):
            ttk.Checkbutton(frame, text=words, variable=self.role_flags[name], command=self._set_role
                            ).grid(row=3 + k // 2, column=k % 2, sticky="w")
        ttk.Label(frame, text="Colour:").grid(row=5, column=0, columnspan=2, sticky="w",
                                                                         pady=(4, 0))
        self.role_colour = self.ColourField(frame, "", lambda _c: self._set_role())
        self.role_colour.grid(row=6, column=0, columnspan=2, sticky="w")
        ttk.Button(frame, text="Reset", command=self._reset_role).grid(row=7, column=0, columnspan=2,
                                                                                       sticky="w", pady=(8, 0))
        frame.columnconfigure(1, weight=1)
        self._show_role()

    def _role(self) -> str:
        return next(k for k, v in ft.ROLES.items() if v == self.role_var.get())

    def _show_role(self) -> None:
        style = self.edits.styles.get(self._role(), {})
        self.role_font.set(style.get("font", SAME_FONT))
        self.role_scale.set(str(style.get("scale", 100)))
        role = self._role()
        for name, var in self.role_flags.items():
            var.set(style.get(name, name == "bold" and role in BOLD_ROLES))
        self.role_colour.set_quietly(style.get("colour", ""))

    def _set_role(self) -> None:
        try:
            scale = int(float(self.role_scale.get()))
        except ValueError:
            self.bell()
            return
        role = self._role()
        style = {"font": self._font_name(self.role_font.get()), "scale": scale, "colour": self.role_colour.value}
        for name, var in self.role_flags.items():
            if bool(var.get()) != (name == "bold" and role in BOLD_ROLES):
                style[name] = bool(var.get())     # only what differs from how it is drawn
        style = ft.clean_style({k: v for k, v in style.items() if v not in (None, "")})
        if style.get("scale") == 100:
            del style["scale"]
        if style:
            self.edits.styles[self._role()] = style
        else:
            self.edits.styles.pop(self._role(), None)
        self._saved()

    def _reset_role(self) -> None:
        self.edits.styles.pop(self._role(), None)
        self._saved()
        self._show_role()

    # ---- the keyboard ---------------------------------------------------------------------
    def _typing(self) -> bool:
        """Whether a typing field has the keyboard, so the shortcut is the field's own."""
        widget = self.focus_get()
        return widget is not None and widget.winfo_class() in ("Entry", "TEntry", "Text", "TCombobox", "TSpinbox",
                                                               "Spinbox")

    def _shortcuts(self) -> None:
        keys = {
            ("c",): self._copy, ("x",): self._cut, ("v",): self._paste, ("d",): self._duplicate,
            ("z",): self._undo, ("y",): self._redo, ("s",): self._save_key,
            ("b",): self._style_key("bold"), ("i",): self._style_key("italic"), ("u",): self._style_key("underline"),
        }
        for (key,), command in keys.items():
            self.bind(f"<Control-{key}>", command)
            self.bind(f"<Control-{key.upper()}>", command)
        self.bind("<Control-Shift-Z>", self._redo)
        self.bind("<Control-bracketright>", self._layer_key("forward"))
        self.bind("<Control-bracketleft>", self._layer_key("backward"))
        self.bind("<Control-braceright>", self._layer_key("front"))
        self.bind("<Control-braceleft>", self._layer_key("back"))
        self.bind("<Delete>", self._delete)
        self.bind("<F2>", self._edit_text)
        for key, (dx, dy) in {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}.items():
            self.bind(f"<{key}>", self._nudge(dx, dy))
            self.bind(f"<Shift-{key}>", self._nudge(dx, dy))
        self.canvas.bind("<Double-Button-1>", self._double_click)

    def _save_key(self, _event=None):
        """Ctrl+S: Save to Save Folder (the editable tree file); Ctrl+Shift+S: Export as Picture."""
        if _event is not None and _event.state & 0x1:
            self._export()
        else:
            self._save_tree()
        return "break"


def frame_dragged(box: tuple, mode: str, handle: str, x: float, y: float, steps: bool, free: bool) -> tuple:
    """A family member's portrait frame (middle x and y, width, height, angle) with a handle dragged to
    (x, y).  It stays centred on the portrait: a corner keeps its shape unless `free`, an edge
    stretches one way; the round handle turns it (in steps of 15 degrees with `steps`)."""
    cx, cy, w, h, angle = box
    if mode == "turn":
        turned = math.degrees(math.atan2(y - cy, x - cx)) + 90
        return cx, cy, w, h, (round(turned / 15) * 15 if steps else turned) % 360
    sx, sy = HANDLES[handle]
    lx, ly = ft.turn(x - cx, y - cy, -angle)
    nw = w if sx == 0 else 2 * sx * lx
    nh = h if sy == 0 else 2 * sy * ly
    if sx and sy and not free:
        scale = max(nw / w, nh / h)
        nw, nh = w * scale, h * scale
    return (cx, cy, min(ft.FRAME_MAX, max(ft.FRAME_MIN, nw)), min(ft.FRAME_MAX, max(ft.FRAME_MIN, nh)), angle)


def resized(raw: dict, handle: str, x: float, y: float, free: bool = False) -> dict:
    """The sticker with `handle` dragged to (x, y), the opposite side or corner staying put: a
    corner keeps the shape unless `free`; an edge stretches one side."""
    sx, sy = HANDLES[handle]
    w, h, a = raw["w"], raw["h"], raw["angle"]
    fx, fy = ft.turn(-sx * w / 2, -sy * h / 2, a)
    fixed = (raw["cx"] + fx, raw["cy"] + fy)
    lx, ly = ft.turn(x - fixed[0], y - fixed[1], -a)
    nw = w if sx == 0 else max(ft.STICKER_MIN, sx * lx)
    nh = h if sy == 0 else max(ft.STICKER_MIN, sy * ly)
    if sx and sy and not free:
        scale = max(nw / w, nh / h)
        nw, nh = max(ft.STICKER_MIN, w * scale), max(ft.STICKER_MIN, h * scale)
    ox, oy = ft.turn(sx * nw / 2, sy * nh / 2, a)
    return {**raw, "w": nw, "h": nh, "cx": fixed[0] + ox, "cy": fixed[1] + oy}
