"""Draw a Family Tree Maker scene (src/vf1_family_tree.py) into a PNG or JPG with Windows' own GDI+.

The patcher needs nothing beyond Python's standard library (README, Requirements), so the family
tree's picture is drawn by gdiplus.dll -- part of every Windows since XP, and what the patcher's
Origins companions already use to show the heads in Change Appearance -- through ctypes.  Nothing
here runs on another system: save_scene says False there and the tree's page is still written.
"""
from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes as W
from pathlib import Path

ENCODERS = {
    ".png": "{557CF406-1A04-11D3-9A73-0000F81EF32E}",
    ".jpg": "{557CF401-1A04-11D3-9A73-0000F81EF32E}",
    ".jpeg": "{557CF401-1A04-11D3-9A73-0000F81EF32E}",
}
JPEG_QUALITY = "{1D5BE4B5-FA4A-452D-9CDD-5DB35105E7EB}"
PIXEL_FORMAT_32BPP_ARGB = 0x26200A
UNIT_PIXEL = 2
FONT = "Segoe UI"


class GUID(ctypes.Structure):
    _fields_ = [("Data1", W.DWORD), ("Data2", W.WORD), ("Data3", W.WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> "GUID":
        h = text.strip("{}").replace("-", "")
        g = cls(int(h[0:8], 16), int(h[8:12], 16), int(h[12:16], 16))
        for k in range(8):
            g.Data4[k] = int(h[16 + 2 * k:18 + 2 * k], 16)
        return g


class StartupInput(ctypes.Structure):
    _fields_ = [("GdiplusVersion", ctypes.c_uint32), ("DebugEventCallback", ctypes.c_void_p),
                ("SuppressBackgroundThread", W.BOOL), ("SuppressExternalCodecs", W.BOOL)]


class PointF(ctypes.Structure):
    _fields_ = [("X", ctypes.c_float), ("Y", ctypes.c_float)]


class RectF(ctypes.Structure):
    _fields_ = [("X", ctypes.c_float), ("Y", ctypes.c_float), ("Width", ctypes.c_float), ("Height", ctypes.c_float)]


class EncoderParameter(ctypes.Structure):
    _fields_ = [("Guid", GUID), ("NumberOfValues", W.ULONG), ("Type", W.ULONG), ("Value", ctypes.c_void_p)]


class EncoderParameters(ctypes.Structure):
    _fields_ = [("Count", ctypes.c_uint), ("Parameter", EncoderParameter * 1)]


def available() -> bool:
    return sys.platform == "win32"


def _argb(colour: str, alpha: int = 255) -> int:
    """A colour for GDI+, `alpha` 0-255 opaque; transparent is nothing at all."""
    if colour == "transparent":
        return 0
    return (alpha << 24) | int(colour.lstrip("#"), 16)


_LIB: list = []                         # gdiplus.dll, loaded once (each load took a tenth of a second)
_LOCK = threading.RLock()               # one picture at a time: the editor may write its outputs in the background


def _gdiplus():
    if not _LIB:
        _LIB.append(ctypes.WinDLL("gdiplus"))
    return _LIB[0]


class _Gdi:
    def __init__(self) -> None:
        self.g = _gdiplus()
        token = ctypes.c_size_t()
        start = StartupInput(1, None, False, False)
        self._check(self.g.GdiplusStartup(ctypes.byref(token), ctypes.byref(start), None), "start")
        self.token = token
        self.fonts: dict[tuple, ctypes.c_void_p] = {}
        self.families: dict[tuple, tuple] = {}

    @staticmethod
    def _check(status: int, what: str) -> None:
        if status != 0:
            raise OSError(f"GDI+ could not {what} (status {status}).")

    def close(self) -> None:
        for font in self.fonts.values():
            self.g.GdipDeleteFont(font)
        for family, _ascent in self.families.values():
            self.g.GdipDeleteFontFamily(family)
        self.g.GdiplusShutdown(self.token)

    def family(self, name: str, style: int) -> tuple:
        """(the font family, its ascent as a share of its em): the player's font by name, else the
        patcher's own, else Windows' sans serif."""
        key = (name, style)
        if key not in self.families:
            fam = ctypes.c_void_p()
            if self.g.GdipCreateFontFamilyFromName(ctypes.c_wchar_p(name or FONT), None, ctypes.byref(fam)) != 0 \
                    and self.g.GdipCreateFontFamilyFromName(ctypes.c_wchar_p(FONT), None, ctypes.byref(fam)) != 0:
                self.g.GdipGetGenericFontFamilySansSerif(ctypes.byref(fam))
            em, ascent = ctypes.c_uint16(), ctypes.c_uint16()
            self.g.GdipGetEmHeight(fam, style, ctypes.byref(em))
            self.g.GdipGetCellAscent(fam, style, ctypes.byref(ascent))
            self.families[key] = (fam, ascent.value / max(1, em.value))
        return self.families[key]

    def font(self, size: float, bold: bool, name: str = "", italic: bool = False, underline: bool = False,
             strike: bool = False) -> tuple:
        style = (1 if bold else 0) | (2 if italic else 0) | (4 if underline else 0) | (8 if strike else 0)
        fam, ascent = self.family(name, style)
        key = (name, round(size * 4), style)
        if key not in self.fonts:
            font = ctypes.c_void_p()
            status = self.g.GdipCreateFont(fam, ctypes.c_float(size), style, UNIT_PIXEL, ctypes.byref(font))
            if status != 0:                     # a font without this style: its regular face
                status = self.g.GdipCreateFont(fam, ctypes.c_float(size), style & 12, UNIT_PIXEL, ctypes.byref(font))
            self._check(status, "make a font")
            self.fonts[key] = font
        return self.fonts[key], ascent


def save_scene(sc, present: dict, path: Path, scale: float = 1.0, quality: int = 92,
               transparent: bool = False) -> bool:
    """Draw the scene at `scale` and save it as `path` (.png, or .jpg / .jpeg) -- on its background
    colour, or (a PNG, `transparent`) on nothing.  False where GDI+ is not available (not Windows);
    OSError when it fails."""
    if not available():
        return False
    with _LOCK:
        return _save_scene(sc, present, path, scale, quality, transparent)


def _save_scene(sc, present: dict, path: Path, scale: float, quality: int, transparent: bool) -> bool:
    import vf1_family_tree as ft
    path = Path(path)
    encoder = ENCODERS.get(path.suffix.lower())
    if encoder is None:
        raise ValueError("The picture is saved as .png or .jpg.")
    gdi = _Gdi()
    g = gdi.g
    bitmap, graphics = ctypes.c_void_p(), ctypes.c_void_p()
    images: dict[str, ctypes.c_void_p] = {}
    fmt = ctypes.c_void_p()
    try:
        width, height = max(1, int(sc.width * scale)), max(1, int(sc.height * scale))
        gdi._check(g.GdipCreateBitmapFromScan0(width, height, 0, PIXEL_FORMAT_32BPP_ARGB, None,
                                               ctypes.byref(bitmap)), f"make a {width} x {height} picture")
        gdi._check(g.GdipGetImageGraphicsContext(bitmap, ctypes.byref(graphics)), "draw")
        g.GdipSetSmoothingMode(graphics, 4)                 # anti-alias
        g.GdipSetTextRenderingHint(graphics, 4)             # anti-alias text
        g.GdipSetInterpolationMode(graphics, 5)             # nearest neighbour: the heads stay crisp
        g.GdipSetPixelOffsetMode(graphics, 4)               # half
        g.GdipScaleWorldTransform(graphics, ctypes.c_float(scale), ctypes.c_float(scale), 0)
        clear = 0 if transparent else _argb(sc.background)
        if clear == 0 and not transparent:
            # A "transparent" background is white, as the Family Tree Maker shows it (the owner,
            # 2026-10-08): a see-through PNG looked dark in a picture viewer, and a JPG holds none.
            clear = 0xFFFFFFFF
        g.GdipGraphicsClear(graphics, clear)
        typographic = ctypes.c_void_p()
        g.GdipStringFormatGetGenericTypographic(ctypes.byref(typographic))
        g.GdipCloneStringFormat(typographic, ctypes.byref(fmt))
        for name, sheet in present.items():
            image = ctypes.c_void_p()
            if g.GdipLoadImageFromFile(ctypes.c_wchar_p(str(sheet)), ctypes.byref(image)) == 0:
                images[name] = image
        for item in sc.items:
            _draw(gdi, graphics, fmt, images, item, ft, (sc.width, sc.height))
        clsid = GUID.parse(encoder)
        params = None
        if path.suffix.lower() in (".jpg", ".jpeg"):
            value = ctypes.c_ulong(max(1, min(100, quality)))
            params = EncoderParameters(1)
            params.Parameter[0] = EncoderParameter(GUID.parse(JPEG_QUALITY), 1, 4,
                                                   ctypes.cast(ctypes.byref(value), ctypes.c_void_p))
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        gdi._check(g.GdipSaveImageToFile(bitmap, ctypes.c_wchar_p(str(temp)), ctypes.byref(clsid),
                                         ctypes.byref(params) if params is not None else None), "save the picture")
        temp.replace(path)
        return True
    finally:
        for image in images.values():
            if image:
                g.GdipDisposeImage(image)
        if fmt:
            g.GdipDeleteStringFormat(fmt)
        if graphics:
            g.GdipDeleteGraphics(graphics)
        if bitmap:
            g.GdipDisposeImage(bitmap)
        gdi.close()


def _points(points) -> tuple:
    arr = (PointF * len(points))(*[PointF(float(x), float(y)) for x, y in points])
    return arr, len(points)


def _rounded(g, x: float, y: float, w: float, h: float, r: float) -> ctypes.c_void_p:
    path = ctypes.c_void_p()
    g.GdipCreatePath(0, ctypes.byref(path))
    d = min(2 * r, w, h)
    f = ctypes.c_float
    if d <= 0:                          # square corners: GDI+ draws nothing for an arc of no size
        g.GdipAddPathRectangle(path, f(x), f(y), f(w), f(h))
        return path
    g.GdipAddPathArc(path, f(x), f(y), f(d), f(d), f(180), f(90))
    g.GdipAddPathArc(path, f(x + w - d), f(y), f(d), f(d), f(270), f(90))
    g.GdipAddPathArc(path, f(x + w - d), f(y + h - d), f(d), f(d), f(0), f(90))
    g.GdipAddPathArc(path, f(x), f(y + h - d), f(d), f(d), f(90), f(90))
    g.GdipClosePathFigure(path)
    return path


def _backdrop(gdi: _Gdi, graphics, item, ft, width: float, height: float) -> None:
    """The background: its colour or gradient, then its picture (fill, stretch or tile), faded
    by `soften` percent (into whatever is under it: the colour, the gradient, or nothing)."""
    g = gdi.g
    f = ctypes.c_float
    if item.colour2:
        brush = ctypes.c_void_p()
        stops = ft.gradient_stops(item)
        start = PointF(0, 0)
        end = PointF(float(width), 0) if ft.RAINBOWS.get(item.colour2) == "across" else PointF(0, float(height))
        g.GdipCreateLineBrush(ctypes.byref(start), ctypes.byref(end), _argb(stops[0][0]), _argb(stops[-1][0]),
                              0, ctypes.byref(brush))
        if len(stops) > 2:
            colours = (ctypes.c_uint32 * len(stops))(*(_argb(c) for c, _at in stops))
            places = (ctypes.c_float * len(stops))(*(at for _c, at in stops))
            g.GdipSetLinePresetBlend(brush, colours, places, len(stops))
        g.GdipFillRectangle(graphics, brush, f(0), f(0), f(width), f(height))
        g.GdipDeleteBrush(brush)
    if item.picture is None:
        return
    image = ctypes.c_void_p()
    if g.GdipLoadImageFromFile(ctypes.c_wchar_p(str(item.picture)), ctypes.byref(image)) != 0:
        return
    try:
        pw, ph = ctypes.c_float(), ctypes.c_float()
        g.GdipGetImageDimension(image, ctypes.byref(pw), ctypes.byref(ph))
        pw, ph = pw.value or 1.0, ph.value or 1.0
        attributes = ctypes.c_void_p()
        if item.soften:
            matrix = ColorMatrix()
            for k in (0, 6, 12, 24):
                matrix.m[k] = 1.0
            matrix.m[18] = 1 - item.soften / 100
            g.GdipCreateImageAttributes(ctypes.byref(attributes))
            g.GdipSetImageAttributesColorMatrix(attributes, 0, True, ctypes.byref(matrix), None, 0)
        if item.fit == "tile":
            brush = ctypes.c_void_p()
            g.GdipCreateTextureIA(image, attributes if attributes else None, f(0), f(0), f(pw), f(ph),
                                  ctypes.byref(brush))
            g.GdipFillRectangle(graphics, brush, f(0), f(0), f(width), f(height))
            g.GdipDeleteBrush(brush)
        else:
            g.GdipSetInterpolationMode(graphics, 7)              # high quality for a photograph
            dx, dy, dw, dh = 0.0, 0.0, width, height
            if item.fit == "stretch":
                sx, sy, sw, sh = 0.0, 0.0, pw, ph
            elif item.fit == "cover":                            # fill the page, cutting off the edges
                scale = max(width / pw, height / ph)
                sw, sh = width / scale, height / scale
                sx, sy = (pw - sw) / 2, (ph - sh) / 2
            else:                                                # the whole picture, as large as fits
                scale = min(width / pw, height / ph)
                sx, sy, sw, sh = 0.0, 0.0, pw, ph
                dw, dh = pw * scale, ph * scale
                dx, dy = (width - dw) / 2, (height - dh) / 2
            g.GdipDrawImageRectRect(graphics, image, f(dx), f(dy), f(dw), f(dh), f(sx), f(sy), f(sw), f(sh),
                                    UNIT_PIXEL, attributes if attributes else None, None, None)
            g.GdipSetInterpolationMode(graphics, 5)
        if attributes:
            g.GdipDisposeImageAttributes(attributes)
    finally:
        g.GdipDisposeImage(image)


def _draw(gdi: _Gdi, graphics, fmt, images: dict, item, ft, size: tuple = (0, 0)) -> None:
    g = gdi.g
    f = ctypes.c_float
    if isinstance(item, ft.Text) and getattr(item, "angle", 0.0):
        # Words turned with their portrait (Edits.turn_words): drawn upright, the page turned about them.
        import dataclasses
        state = ctypes.c_uint()
        g.GdipSaveGraphics(graphics, ctypes.byref(state))
        g.GdipTranslateWorldTransform(graphics, f(item.x), f(item.y), 0)
        g.GdipRotateWorldTransform(graphics, f(item.angle), 0)
        g.GdipTranslateWorldTransform(graphics, f(-item.x), f(-item.y), 0)
        _draw(gdi, graphics, fmt, images, dataclasses.replace(item, angle=0.0), ft, size)
        g.GdipRestoreGraphics(graphics, state)
        return
    if isinstance(item, ft.Text) and (getattr(item, "mirror_h", False) or getattr(item, "mirror_v", False)):
        # Mirrored words (Edits.flip_words): drawn as usual, the page mirrored about them.
        import dataclasses
        state = ctypes.c_uint()
        my = item.y - item.size * 0.35
        g.GdipSaveGraphics(graphics, ctypes.byref(state))
        g.GdipTranslateWorldTransform(graphics, f(item.x), f(my), 0)
        g.GdipScaleWorldTransform(graphics, f(-1.0 if item.mirror_h else 1.0), f(-1.0 if item.mirror_v else 1.0), 0)
        g.GdipTranslateWorldTransform(graphics, f(-item.x), f(-my), 0)
        _draw(gdi, graphics, fmt, images, dataclasses.replace(item, mirror_h=False, mirror_v=False), ft, size)
        g.GdipRestoreGraphics(graphics, state)
        return
    if isinstance(item, ft.Backdrop):
        _backdrop(gdi, graphics, item, ft, *size)
    elif isinstance(item, ft.Line):
        pen = ctypes.c_void_p()
        g.GdipCreatePen1(_argb(item.colour, _alpha(item)), f(item.width), 0, ctypes.byref(pen))
        g.GdipSetPenLineJoin(pen, 2)                        # round
        if item.dash:
            g.GdipSetPenDashStyle(pen, ft.GDI_DASHES[item.dash])
        arr, n = _points(item.points)
        g.GdipDrawLines(graphics, pen, arr, n)
        g.GdipDeletePen(pen)
    elif isinstance(item, ft.Poly):
        arr, n = _points(item.points)
        if item.fill:
            brush = ctypes.c_void_p()
            g.GdipCreateSolidFill(_argb(item.fill, _alpha(item)), ctypes.byref(brush))
            g.GdipFillPolygon(graphics, brush, arr, n, 0)          # alternate: a ring stays a ring
            g.GdipDeleteBrush(brush)
        if item.width > 0 and item.stroke:
            pen = ctypes.c_void_p()
            g.GdipCreatePen1(_argb(item.stroke, _alpha(item)), f(item.width), 0, ctypes.byref(pen))
            g.GdipSetPenLineJoin(pen, 2)
            g.GdipDrawPolygon(graphics, pen, arr, n)
            g.GdipDeletePen(pen)
    elif isinstance(item, ft.Shape):
        pen, brush = ctypes.c_void_p(), ctypes.c_void_p()
        alpha = int(255 * max(0.0, min(1.0, item.opacity))) << 24
        if item.width > 0:
            g.GdipCreatePen1(_argb(item.stroke, _alpha(item)), f(item.width), 0, ctypes.byref(pen))
            g.GdipSetPenLineJoin(pen, 2)                    # round: no spike at a heart's dip or a star's point
            if item.dash:
                g.GdipSetPenDashStyle(pen, ft.GDI_DASHES[item.dash])
        if item.fill:
            g.GdipCreateSolidFill(_argb(item.fill, alpha >> 24), ctypes.byref(brush))
        state = ctypes.c_uint()
        if item.angle:                                   # turned about its middle
            mx, my = item.x + item.w / 2, item.y + item.h / 2
            g.GdipSaveGraphics(graphics, ctypes.byref(state))
            g.GdipTranslateWorldTransform(graphics, f(mx), f(my), 0)
            g.GdipRotateWorldTransform(graphics, f(item.angle), 0)
            g.GdipTranslateWorldTransform(graphics, f(-mx), f(-my), 0)
        corners = ft.outline(item.kind, item.x, item.y, item.w, item.h)
        if item.kind in ("ellipse", "circle"):
            ox, oy, ow, oh = ft.oval_box(item.kind, item.x, item.y, item.w, item.h)
            if brush:
                g.GdipFillEllipse(graphics, brush, f(ox), f(oy), f(ow), f(oh))
            if pen:
                g.GdipDrawEllipse(graphics, pen, f(ox), f(oy), f(ow), f(oh))
        elif corners is not None:
            arr, n = _points(corners)
            if brush:
                g.GdipFillPolygon(graphics, brush, arr, n, 0)
            if pen:
                g.GdipDrawPolygon(graphics, pen, arr, n)
        else:
            path = _rounded(g, item.x, item.y, item.w, item.h, item.radius)
            if brush:
                g.GdipFillPath(graphics, brush, path)
            if pen:
                g.GdipDrawPath(graphics, pen, path)
            g.GdipDeletePath(path)
        if item.angle:
            g.GdipRestoreGraphics(graphics, state)
        if brush:
            g.GdipDeleteBrush(brush)
        if pen:
            g.GdipDeletePen(pen)
    elif isinstance(item, ft.Head):
        image = images.get(item.sheet)
        if image is not None:
            w, h = ft.HEAD_W * ft.HEAD_SCALE * item.scale, ft.HEAD_H * ft.HEAD_SCALE * item.scale
            attributes = _faded(gdi, item.opacity)
            g.GdipDrawImageRectRect(graphics, image, f(item.x), f(item.y), f(w), f(h),
                                    f(ft.HEAD_FRAME * ft.HEAD_W), f(item.row * ft.HEAD_H), f(ft.HEAD_W),
                                    f(ft.HEAD_H), UNIT_PIXEL, attributes if attributes else None, None, None)
            if attributes:
                g.GdipDisposeImageAttributes(attributes)
    elif isinstance(item, ft.Sticker):
        _sticker(gdi, graphics, images, item)
    elif isinstance(item, ft.Text) and item.runs:
        _draw_runs(gdi, graphics, fmt, item, ft)
    elif isinstance(item, ft.Text):
        font, ascent = gdi.font(item.size, item.bold, item.font, item.italic, item.underline, item.strike)
        brush = ctypes.c_void_p()
        g.GdipCreateSolidFill(_argb(item.colour, _alpha(item)), ctypes.byref(brush))
        top = item.y - item.size * ascent
        if item.centre:
            g.GdipSetStringFormatAlign(fmt, 1)
            rect = RectF(item.x - 2000, top, 4000, item.size * 2)
        elif item.end:                          # right-aligned: the words end at x
            g.GdipSetStringFormatAlign(fmt, 2)
            rect = RectF(item.x - 20000, top, 20000, item.size * 2)
        else:
            g.GdipSetStringFormatAlign(fmt, 0)
            rect = RectF(item.x, top, 20000, item.size * 2)
        g.GdipDrawString(graphics, ctypes.c_wchar_p(item.text), -1, font, ctypes.byref(rect), fmt, brush)
        g.GdipDeleteBrush(brush)


MEASURE_TRAILING_SPACES = 0x800


def _draw_runs(gdi: _Gdi, graphics, fmt, item, ft) -> None:
    """A formatted Text (a portrait's own words, formatted word by word): each run measured in its
    own font, the whole line centred (or started) where the Text says, and each run drawn after the
    one before it -- a superscript or subscript smaller, raised or lowered (ft.run_look)."""
    g = gdi.g
    own = ctypes.c_void_p()                     # the spaces at a run's ends measured too
    gdi._check(g.GdipCloneStringFormat(fmt, ctypes.byref(own)), "measure words")
    try:
        flags = ctypes.c_int()
        g.GdipGetStringFormatFlags(own, ctypes.byref(flags))
        g.GdipSetStringFormatFlags(own, flags.value | MEASURE_TRAILING_SPACES)
        g.GdipSetStringFormatAlign(own, 0)
        pieces = []
        for text, style in item.runs:
            look = ft.run_look(item, style)
            font, ascent = gdi.font(look["size"], look["bold"], item.font, look["italic"], look["underline"],
                                    look["strike"])
            box = RectF()
            g.GdipMeasureString(graphics, ctypes.c_wchar_p(text), -1, font,
                                ctypes.byref(RectF(0, 0, 20000, look["size"] * 2)), own, ctypes.byref(box),
                                None, None)
            pieces.append((text, look, font, ascent, box.Width))
        total = sum(p[4] for p in pieces)
        x = item.x - total / 2 if item.centre else item.x - total if item.end else item.x
        for text, look, font, ascent, width in pieces:
            brush = ctypes.c_void_p()
            g.GdipCreateSolidFill(_argb(look["colour"], _alpha(item)), ctypes.byref(brush))
            top = item.y + look["dy"] - look["size"] * ascent
            g.GdipDrawString(graphics, ctypes.c_wchar_p(text), -1, font,
                             ctypes.byref(RectF(x, top, 20000, look["size"] * 2)), own, brush)
            g.GdipDeleteBrush(brush)
            x += width
    finally:
        g.GdipDeleteStringFormat(own)


class ColorMatrix(ctypes.Structure):
    _fields_ = [("m", ctypes.c_float * 25)]


def _alpha(item) -> int:
    """An item's opacity as GDI+'s alpha, 0-255."""
    return int(255 * max(0.0, min(1.0, item.opacity)))


def _faded(gdi: _Gdi, opacity: float):
    """Image attributes that draw a picture `opacity` opaque (None when it is wholly opaque)."""
    if opacity >= 1:
        return None
    matrix = ColorMatrix()
    for k in (0, 6, 12, 24):
        matrix.m[k] = 1.0
    matrix.m[18] = max(0.0, opacity)
    attributes = ctypes.c_void_p()
    gdi.g.GdipCreateImageAttributes(ctypes.byref(attributes))
    gdi.g.GdipSetImageAttributesColorMatrix(attributes, 0, True, ctypes.byref(matrix), None, 0)
    return attributes


def _sticker(gdi: _Gdi, graphics, images: dict, s) -> None:
    """A sticker: a picture, or a text box (its fill, border and words), moved to its middle,
    turned, mirrored and faded."""
    g = gdi.g
    f = ctypes.c_float
    state = ctypes.c_uint()
    g.GdipSaveGraphics(graphics, ctypes.byref(state))
    try:
        g.GdipTranslateWorldTransform(graphics, f(s.cx), f(s.cy), 0)
        g.GdipRotateWorldTransform(graphics, f(s.angle), 0)
        g.GdipScaleWorldTransform(graphics, f(-1 if s.flip_h else 1), f(-1 if s.flip_v else 1), 0)
        x, y, w, h = -s.w / 2, -s.h / 2, s.w, s.h
        if s.picture is not None:
            key = "sticker:" + str(s.picture)
            if key not in images:
                image = ctypes.c_void_p()
                images[key] = image if g.GdipLoadImageFromFile(ctypes.c_wchar_p(str(s.picture)),
                                                               ctypes.byref(image)) == 0 else None
            image = images[key]
            if image is None:
                return
            pw, ph = ctypes.c_float(), ctypes.c_float()
            g.GdipGetImageDimension(image, ctypes.byref(pw), ctypes.byref(ph))
            attributes = ctypes.c_void_p()
            if s.opacity < 1:
                matrix = ColorMatrix()
                for k in (0, 6, 12, 24):
                    matrix.m[k] = 1.0
                matrix.m[18] = max(0.0, s.opacity)
                g.GdipCreateImageAttributes(ctypes.byref(attributes))
                g.GdipSetImageAttributesColorMatrix(attributes, 0, True, ctypes.byref(matrix), None, 0)
            g.GdipSetInterpolationMode(graphics, 7)
            g.GdipDrawImageRectRect(graphics, image, f(x), f(y), f(w), f(h), f(0), f(0), pw, ph, UNIT_PIXEL,
                                    attributes if attributes else None, None, None)
            if attributes:
                g.GdipDisposeImageAttributes(attributes)
            return
        alpha = int(255 * max(0.0, min(1.0, s.opacity)))
        if s.fill:
            brush = ctypes.c_void_p()
            fill_alpha = int(alpha * s.fill_opacity / 100)
            g.GdipCreateSolidFill(_argb(s.fill, fill_alpha), ctypes.byref(brush))
            if s.shape == "ellipse":
                g.GdipFillEllipse(graphics, brush, f(x), f(y), f(w), f(h))
            else:
                g.GdipFillRectangle(graphics, brush, f(x), f(y), f(w), f(h))
            g.GdipDeleteBrush(brush)
        if s.border and s.border_width > 0:
            pen = ctypes.c_void_p()
            g.GdipCreatePen1(_argb(s.border, alpha), f(s.border_width), UNIT_PIXEL,
                             ctypes.byref(pen))
            if s.shape == "ellipse":
                g.GdipDrawEllipse(graphics, pen, f(x), f(y), f(w), f(h))
            else:
                g.GdipDrawRectangle(graphics, pen, f(x), f(y), f(w), f(h))
            g.GdipDeletePen(pen)
        if s.text:
            font, _ascent = gdi.font(s.size, s.bold, s.font, s.italic, s.underline, s.strike)
            fmt = ctypes.c_void_p()
            g.GdipCreateStringFormat(0x4000, 0, ctypes.byref(fmt))      # 0x4000: clip to the box
            g.GdipSetStringFormatAlign(fmt, {"left": 0, "centre": 1, "right": 2}[s.align])
            g.GdipSetStringFormatLineAlign(fmt, {"top": 0, "middle": 1, "bottom": 2}[s.valign])
            brush = ctypes.c_void_p()
            g.GdipCreateSolidFill(_argb(s.colour, alpha), ctypes.byref(brush))
            pad = s.border_width + 4 if s.border else 4
            rect = RectF(x + pad, y + pad, max(1.0, w - 2 * pad), max(1.0, h - 2 * pad))
            g.GdipDrawString(graphics, ctypes.c_wchar_p(s.text), -1, font, ctypes.byref(rect), fmt, brush)
            g.GdipDeleteBrush(brush)
            g.GdipDeleteStringFormat(fmt)
    finally:
        g.GdipRestoreGraphics(graphics, state)
        g.GdipSetInterpolationMode(graphics, 5)


def render_sticker(s, path: Path, zoom: float = 1.0) -> tuple[float, float] | None:
    """One sticker alone, at `zoom`, on a clear PNG the size of its turned bounds (for the
    editor's canvas, which cannot turn or fade a picture itself): where that PNG's top left goes
    on the zoomed canvas, or None where GDI+ is not available."""
    import dataclasses
    import vf1_family_tree as ft
    s = dataclasses.replace(s, cx=s.cx * zoom, cy=s.cy * zoom, w=s.w * zoom, h=s.h * zoom, size=s.size * zoom,
                            border_width=s.border_width * zoom)
    x0, y0, x1, y1 = s.bounds()
    x0, y0 = int(x0) - 2, int(y0) - 2
    moved = dataclasses.replace(s, cx=s.cx - x0, cy=s.cy - y0)
    scene = ft.Scene(int(x1) + 3 - x0, int(y1) + 3 - y0, "#000000", [moved])
    return (x0, y0) if save_scene(scene, {}, path, transparent=True) else None


class _BitmapData(ctypes.Structure):
    _fields_ = [("Width", ctypes.c_uint), ("Height", ctypes.c_uint), ("Stride", ctypes.c_int),
                ("PixelFormat", ctypes.c_int), ("Scan0", ctypes.c_void_p), ("Reserved", ctypes.c_size_t)]


class _Rect(ctypes.Structure):
    _fields_ = [("X", ctypes.c_int), ("Y", ctypes.c_int), ("Width", ctypes.c_int), ("Height", ctypes.c_int)]


def backdrop_pixels(item, width: float, height: float, scale: float = 1.0) -> tuple[int, int, bytes] | None:
    """The page's background (a Family Tree Maker Backdrop) drawn exactly as save_scene draws it, at
    `scale`, on nothing (a "transparent" colour stays see-through): (width, height, its pixels as
    B, G, R, A bytes row by row, no padding), or None where GDI+ is not available.  What the Auto-colour
    family lines button reads the background's colours under each line from (vf1_line_colours)."""
    if not available():
        return None
    import vf1_family_tree as ft
    gdi = _Gdi()
    g = gdi.g
    bitmap, graphics = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        w, h = max(1, int(width * scale)), max(1, int(height * scale))
        gdi._check(g.GdipCreateBitmapFromScan0(w, h, 0, PIXEL_FORMAT_32BPP_ARGB, None, ctypes.byref(bitmap)),
                   f"make a {w} x {h} picture")
        gdi._check(g.GdipGetImageGraphicsContext(bitmap, ctypes.byref(graphics)), "draw")
        g.GdipSetSmoothingMode(graphics, 4)
        g.GdipSetInterpolationMode(graphics, 5)
        g.GdipSetPixelOffsetMode(graphics, 4)
        g.GdipScaleWorldTransform(graphics, ctypes.c_float(scale), ctypes.c_float(scale), 0)
        g.GdipGraphicsClear(graphics, _argb(item.colour))
        _backdrop(gdi, graphics, item, ft, float(width), float(height))
        g.GdipDeleteGraphics(graphics)
        graphics = ctypes.c_void_p()
        rect, data = _Rect(0, 0, w, h), _BitmapData()
        gdi._check(g.GdipBitmapLockBits(bitmap, ctypes.byref(rect), 1, PIXEL_FORMAT_32BPP_ARGB, ctypes.byref(data)),
                   "read the picture")
        try:
            stride = data.Stride
            rows = [ctypes.string_at(data.Scan0 + y * stride, w * 4) for y in range(h)]
        finally:
            g.GdipBitmapUnlockBits(bitmap, ctypes.byref(data))
        return w, h, b"".join(rows)
    finally:
        if graphics:
            g.GdipDeleteGraphics(graphics)
        if bitmap:
            g.GdipDisposeImage(bitmap)
        gdi.close()
