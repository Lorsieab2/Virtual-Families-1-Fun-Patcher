"""The Game Text tool (patcher/vf1_game_text.py): character search, export and the window."""
import tkinter as tk

import pytest

import vf1_game_fonts as gf
import vf1_game_text as tool
import vf1_picture_image as pi


@pytest.mark.parametrize("text,cp", [("U+00E9", 0xE9), ("u+1f600", 0x1F600), ("0x41", 0x41), ("e9", 0xE9),
                                     ("&#x263A;", 0x263A), ("U+D800", None), ("U+110000", None), ("hello", None)])
def test_code_points(text, cp):
    assert tool.parse_code_point(text) == cp


def test_search_by_name_and_code():
    found = tool.search("e acute")
    assert 0xE9 in found and 0xC9 in found
    assert tool.search("U+011F")[0] == 0x11F
    assert 0x304B in tool.search("hiragana ka")
    assert 0x1202D in tool.search("cuneiform sign an")
    assert tool.search("") == []
    assert tool.search("ñ")[0] == 0xF1


@pytest.fixture(scope="module")
def fonts(vanilla_dir):
    return gf.Fonts(vanilla_dir)


def test_every_character_says_where_its_letter_comes_from(fonts):
    f = fonts.font("SegoeUiBold18")
    assert tool.describe(f, ord("A")).endswith("(game)")
    assert tool.describe(f, 0x011F).endswith("(patcher-made)")         # ğ
    assert "(drawn by Windows: " in tool.describe(f, 0x65E5) or tool.describe(f, 0x65E5).endswith("(missing)")


def test_export_sizes(fonts, tmp_path):
    f = fonts.font("SegoeUi33")
    picture = f.render("Zoë", 0xFF102030)
    for size, scale in (("1x", 1), ("2x", 2), ("4x", 4)):
        path = tool.save_text_png(picture, tmp_path / f"{size}.png", **tool.export_options(size))
        out = pi.decode_png(path.read_bytes())
        assert (out.width, out.height) == (picture.width * scale, picture.height * scale)
    path = tool.save_text_png(picture, tmp_path / "custom.png", **tool.export_options("custom", "300", ""))
    assert pi.decode_png(path.read_bytes()).width == 300
    path = tool.save_text_png(picture, tmp_path / "trim.png", **tool.export_options("1x", trim=True))
    trimmed = pi.decode_png(path.read_bytes())
    assert trimmed.width < picture.width or trimmed.height < picture.height
    with pytest.raises(pi.PictureError):
        tool.export_options("custom", "abc")


def test_the_stock_view_draws_the_bytes(fonts):
    f = fonts.font("SegoeUiBold18")
    stock = tool.stock_picture(f, "Zoë", 0xFFFFFFFF)
    assert stock.width == sum(f.box(b)[2] - f.box(b)[0] for b in "Zoë".encode())


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no Tk display: {exc}")
    root.withdraw()
    yield root
    root.destroy()


def test_the_window(tk_root, vanilla_dir, tmp_path):
    window = tool.open_window(tk_root, game_folders=[vanilla_dir])
    try:
        window.quiet = True
        labels = list(window.font_box.cget("values"))
        assert len(labels) == 4 + len(gf.UNUSED_FONTS)
        assert all("unused in the game" in label for label in labels[4:])
        window.text.delete("1.0", "end")
        window.text.insert("1.0", "François İlkay\n¡Hola!")
        window.refresh()
        assert "characters" in window.info_var.get() and "patcher-made" in window.info_var.get()
        window.search_var.set("o diaeresis")
        window.do_search()
        assert window.results and window.results[0] in (0xF6, 0xD6)
        window.result_list.selection_set(0)
        window.insert_selected()
        assert window.text_value().count(chr(window.results[0])) >= 1
        window.size_var.set("2x")
        saved = window.save_png(str(tmp_path / "text.png"))
        out = pi.decode_png(saved.read_bytes())
        assert out.width == 2 * window.picture().width
        window.stock_var.set(True)
        window.refresh()
        assert window.picture().width != 0
        window.font_var.set(labels[-1])
        window.refresh()
        assert window.current_font().name == gf.UNUSED_FONTS[-1]
    finally:
        window.close()
