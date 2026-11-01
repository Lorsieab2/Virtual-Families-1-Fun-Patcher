"""patcher/vf1_jpeg.py shows Virtual Families 1's .jpg pictures exactly as the game decodes them.

* With VF1_VANILLA_DIR: the game folder's own libjpeg-9.dll runs in Unicorn the way SDL2_image's
  IMG_LoadJPG_RW calls it (tests/jpeg_emu.py), and vf1_jpeg.decode must give the same bytes for every
  .jpg under Images (Images\\DRM too) and every .jpg in patcher/payload/CustomImages.  The full sweep is
  release-only (slow, about half a minute); a 4:4:4 picture (VD_line-blue.jpg), a 4:2:0 map tile
  (MapX0Y2.jpg) and a progressive custom tile always run.  The DLL's own IDCT routines are also checked
  against the module's kernels on random blocks, and pictures Pillow writes in every sampling the
  module handles (and cut-short or damaged ones) are compared with the DLL.
* Without the game: Pillow-made pictures decode, exactly where libjpeg-turbo (Pillow) and libjpeg 9
  must agree (4:4:4 colour, grey, and 4:2:0 with flat colour: same integer IDCT, same colour tables, no
  upsampling of anything that varies) and closely otherwise; broken files raise PictureError.
"""
from __future__ import annotations

import io
import os
import random
from pathlib import Path

import pytest
import vf1_jpeg
from conftest import RELEASE_SKIP_REASON, ROOT, release_run
from vf1_picture_image import PictureError

CUSTOM = ROOT / "patcher" / "payload" / "CustomImages"
FAST = ("Images/VD_line-blue.jpg", "Images/MapX0Y2.jpg", "CustomImages/MapX0Y0.jpg")


def _game() -> Path | None:
    value = os.environ.get("VF1_VANILLA_DIR")
    if value and (Path(value) / "libjpeg-9.dll").is_file():
        return Path(value)
    return None


def _pictures() -> list[str]:
    """Every .jpg the sweep covers, as "Images/..." (vanilla) or "CustomImages/..." (the payload)."""
    names = []
    game = _game()
    if game is not None:
        names += sorted("Images/" + p.relative_to(game / "Images").as_posix()
                        for p in (game / "Images").rglob("*") if p.suffix.lower() == ".jpg")
    if CUSTOM.is_dir():
        names += sorted("CustomImages/" + p.name for p in CUSTOM.iterdir() if p.suffix.lower() == ".jpg")
    return names or list(FAST)


def _path(name: str) -> Path:
    if name.startswith("CustomImages/"):
        return CUSTOM / name.split("/", 1)[1]
    return _game() / name


def _rgb(image) -> bytes:
    n = image.width * image.height
    out = bytearray(3 * n)
    out[0::3], out[1::3], out[2::3] = image.data[0::4], image.data[1::4], image.data[2::4]
    return bytes(out)


@pytest.fixture(scope="module")
def emu():
    game = _game()
    if game is None:
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    pytest.importorskip("pefile")
    pytest.importorskip("unicorn")
    import faulthandler

    import jpeg_emu
    # Unicorn's memory set-up raises access violations it handles itself; pytest's faulthandler would
    # print a stack for them (as tests/test_picture_maker.py).
    was_on = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        return jpeg_emu.JpegEmu(game)
    finally:
        if was_on:
            faulthandler.enable()


def _same_as_the_game(emu, data: bytes) -> None:
    width, height, expected = emu.decode(data)
    image = vf1_jpeg.decode(data)
    assert (image.width, image.height) == (width, height)
    assert image.data[3::4] == b"\xFF" * (width * height)
    got = _rgb(image)
    if got != expected:
        wrong = sum(1 for a, b in zip(got, expected) if a != b)
        pytest.fail(f"{wrong} of {len(expected)} bytes differ from libjpeg-9.dll")


# ------------------------------------------------------------------ against the game's DLL


@pytest.mark.parametrize("name", _pictures())
def test_every_game_picture_matches_libjpeg9(emu, name, request):
    if name not in FAST and not release_run(request.config):
        pytest.skip(RELEASE_SKIP_REASON)
    path = _path(name)
    if not path.is_file():
        pytest.skip(f"{name} is not here")
    _same_as_the_game(emu, path.read_bytes())


