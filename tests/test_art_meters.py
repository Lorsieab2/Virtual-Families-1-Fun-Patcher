"""The Picture Maker's meters and bars (patcher/vf1_art_meters.py).

Without the game: a synthetic game folder (small stand-in pictures of the right sizes) checks that every bar
is listed, every key is unique, every layer's picture exists, the levels and thresholds are there, the
unused pictures are labelled, and every bar renders to the size its draws cover.

With VF1_VANILLA_DIR (a copy of the vanilla game; only read): tests/meters_emu.py runs the game's own code in
Unicorn and every Art's layers must equal the game's recorded draws and fills, in order:
the bar painter 0x44EEA0 for every kind and level (and every percent 0..100 against the module's model),
the Details screen 0x44B890 (the five bars from a family member's numbers, after its background), the
loading screen 0x4406D0 (between loading.jpg and the logo), one achievement row 0x412D00 (after the row's
own box), and the bank chart 0x415300.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest
import vf1_art_meters as am
import vf1_game_art as ga
import vf1_picture_image as pi

SIZES = {
    "VD_progressbar-blue.jpg": (290, 30), "VD_progressbar-red.jpg": (290, 30), "VD_fade-01.png": (20, 35),
    "VD_fade-02.png": (19, 33), "VD_line-blue.jpg": (3, 30), "VD_line-red.jpg": (3, 30),
    "VD_BG_2.jpg": (800, 600), "LoadSceneBarBG.png": (292, 32), "achievement_progress_box.png": (178, 29),
    "StatusBarSliceB.png": (2, 14), "StatusBarSliceR.png": (16, 16), "LoadColor.png": (8, 30),
}


# ------------------------------------------------------------------ without the game
@pytest.fixture(scope="module")
def fake_game(tmp_path_factory) -> Path:
    """Stand-in pictures, all PNG (the game's .jpg names hold PNG data: the catalogue reads by content)."""
    folder = tmp_path_factory.mktemp("game") / "Virtual Families"
    (folder / "Images").mkdir(parents=True)
    for k, (name, (w, h)) in enumerate(SIZES.items()):
        img = pi.Image(w, h)
        img.data[:] = bytes((k * 20 % 256, 100, 200, 255)) * (w * h)
        (folder / "Images" / name).write_bytes(img.to_png())
    return folder


def test_every_bar_is_listed_once_with_its_levels(fake_game):
    files = ga.GameFiles(fake_game)
    arts = am.arts(files)
    keys = [a.key for a in arts]
    assert len(keys) == len(set(keys))
    for a in arts:
        assert a.key.startswith("meters/")
        assert a.category.split("/")[0] in ga.CATEGORY_ORDER
        assert a.why and a.label
        for layer in a.layers:
            if isinstance(layer, pi.Draw):
                assert files.has(layer.file), layer.file
    for name in ("progress", "happiness", "health", "fed", "energy"):
        for p in (0, 10, 25, 50, 75, 90, 100, 7, 94):
            assert f"meters/details/{name}/{p}" in keys
    for p in (0, 10, 25, 50, 75, 90, 100, 7, 94):
        assert f"meters/loading/{p}" in keys
    for p in (0, 10, 25, 50, 75, 90, 100):
        assert f"meters/achievement/{p}" in keys
    unused = {a.key for a in arts if not a.used}
    assert unused == {"meters/achievement/100", "meters/unused/status-slice-blue",
                      "meters/unused/status-slice-red", "meters/unused/load-colour"}
    for image, (used, why) in am.USAGE.items():
        assert why and image in ga.TABLE
    assert {i for i, (u, _w) in am.USAGE.items() if not u} == {0x38, 0x39, 0x3A}
    for (image, cell) in am.CELL_LABELS:
        assert ga.grid_shape(image) == (1, 1) and cell == 0


def test_bars_render_to_what_their_draws_cover(fake_game):
    files = ga.GameFiles(fake_game)
    for a in am.arts(files):
        a = ga.resolve(files, a)
        img = ga.render(files, a)
        boxes = []
        for layer in a.layers:
            if isinstance(layer, ga.Fill):
                boxes.append((layer.x, layer.y, layer.x + layer.w, layer.y + layer.h))
            else:
                l, t, r, b = layer.rect
                boxes.append((layer.x, layer.y, layer.x + r - l, layer.y + b - t))
        boxes = [b for b in boxes if b[2] > b[0] and b[3] > b[1]]
        assert (img.width, img.height) == (max(b[2] for b in boxes) - min(b[0] for b in boxes),
                                           max(b[3] for b in boxes) - min(b[1] for b in boxes)), a.key


def test_the_painter_model_by_hand():
    # 50 percent of the Happiness bar: 145 wide, the edge line at 473 - 3 + 145, no end shading
    draws = am.painter_draws(10, 50)
    assert [(d.file, d.rect, d.x, d.y) for d in draws] == [
        ("VD_progressbar-blue.jpg", (0, 0, 145, 30), 473, 208), ("VD_fade-01.png", (0, 0, 20, 30), 473, 208),
        ("VD_line-blue.jpg", (0, 0, 3, 30), 615, 208)]
    # empty: only the edge line, cut to nothing
    assert [(d.file, d.rect, d.x) for d in am.painter_draws(10, 0)] == [("VD_line-blue.jpg", (3, 0, 3, 30), 473)]
    # the end shading from 94 percent; the career bar is red and counts 3000 points
    assert am.painter_draws(10, 94)[-1].rect == (0, 0, 1, 30)
    assert len(am.painter_draws(10, 93)) == 3
    assert {d.file for d in am.painter_draws(9, 3000)} == {"VD_progressbar-red.jpg", "VD_fade-01.png",
                                                            "VD_line-red.jpg", "VD_fade-02.png"}
    assert am.percent(9, 99999) == 100 and am.percent(9, 29) == 0 and am.percent(10, -5) == 0
    assert am.percent(10, 250) == 100


def test_the_achievement_and_chart_models_by_hand():
    assert am.achievement_layers(37)[1] == ga.Fill(500, 16, 64, 25, (216, 120, 10, 255))
    assert len(am.achievement_layers(0)) == 1
    fills = am.chart_layers([1000, 1010, 1020, 1030, 1040, 1050, 1060])
    assert fills[0] == ga.Fill(295, 200, 210, 140, am.WHITE)
    assert fills[1] == ga.Fill(265, 230, 31, 1, am.BLACK)          # the first bar's tick
    assert fills[2] == ga.Fill(295, 230, 30, 110, am.GREEN)
    assert len(fills) == 1 + 7 * 5 + 2 + 4


# ------------------------------------------------------------------ against the game
@pytest.fixture(scope="module")
def emu():
    value = os.environ.get("VF1_VANILLA_DIR")
    if not value or not (Path(value) / "Virtual Families.exe").is_file():
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    pytest.importorskip("unicorn")
    pytest.importorskip("capstone")
    pytest.importorskip("pefile")
    import meters_emu
    return meters_emu.MeterEmu(Path(value))


@pytest.fixture(scope="module")
def game_files():
    return ga.GameFiles(Path(os.environ["VF1_VANILLA_DIR"]))


def _as_layers(events) -> list:
    out = []
    for kind, e in events:
        if kind == "blit":
            assert e["alpha"] == 1.0 and e["scale"] == 1.0
            out.append((e["file"], tuple(e["rect"]), e["x"], e["y"]))
        else:
            l, t, r, b = e["rect"]
            rgba = tuple(int(c * 255.0) for c in e["rgba"])     # 0x403B40: each float * 255, rounded down
            out.append(ga.Fill(l, t, r - l, b - t, rgba))
    return out


def _module_layers(files, art) -> list:
    art = ga.resolve(files, art)
    return [layer if isinstance(layer, ga.Fill) else (layer.file, tuple(layer.rect), layer.x, layer.y)
            for layer in art.layers]


def test_the_painter_holds_the_pictures_the_module_names(emu):
    assert [emu.painter_field(o) for o in range(8, 0x28, 4)] == [
        "StatusBarSliceB.png", "StatusBarSliceR.png", am.BLUE, am.RED, am.START, am.END, am.LINE_BLUE,
        am.LINE_RED]


def test_the_painter_model_equals_the_game_at_every_percent(emu, game_files):
    for kind in am.KINDS:
        values = range(-5, 106) if kind != 9 else list(range(-30, 3100, 7)) + [2999, 3000, 3001]
        for value in values:
            game = _as_layers(emu.bar(kind, value))
            mine = [(d.file, d.rect, d.x, d.y) for d in am.painter_draws(kind, value)]
            assert game == mine, (kind, value)


def test_the_pieces_are_cut_as_a_full_bar_cuts_them(emu, game_files):
    full = {(file, rect) for file, rect, _x, _y in _as_layers(emu.bar(10, 100))}
    for a in am.arts(game_files):
        if a.key.startswith("meters/pieces/"):
            (layer,) = a.layers
            assert (layer.file, tuple(layer.rect)) in full, a.key


def test_details_bars_equal_the_details_screen(emu, game_files):
    by_key = {a.key: a for a in am.arts(game_files)}
    for kind in am.DETAILS_ORDER:
        name = am.KINDS[kind][0].lower()
        for p in am.LEVELS:
            events = emu.details(**am.details_value(kind, p))
            layers = _as_layers(events)
            # the screen: its background whole at (0, 0), then the five bars in DETAILS_ORDER
            assert layers[0] == ("VD_BG_2.jpg", (0, 0, 800, 600), 0, 0)
            bars, at = {}, 1
            for k in am.DETAILS_ORDER:
                value = am.painter_value(k, p) if k == kind else am.painter_value(
                    k, {9: 50, 10: 50, 11: 50, 12: 50, 8: 50}[k])
                n = len(am.painter_draws(k, value))
                bars[k] = layers[at:at + n]
                at += n
            assert at == len(layers)
            mine = _module_layers(game_files, by_key[f"meters/details/{name}/{p}"])
            file, rect, x, y = mine[0]           # the trough: a piece of the background, in its own place
            assert file == "VD_BG_2.jpg" and (x, y) == rect[:2]
            assert bars[kind] == mine[1:], (name, p)


def test_loading_bar_equals_the_loading_screen(emu, game_files):
    by_key = {a.key: a for a in am.arts(game_files)}
    for p in am.LEVELS:
        layers = _as_layers(emu.loading(p))
        assert layers[0] == ("loading.jpg", (0, 0, 800, 600), 0, 0)
        assert layers[-1][0] == "ldwLogo.png"
        assert layers[1:-1] == _module_layers(game_files, by_key[f"meters/loading/{p}"]), p
    # the counter past 100 draws the full bar
    assert _as_layers(emu.loading(137))[1:-1] == _module_layers(game_files, by_key["meters/loading/100"])


def test_achievement_bar_equals_the_awards_row(emu, game_files):
    by_key = {a.key: a for a in am.arts(game_files)}
    assert struct.unpack("<I", emu.u.mem_read(0x4E951C, 4))[0] == 100      # achievement 0's goal
    for p in am.ACH_LEVELS:
        layers = _as_layers(emu.achievement(0, p))
        assert layers[0] == ("achievement_box.png", (0, 0, 687, 57), 8, 0)
        assert layers[1:] == _module_layers(game_files, by_key[f"meters/achievement/{p}"]), p
    # a finished achievement: its box only, no bar
    assert _as_layers(emu.achievement(0, 100, done=True)) == [("achievement_complete_box.png", (0, 0, 687, 57), 8, 0)]
    # every count of a goal-of-15 achievement (43) against the model
    for count in range(0, 16):
        layers = _as_layers(emu.achievement(43, count))
        mine = am.achievement_layers(count * 100 // 15)
        assert layers[1:] == [(m.file, (0, 0, 178, 29), m.x, m.y) if isinstance(m, pi.Draw) else m
                              for m in mine], count


def test_bank_chart_equals_the_bank_window(emu, game_files):
    by_key = {a.key: a for a in am.arts(game_files)}
    for key, _words, values in am.CHART_STATES:
        game = _as_layers(emu.bank_chart(list(values), x=am.CHART_X, y=am.CHART_Y))
        assert game == _module_layers(game_files, by_key[f"meters/bank/{key}"]), key
    # other places and values against the model
    for values, x, y in (([1, 2, 3, 4, 5, 6, 7], 300, 100), ([9999.5] * 7, 512, 260),
                         ([10.0, 50.0, 90.0, 130.0, 170.0, 210.0, 250.0], 233, 77)):
        assert _as_layers(emu.bank_chart(values, x=x, y=y)) == am.chart_layers(values, x, y)
