"""The Picture Maker's "Every picture" tab (patcher/vf1_game_art.py, vf1_art_sheets.py, vf1_small_formats.py and the
tab in vf1_picture_maker.py).  The area modules (vf1_art_meters / _ui / _house / _misc / _fonts) have their own
tests (tests/test_art_*.py) that run the game's own drawing code for every assembled picture.

Without the game: a synthetic game folder (a few sheets from the image table, a JPEG-free set) checks the
catalogue (every file whole, every cell, the unused labels, the categories), the tab (find, show, open, preview,
Save PNG and Save all in folders by category at every size, whole size or cut) and the BMP / GIF readers.

With VF1_VANILLA_DIR (only read): the image table equals the exe's 0x4F2D00; the game's own grid makers 0x40AE10
(a grid) and 0x401000 (a strip) and GetCellRect 0x40AD40 run in Unicorn for every cell of every grid the catalogue
lists, and the catalogue's rectangles must be theirs; every picture file in the game folder is in the catalogue;
every picture draws; icon.bmp and DRM\\logo1.gif read pixel for pixel as Pillow reads them.
"""
from __future__ import annotations

import faulthandler
import os
import struct
import tkinter as tk
from pathlib import Path

import pytest
import vf1_art_sheets as sheets
import vf1_game_art as ga
import vf1_picture_image as pi
import vf1_picture_maker as pm
import vf1_small_formats as sf


# ------------------------------------------------------------------ a synthetic game folder
def _sheet(w: int, h: int, cols: int, rows: int, seed: int) -> pi.Image:
    img = pi.Image(w, h)
    cw, ch = w // cols, h // rows
    for y in range(h):
        for x in range(w):
            c, r = x // cw, y // ch
            if x % cw == 0:
                continue                              # each cell's first column is see-through
            at = (y * w + x) * 4
            img.data[at:at + 4] = bytes(((seed * 40) % 256, (c * 30) % 256, (r * 50) % 256, 255))
    return img


SYNTHETIC = {   # file: (width, height, columns, rows)
    "btn_blue.png": (30, 8, 3, 1), "fridgeStates.png": (12, 10, 3, 2), "toolbox.png": (7, 5, 1, 1),
    "checkmark.png": (6, 6, 1, 1), "LoadColor.png": (4, 4, 1, 1), "carrying.png": (26, 12, 13, 6),
    "help1.jpg.png": (5, 5, 1, 1),
}