@pytest.mark.parametrize("routine, cols, rows", [
    ("jpeg_idct_islow", 8, 8), ("jpeg_idct_16x16", 16, 16),
    ("jpeg_idct_16x8", 16, 8), ("jpeg_idct_8x16", 8, 16),
])
def test_idct_kernels_match_the_dll(emu, routine, cols, rows):
    rnd = random.Random(routine)
    for _ in range(60):
        coefficients = [0] * 64
        for _ in range(rnd.choice((1, 3, 12, 64))):
            coefficients[rnd.randrange(64)] = rnd.randint(-2000, 2000) if rnd.random() < 0.3 \
                else rnd.randint(-300, 300)
        quant = [rnd.randint(1, 8) for _ in range(64)]
        expected = emu.idct(routine, coefficients, quant, rows, cols)
        got = bytes(vf1_jpeg.idct([c * q for c, q in zip(coefficients, quant)], cols, rows))
        assert got == expected, (coefficients, quant)


def _pattern(width: int, height: int, mode: str = "RGB", seed: int = 1):
    Image = pytest.importorskip("PIL.Image")
    rnd = random.Random(seed)
    image = Image.new("RGB", (width, height))
    px = image.load()
    for y in range(height):
        for x in range(width):
            px[x, y] = ((x * 7 + y * 3) % 256,
                        (x * x + y * 5) % 256 if rnd.random() < 0.9 else rnd.randrange(256),
                        (y * 11 ^ x * 2) % 256)
    return image.convert(mode)


def _jpeg(image, **options) -> bytes:
    out = io.BytesIO()
    image.save(out, "JPEG", **options)
    return out.getvalue()


SAMPLINGS = ("4:4:4", "4:2:2", "4:2:0", "4:1:1")


@pytest.mark.parametrize("sampling", SAMPLINGS)
@pytest.mark.parametrize("progressive", (False, True), ids=("sequential", "progressive"))
def test_pillow_pictures_match_libjpeg9(emu, sampling, progressive):
    for size in ((37, 23), (1, 1), (130, 17)):
        data = _jpeg(_pattern(*size), quality=80, subsampling=sampling, progressive=progressive)
        _same_as_the_game(emu, data)


def test_grey_restart_and_colour_markers_match_libjpeg9(emu):
    _same_as_the_game(emu, _jpeg(_pattern(45, 33, "L")))
    _same_as_the_game(emu, _jpeg(_pattern(45, 33, "L"), progressive=True))
    _same_as_the_game(emu, _jpeg(_pattern(70, 50), subsampling="4:2:0", restart_marker_rows=1))
    base = _jpeg(_pattern(20, 20), subsampling="4:4:4")
    no_jfif = _without_jfif(base)
    # libjpeg 9: JFIF means YCbCr, then the Adobe transform, then the component ids
    _same_as_the_game(emu, _with_ids(base, b"RGB"))                   # JFIF wins: YCbCr
    _same_as_the_game(emu, _with_ids(no_jfif, b"RGB"))                # ids: RGB
    _same_as_the_game(emu, _with_adobe(no_jfif, 0))                   # Adobe 0: RGB despite ids 1 2 3
    _same_as_the_game(emu, _with_adobe(no_jfif, 1))
    _same_as_the_game(emu, _with_ids(no_jfif, b"\x04\x05\x06"))


def test_cut_short_and_damaged_pictures_match_libjpeg9(emu):
    data = _jpeg(_pattern(200, 120), subsampling="4:2:0", quality=90)
    for fraction in (0.3, 0.6, 0.99):
        _same_as_the_game(emu, data[:int(len(data) * fraction)])
    restarts = _jpeg(_pattern(200, 120), subsampling="4:2:0", quality=90, restart_marker_rows=1)
    _same_as_the_game(emu, restarts[:len(restarts) // 2])
    scan = restarts.find(b"\xFF\xDA") + 14
    for seed in range(4):
        rnd = random.Random(seed)
        damaged = bytearray(restarts)
        for _ in range(3):
            damaged[rnd.randrange(scan, len(restarts) - 2)] = rnd.randrange(256)
        _same_as_the_game(emu, bytes(damaged))


def _without_jfif(data: bytes) -> bytes:
    assert data[2:4] == b"\xFF\xE0"
    return data[:2] + data[4 + ((data[4] << 8) | data[5]):]


def _with_adobe(data: bytes, transform: int) -> bytes:
    return data[:2] + b"\xFF\xEE\x00\x0EAdobe\x00\x64\x00\x00\x00\x00" + bytes([transform]) + data[2:]


def _with_ids(data: bytes, ids: bytes) -> bytes:
    out = bytearray(data)
    sof = data.find(b"\xFF\xC0")
    sos = data.find(b"\xFF\xDA")
    for k, value in enumerate(ids):
        out[sof + 10 + 3 * k] = value
        out[sos + 5 + 2 * k] = value
    return bytes(out)


# ------------------------------------------------------------------ without the game


def _pillow_rgb(data: bytes) -> bytes:
    Image = pytest.importorskip("PIL.Image")
    return Image.open(io.BytesIO(data)).convert("RGB").tobytes()


@pytest.mark.parametrize("progressive", (False, True), ids=("sequential", "progressive"))
def test_444_and_grey_equal_pillow(progressive):
    """No upsampling: libjpeg-turbo's islow IDCT and colour tables are libjpeg 9's, bit for bit."""
    for mode in ("RGB", "L"):
        data = _jpeg(_pattern(41, 29, mode), quality=85, subsampling="4:4:4", progressive=progressive)
        image = vf1_jpeg.decode(data)
        assert (image.width, image.height) == (41, 29)
        assert _rgb(image) == _pillow_rgb(data)
        assert image.data[3::4] == b"\xFF" * (41 * 29)


def test_420_of_a_grey_picture_equals_pillow():
    """4:2:0 whose colour planes are flat: how the colour is brought up to size cannot matter."""
    Image = pytest.importorskip("PIL.Image")
    grey = _pattern(53, 35, "L").convert("RGB")
    data = _jpeg(grey, quality=90, subsampling="4:2:0")
    assert _rgb(vf1_jpeg.decode(data)) == _pillow_rgb(data)
    assert Image is not None


@pytest.mark.parametrize("sampling", ("4:2:0", "4:2:2"))
def test_subsampled_colour_is_close_to_pillow(sampling):
    """libjpeg 9 brings half-size colour up through a 16-point IDCT, Pillow's libjpeg-turbo with a
    triangle filter: on smooth colour the two agree within a few levels (on sharp colour edges they
    can differ by much more, which is why Pillow is no reference for the game's pictures)."""
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (64, 48))
    px = image.load()
    for y in range(48):
        for x in range(64):
            px[x, y] = (x * 4, y * 5, (x + y) * 2)
    data = _jpeg(image, quality=90, subsampling=sampling)
    got, ref = _rgb(vf1_jpeg.decode(data)), _pillow_rgb(data)
    diffs = [abs(a - b) for a, b in zip(got, ref)]
    assert sum(diffs) / len(diffs) < 1
    assert max(diffs) <= 8


@pytest.mark.parametrize("data", [
    b"",
    b"not a picture",
    b"\xFF\xD8",
    b"\xFF\xD8\xFF\xD9",
    b"\x89PNG\r\n\x1a\n" + bytes(40),
], ids=("empty", "text", "only-start", "no-picture", "png"))
def test_broken_files_raise_picture_error(data):
    with pytest.raises(PictureError):
        vf1_jpeg.decode(data)


def test_damaged_headers_raise_picture_error():
    data = _jpeg(_pattern(20, 20), subsampling="4:4:4")
    with pytest.raises(PictureError):
        vf1_jpeg.decode(data[:30])                                   # cut inside the headers
    sof = data.find(b"\xFF\xC0")
    with pytest.raises(PictureError):                                 # lossless (SOF3)
        vf1_jpeg.decode(data[:sof + 1] + b"\xC3" + data[sof + 2:])
    with pytest.raises(PictureError):                                 # 12-bit samples
        vf1_jpeg.decode(data[:sof + 4] + b"\x0C" + data[sof + 5:])
    dht = data.find(b"\xFF\xC4")
    with pytest.raises(PictureError):                                 # no Huffman tables
        vf1_jpeg.decode(data[:dht] + _skip_all(data[dht:], 0xC4))


def _skip_all(data: bytes, marker: int) -> bytes:
    """data with every marker segment of one kind removed (up to the first scan)."""
    out = bytearray()
    i = 0
    while i < len(data):
        if data[i] == 0xFF and data[i + 1] == marker:
            i += 2 + ((data[i + 2] << 8) | data[i + 3])
            continue
        if data[i] == 0xFF and data[i + 1] == 0xDA:
            out += data[i:]
            break
        length = (data[i + 2] << 8) | data[i + 3]
        out += data[i:i + 2 + length]
        i += 2 + length
    return bytes(out)