@pytest.fixture(scope="module")
def game(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("game") / "Virtual Families"
    images = folder / "Images"
    images.mkdir(parents=True)
    for k, (name, (w, h, cols, rows)) in enumerate(SYNTHETIC.items()):
        if name.endswith(".jpg.png"):
            continue
        (images / name).write_bytes(_sheet(w, h, cols, rows, k).to_png())
    (images / "unknown_extra.png").write_bytes(_sheet(4, 4, 1, 1, 9).to_png())
    (images / "blank.png").write_bytes(pi.Image(3, 3).to_png())
    (folder / "Assets").mkdir()
    (folder / "Assets" / "animpts.dat").write_bytes(b"")          # the folder the window offers needs it
    return folder


@pytest.fixture
def files(game) -> ga.GameFiles:
    return ga.GameFiles(game)


def test_cell_rect_matches_the_grid_rules():
    assert ga.cell_rect((30, 8), 3, 1, 2, 0) == (0, (20, 0, 30, 8))
    assert ga.cell_rect((12, 10), 3, 2, 1, 1) == (0, (4, 5, 8, 10))
    assert ga.cell_rect((12, 10), 3, 2, 7, 9) == (0, (8, 5, 12, 10))          # past the last: the last
    assert ga.cell_rect((120, 100), 24, 50, 13, 3, 2) == (1, (10, 6, 20, 8))  # two files across
    assert ga.grid_shape(0x23) == (3, 1) and ga.grid_shape(0x35) is None and ga.grid_shape(0x16) == (3, 2)


def test_catalogue_lists_every_file_whole_and_every_cell(files):
    cat = ga.catalogue(files)
    keys = [a.key for a in cat.arts]
    assert len(keys) == len(set(keys))
    by_key = {a.key: a for a in cat.arts}
    # a strip of three: whole plus three cells, each the game's cell
    assert by_key["sheets/btn_blue.png"].layers[0].rect == (0, 0, -1, -1)
    for k in range(3):
        assert by_key[f"sheets/btn_blue.png/{k}"].layers[0].rect == (10 * k, 0, 10 * k + 10, 8)
    assert [by_key[f"sheets/fridgestates.png/{k}"].layers[0].rect for k in range(6)] == [
        (0, 0, 4, 5), (4, 0, 8, 5), (8, 0, 12, 5), (0, 5, 4, 10), (4, 5, 8, 10), (8, 5, 12, 10)]
    assert len([k for k in keys if k.startswith("sheets/carrying.png/")]) == 78
    # unused pictures and cells are labelled, with the reason
    assert not by_key["sheets/loadcolor.png"].used and by_key["sheets/loadcolor.png"].title.endswith("(unused)")
    assert not by_key["sheets/checkmark.png"].used
    assert by_key["sheets/toolbox.png"].used
    unused_cell = by_key["sheets/carrying.png/12"]
    assert not unused_cell.used and "(unused)" in unused_cell.title and unused_cell.why
    # a file no code names, and the patcher's own pictures
    assert not by_key["sheets/unknown_extra.png"].used and by_key["sheets/unknown_extra.png"].why == sheets.NOT_NAMED
    patcher = [a for a in cat.arts if a.patcher]
    assert patcher and all("(patcher)" in a.title and a.category.startswith("Patcher's own pictures") for a in patcher)
    for art in cat.arts:
        assert art.category.split("/")[0] in ga.CATEGORY_ORDER, art.category
        assert art.why, art.key
        assert ("(unused)" in art.title) == (not art.used)


def test_draw_and_the_layer_kinds(files):
    art = ga.Art("x", "Store", "x", (pi.Draw("cell", "fridgeStates.png", (4, 5, 8, 10), 2, 3),
                                    ga.Fill(0, 0, 2, 2, (1, 2, 3, 255))), True, "w", "c")
    image = ga.draw(files, art)
    assert (image.width, image.height) == (6, 8)
    assert image.pixel(0, 0) == (1, 2, 3, 255)
    assert image.pixel(2, 3) == (0, 0, 0, 0)                  # the cell's see-through first column
    assert image.pixel(3, 3)[3] == 255

    class Made:
        what, file, rect, x, y, scale, alpha = "made", "computed:x", (0, 0, 2, 1), 5, 5, 1.0, 1.0

        @staticmethod
        def make(_files):
            out = pi.Image(2, 1)
            out.data[:] = bytes((9, 9, 9, 255)) * 2
            return out
    made = ga.draw(files, ga.Art("y", "Store", "y", (Made(),), True, "w"))
    assert (made.width, made.height) == (2, 1) and made.pixel(1, 0) == (9, 9, 9, 255)


def test_find_and_the_words(files):
    cat = ga.catalogue(files)
    assert all("fridge" in (a.title + a.key).lower() for a in cat.find("fridge"))
    assert cat.find("") == cat.arts
    art = cat.arts[0]
    assert (ga.CHECK in art.note()) == (not art.checked)


@pytest.fixture
def window(game):
    root = tk.Tk()
    root.withdraw()
    win = pm.PictureMaker(root, game_folders=[game])
    win.quiet = True
    yield win
    win.close()
    root.destroy()


def test_the_tab_finds_shows_and_saves(window, game, tmp_path):
    cat = window.ensure_catalogue()
    assert window.all_count_var.get() == f"{len(cat.arts)} of {len(cat.arts)} pictures"
    window.select_art("sheets/fridgestates.png/4")
    assert "Cell 5" in window.all_preview["info"].cget("text")
    assert window.shown["all"].width == 4
    out = window.save_png("all", str(tmp_path / "one.png"))
    saved = pi.decode_png(out.read_bytes())
    assert (saved.width, saved.height) == (3 + 2 * pi.MARGIN, 5 + 2 * pi.MARGIN)      # cut to the drawn pixels
    window.whole_var.set(True)
    saved = pi.decode_png(window.save_png("all", str(tmp_path / "whole.png")).read_bytes())
    assert (saved.width, saved.height) == (4, 5)                                      # the cell's whole size
    window.select_art("sheets/blank.png")
    assert "see-through" in window.all_preview["info"].cget("text")
    # only the unused
    window.show_var.set(pm.SHOW_CHOICES[2])
    window._fill_all()
    window.open_all_groups()
    assert window.all_nodes and all(not a.used for a in window.all_nodes.values())
    # find
    window.show_var.set(pm.SHOW_CHOICES[0])
    window.search_var.set("btn_blue")
    window._fill_all()
    window.open_all_groups()
    assert {a.key for a in window.all_nodes.values()} == {"sheets/btn_blue.png"} | {
        f"sheets/btn_blue.png/{k}" for k in range(3)}
    # Save all shown at 2x: a folder per category
    window.size_var.set("2x")
    target = window.save_every(group=False, folder=str(tmp_path))
    pngs = sorted(p.relative_to(target).as_posix() for p in target.rglob("*.png"))
    assert len(pngs) == 4
    assert all(p.startswith("Buttons and controls/Picture files/") for p in pngs)
    cell = pi.decode_png(sorted((target / "Buttons and controls" / "Picture files" / "btn_blue").glob(
        "Cell 1 *.png"))[0].read_bytes())
    assert (cell.width, cell.height) == (20, 16)                                      # 10 x 8 at 2x
    # Save all in a group, at a custom size
    window.search_var.set("")
    window._fill_all()
    window.open_all_groups()
    node = next(n for n, path in window.all_groups.items() if path == "Furniture and objects")
    window.all_tree.selection_set(node)
    window.size_var.set("custom")
    window.width_var.set("50")
    target = window.save_every(group=True, folder=str(tmp_path))
    found = list(target.rglob("*.png"))
    assert found and all(pi.decode_png(p.read_bytes()).width == 50 for p in found)
    assert "picture(s) saved" in window.last_message


def test_save_arts_reports_missing_and_stops(files, tmp_path):
    arts = [ga.Art("a", "Store", "Nothing here", (), False, "w"),
            ga.Art("b", "Store", "Toolbox", (ga.whole("toolbox.png"),), True, "w")]
    saved, failed, blank = pm.save_arts(files, arts, tmp_path / "out", {"scale": 1})
    assert saved == 1 and len(failed) == 1 and blank == 0
    saved, failed, _ = pm.save_arts(files, arts, tmp_path / "out2", {"scale": 1}, progress=lambda d, t: d < 1)
    assert saved == 0


def test_quick_shrink_keeps_every_kth_pixel():
    image = _sheet(1000, 700, 10, 7, 1)
    small = pm.quick_shrink(image, 320)
    assert (small.width, small.height) == (250, 175)
    assert small.pixel(5, 7) == image.pixel(20, 28)


def test_bmp_and_gif_readers():
    from PIL import Image
    import io
    for mode in ("P", "RGB"):
        src = Image.new(mode, (5, 3))
        if mode == "P":
            src.putpalette([k % 256 for k in range(768)])
        src.putdata([(k * 7) % 200 if mode == "P" else (k * 9, k * 3, 255 - k) for k in range(15)])
        buf = io.BytesIO()
        src.save(buf, "BMP")
        got = sf.decode_bmp(buf.getvalue())
        assert bytes(got.data) == src.convert("RGBA").tobytes()
    src = Image.new("P", (6, 4))
    src.putpalette([k % 256 for k in range(768)])
    src.putdata([k % 5 for k in range(24)])
    buf = io.BytesIO()
    src.save(buf, "GIF", transparency=3)
    got = sf.decode_gif(buf.getvalue())
    want = bytearray(Image.open(io.BytesIO(buf.getvalue())).convert("RGBA").tobytes())
    for k in range(0, len(want), 4):
        if want[k + 3] == 0:
            want[k:k + 4] = bytes(4)
    assert bytes(got.data) == bytes(want)
    with pytest.raises(pi.PictureError):
        sf.decode_gif(b"GIF89a\x01")
    with pytest.raises(pi.PictureError):
        sf.decode_bmp(b"BMxx")


# ------------------------------------------------------------------ with the game
@pytest.fixture(scope="module")
def vanilla() -> Path:
    value = os.environ.get("VF1_VANILLA_DIR")
    if not value or not (Path(value) / "Virtual Families.exe").is_file():
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    return Path(value)


def test_image_table_is_the_games(vanilla):
    import pefile
    pe = pefile.PE(str(vanilla / "Virtual Families.exe"), fast_load=True)
    img = pe.get_memory_mapped_image()

    def cstr(address: int) -> str:
        at = address - 0x400000
        return img[at:img.index(b"\0", at)].decode("latin-1")
    table = {}
    at = 0x4F2D00 - 0x400000
    while True:
        w = struct.unpack_from("<12I", img, at)
        if w[1] == 0:
            break
        table[w[0]] = (cstr(w[1]), w[2], w[3], w[5] if w[4] else 1)
        at += 0x30
    assert table == ga.TABLE
    assert list(table) == list(ga.TABLE)
    assert cstr(0x4B2660) == ".png"                  # the two-file grids' names end in it


@pytest.fixture(scope="module")
def vanilla_catalogue(vanilla):
    files = ga.GameFiles(vanilla)
    return files, ga.catalogue(files)


def test_every_file_is_in_the_catalogue(vanilla, vanilla_catalogue):
    files, cat = vanilla_catalogue
    assert not cat.problems
    named = set()
    for art in cat.arts:
        for layer in art.layers:
            name = getattr(layer, "file", "")
            if name and not name.startswith(("patcher:", "computed:")):
                named.add(name.replace("\\", "/").lower())
    pictures = {k for k in files.names() if k.endswith((".png", ".jpg", ".gif", ".bmp"))}
    assert pictures - named == set()
    assert "root:icon.bmp" in named
    for art in cat.arts:
        assert ("(unused)" in art.title) == (not art.used)


def test_cell_rectangles_are_the_games(vanilla, vanilla_catalogue):
    """0x40AE10 / 0x401000 make every grid and strip from the file's size, and GetCellRect 0x40AD40 cuts every
    cell: the catalogue's rectangle for every cell must be the one the game's code gives."""
    from ui_emu import UiEmu
    from unicorn import UC_HOOK_CODE
    files, cat = vanilla_catalogue
    enabled = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        emu = UiEmu(vanilla)
    finally:
        if enabled:
            faulthandler.enable()
    sizes: dict[int, tuple[int, int]] = {}

    def picture_impl():                 # 0x40B350: the picture object for a file name (stood in: its size)
        name = bytes(emu.u.mem_read(emu._arg(0), 64)).split(b"\0")[0].decode("latin-1")
        w, h = files.size(name)
        surf = emu.alloc(0x20)
        emu.w32(surf + 8, w)
        emu.w32(surf + 0xC, h)
        this = emu.u.reg_read(__import__("unicorn").x86_const.UC_X86_REG_ECX)
        emu.w32(this, surf)
        emu._return(this, 4)
    emu.hooks[0x40B350] = picture_impl
    emu.u.hook_add(UC_HOOK_CODE, emu._code, begin=0x40B350, end=0x40B350)
    cells = {}
    for art in cat.arts:
        if art.key.startswith("sheets/") and art.key.count("/") == 2 and art.key.rsplit("/", 1)[1].isdigit():
            layer = art.layers[0]
            cells[(layer.file.lower(), int(art.key.rsplit("/", 1)[1]))] = (layer.file, tuple(layer.rect))
    checked = 0
    for image, (name, cols, rows, files_across) in ga.TABLE.items():
        if cols == 0 or files_across != 1 or not files.has(name):
            continue
        obj = emu.alloc(0x40)
        if rows:
            emu.call(0x40AE10, (emu.cstr(name), cols, rows), ecx=obj)
        else:
            emu.call(0x401000, (emu.cstr(name), cols), ecx=obj)
        out = emu.alloc(16)
        for row in range(rows or 1):
            for col in range(cols):
                emu.call(0x40AD40, (col, row, out), ecx=obj)
                rect = struct.unpack("<4i", emu.u.mem_read(out, 16))
                key = (files.path(name).name.lower(), row * cols + col)
                if key in cells:
                    assert cells[key][1] == rect, (name, row, col)
                    checked += 1
                assert ga.cell_rect(files.size(name), cols, rows or 1, col, row)[1] == rect
    assert checked > 2000


def test_every_picture_draws(vanilla, vanilla_catalogue):
    """Every picture but the people's sheet cells (their drawing is tested in test_picture_maker) draws."""
    files, cat = vanilla_catalogue
    for art in cat.arts:
        if art.category.startswith("People/") and "/" in art.key[7:]:
            continue
        if art.layers:
            ga.draw(files, art)


def test_odd_files_read_as_pillow_reads_them(vanilla):
    from PIL import Image
    icon = sf.decode_bmp((vanilla / "icon.bmp").read_bytes())
    assert bytes(icon.data) == Image.open(vanilla / "icon.bmp").convert("RGBA").tobytes()
    gif = vanilla / "Images" / "DRM" / "logo1.gif"
    got = sf.decode_gif(gif.read_bytes())
    want = bytearray(Image.open(gif).convert("RGBA").tobytes())
    for k in range(0, len(want), 4):
        if want[k + 3] == 0:
            want[k:k + 4] = bytes(4)
    assert bytes(got.data) == bytes(want)
