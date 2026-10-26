"""The Family Tree Maker (patcher/vf1_genealogy.py, vf1_family_tree.py, vf1_family_tree_window.py,
vf1_member_info.py): the family read from a save alone (real-save fixtures and synthetic families) and the
Children sidecar; the tree drawn, exported and kept; the editor window."""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest

import make_vf1_save_fixtures as fx
import vf1_family_tree as ft
import vf1_genealogy as gen
import vf1_save as vs
from test_vf1_save import FIXTURES, build_save, family_record, peep, villager_record


def fixture_bytes(name: str) -> bytes:
    return fx.rebuild(json.loads((FIXTURES / f"{name}.json").read_text("utf-8")))


def family(data: bytes, **kw) -> gen.Village:
    village = gen.build_family(vs.parse_save(data), 1, data=data, **kw)
    gen.finish(village)
    return village


def by_name(village: gen.Village, name: str) -> gen.Person:
    hits = [p for p in village.people.values() if p.name == name]
    assert len(hits) == 1, (name, hits)
    return hits[0]


def snapshot(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in folder.rglob("*") if p.is_file()}


# ---------------------------------------------------------------- real saves (fixtures from copies)
def test_real_six_generations():
    v = family(fixture_bytes("generation6_left_home"))
    assert v.tribe and v.generations == 6
    rows = {}
    for p in v.known():
        rows.setdefault(p.generation, []).append(p.name)
    assert sorted(rows) == [1, 2, 3, 4, 5, 6, 7]
    assert len(rows[1]) == 2 and all(len(rows[g]) == 7 for g in range(2, 7)) and len(rows[7]) == 6
    founder = next(p for p in v.people.values() if p.how == "Founder")
    assert founder.generation == 1 and ft.is_founder(v, founder)
    vesta, bengor = by_name(v, "Vesta"), by_name(v, "Bengor")
    assert vesta.heir and vesta.alive and vesta.years == 41 and vesta.generation == 6
    assert bengor.how == "Married in" and bengor.alive and not bengor.heir
    assert vesta.father is not None and vesta.mother is not None
    kids = {k.name for k in v.children_of(vesta.id)}
    assert kids == {"Input", "Dico", "Pennella", "Tilde", "Fabiana", "Francone"}
    assert {k.name for k in v.children_of(bengor.id)} == kids
    # Input and Dico left home (19 and 20, the save's left-home flag): alive, and said so.
    assert by_name(v, "Input").left_home and by_name(v, "Input").alive and by_name(v, "Dico").left_home
    # Every parent before the current couple died (the tree's slot is -1).
    for p in v.people.values():
        if p.generation < 6 and (p.heir or p.how in ("Founder", "Married in")):
            assert p.gone == "died" and not p.alive
    # The heir's brothers and sisters of older generations: not in the house, and what became of them unknown.
    older = [p for p in v.people.values() if p.generation in (2, 3) and not p.heir and p.how != "Married in"]
    assert older and all(p.gone == "left" and not p.alive for p in older)
    assert all(any("does not say whether they died" in u for u in p.unknowns) for p in older)
    assert any("keeps no history" in n for n in v.notes)


def test_real_pregnancy_shows_the_baby_on_the_way():
    v = family(fixture_bytes("pregnant_unborn_baby"))
    baby = next(p for p in v.people.values() if p.upcoming)
    mother = by_name(v, "Rosella")
    assert baby.name == "Bohi" and baby.mother == mother.id and mother.expecting and mother.alive
    assert baby.number is None and baby not in v.known()


@pytest.mark.parametrize("name", ["generation6_left_home", "pregnant_unborn_baby", "legacy_header_v3f0",
                                  "parents_died_old_age"])
def test_every_real_fixture_draws(name):
    v = family(fixture_bytes(name))
    edits = ft.Edits()
    ft.arrange(v, edits)
    lay = ft.layout(v, edits)
    sc = ft.scene(lay, gen.GAME_TITLE, {})
    svg = ft.to_svg(sc, {})
    assert svg.startswith("<svg") and lay.pages >= 1
    for p in v.known():
        if p.id in lay.x:
            assert p.name.replace("&", "&amp;").strip() in svg


# ---------------------------------------------------------------- synthetic families
def two_generations(extra_villagers: dict | None = None, **gs) -> bytes:
    """Ann (founder) and Bob; their children Cal (the heir), Dee and the twins Eve and Fay; Cal married Gia and
    they have Hal; Ivy was adopted."""
    villagers = {
        0: villager_record(name="Cal", sex=0, age=600, head=4, body=5),
        1: villager_record(name="Gia", sex=1, age=580, head=6, body=7),
        2: villager_record(name="Hal", sex=0, age=100, head=8, body=9, p1="Joey", p2="Gia"),
        3: villager_record(name="Ivy", sex=1, age=120, head=10, body=11),          # no parents in the bio: adopted
        4: villager_record(name="Ann", sex=1, age=1300, head=1, body=2, health=0, cause=2),   # her body, not removed
    }
    villagers.update(extra_villagers or {})
    gen1 = family_record(peep("Ann", sex=1, head=1, body=2, slot=4, index=-1), peep("Bob", sex=0, head=3, body=3),
                         [peep("Cal", head=4, body=5, slot=9), peep("Dee", sex=1, head=12, body=1, slot=8),
                          peep("Eve", sex=1, head=13, body=2, slot=7), peep("Fay", sex=1, head=14, body=3, slot=6)])
    gen2 = family_record(peep("Cal", head=4, body=5, slot=0, index=0, likes="Cooking, Music"),
                         peep("Gia", sex=1, head=6, body=7, slot=1),
                         [peep("Hal", head=8, body=9, slot=2), peep("Ivy", sex=1, head=10, body=11, slot=3)])
    return build_save(villagers, [gen1, gen2], family="Testfamily", **gs)


def test_synthetic_family_from_the_save_alone():
    v = family(two_generations())
    ann, bob, cal, gia = (by_name(v, n) for n in ("Ann", "Bob", "Cal", "Gia"))
    assert ann.how == "Founder" and bob.how == "Married in" and bob.gone == "died"
    assert ann.gone == "died" and "the wording is unconfirmed" in ann.cause     # the save's number only
    assert cal.heir and cal.father == bob.id and cal.mother == ann.id and cal.generation == 2
    assert cal.likes == ["Cooking", "Music"]
    assert gia.generation == 2 and gia.arrived
    hal, ivy = by_name(v, "Hal"), by_name(v, "Ivy")
    assert (hal.father, hal.mother) == (cal.id, gia.id) and not hal.adopted and hal.generation == 3
    assert ivy.adopted and ivy.how == "Adopted" and (ivy.father, ivy.mother) == (cal.id, gia.id)
    for name in ("Dee", "Eve", "Fay"):
        assert by_name(v, name).gone == "left" and by_name(v, name).unknowns
    assert by_name(v, "Eve").litter is None                     # no Family History log: twins are not known
    text = gen.report(v)
    assert "Family: Testfamily (Save 1)" in text and "unknown: Not in the house now" in text


def test_someone_in_the_house_the_tree_does_not_hold_is_shown_apart():
    v = family(two_generations({5: villager_record(name="Zed", sex=0, age=200, head=20, body=20)}))
    zed = by_name(v, "Zed")
    assert zed.alive and zed.father is None and zed.mother is None and "does not record them" in zed.unknowns[0]


def test_no_other_log_or_data_file_is_read(tmp_path):
    """Only the save, the Children sidecar of that very save and the Family History log are read: the old Family
    Logs' other files (which no patcher writes any more) are ignored."""
    (tmp_path / "Virtual Families1.ldw").write_bytes(two_generations())
    root = gen.slot_root(tmp_path, 1)
    for rel, text in (("Data/Parents/Virtual Families 1 Parents - Save 1.dat",
                       "VF1LOGS PARENTS 1\nchild\t2\tHal\t0\t2\tMia\tCal\tconceived\n"),
                      ("Logs/Deaths/Virtual Families 1 Deaths Log 1.txt",
                       "Death 1\n  Name: Dee\n  Cause of death: Disease\n  Head: 12\n  Body: 1\n")):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="cp1252")
    before = snapshot(tmp_path)
    v = gen.load_village(tmp_path, gen.GAME, 1)
    assert snapshot(tmp_path) == before                 # read only
    assert "Mia" not in {p.name for p in v.people.values()}
    assert by_name(v, "Dee").cause == "" and by_name(v, "Dee").gone == "left"
    assert any("keeps no history" in n for n in v.notes)
    source = Path(gen.__file__).read_text(encoding="utf-8")
    assert "read_family_logs" not in source and "VF1LOGS" not in source


def test_children_seven_to_twenty_eight_from_the_sidecar(tmp_path):
    kids = [peep(f"K{i}", head=i, body=i, slot=10 + i) for i in range(6)]
    villagers = {0: villager_record(name="Ma", sex=1, age=700, head=1), 1: villager_record(name="Pa", age=700, head=2)}
    villagers.update({10 + i: villager_record(name=f"K{i}", age=50, head=i, body=i) for i in range(6)})
    villagers[20] = villager_record(name="Seventh", sex=1, age=30, head=30, body=3)
    data = build_save(villagers, [family_record(peep("Ma", sex=1, head=1, slot=0, index=-1),
                                                peep("Pa", head=2, slot=1), kids)])
    extra = [gen.ExtraChild(20, 1, "alive", 30, 3, 30, "Seventh"), gen.ExtraChild(21, 0, "dead", 31, 4, 25, "Eighth")]
    side = gen.make_children_sidecar(data, 1, 0, 1, extra)
    assert gen.read_children_sidecar(side).children == extra
    (tmp_path / "Virtual Families1.ldw").write_bytes(data)
    path = gen.children_sidecar_path(tmp_path, 1)
    path.parent.mkdir(parents=True)
    path.write_bytes(side)
    v = gen.load_village(tmp_path, gen.GAME, 1)
    ma = by_name(v, "Ma")
    assert len(v.children_of(ma.id)) == 8
    assert by_name(v, "Seventh").alive and by_name(v, "Eighth").gone == "died"
    # A sidecar of another save file (an older save) is not used, and the tree says so.
    path.write_bytes(gen.make_children_sidecar(data + b"x", 1, 0, 1, extra))
    v = gen.load_village(tmp_path, gen.GAME, 1)
    assert len(v.children_of(by_name(v, "Ma").id)) == 6 and any("another save file" in n for n in v.notes)
    # A damaged sidecar is refused as vf1kids refuses it.
    assert gen.read_children_sidecar(side[:-1] + bytes([side[-1] ^ 1])) is None


def test_a_missing_or_foreign_save_is_a_clear_error(tmp_path):
    with pytest.raises(gen.GenealogyError, match="could not be read"):
        gen.load_village(tmp_path, gen.GAME, 3)
    (tmp_path / "Virtual Families3.ldw").write_bytes(b"not a save")
    with pytest.raises(gen.GenealogyError, match="not a Virtual Families save"):
        gen.load_village(tmp_path, gen.GAME, 3)


# ---------------------------------------------------------------- the picture
def png(width: int, height: int, pixel=lambda x, y: (0, 0, 0, 0)) -> bytes:
    raw = b"".join(b"\0" + b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def fake_images(folder: Path) -> Path:
    """Head sheets shaped like the game's: 12 x 50 cells of 56 pixels; each cell of column 5 a face 20 wide."""
    folder.mkdir(parents=True)

    def face(x, y):
        cx, row_y = x - ft.HEAD_FRAME * ft.HEAD_W, y % ft.HEAD_H
        return (200, 150, 100, 255) if 18 <= cx < 38 and 6 <= row_y < 36 else (0, 0, 0, 0)
    sheet = png(12 * ft.HEAD_W, 50 * ft.HEAD_H, face)
    for name in ft.SHEETS[gen.GAME]:
        (folder / name).write_bytes(sheet)
    return folder


def test_head_sheets_are_the_games_young_ones_in_column_five(tmp_path):
    images = fake_images(tmp_path / "Images")
    present = ft.sheets_present(gen.GAME, images)
    assert set(present) == {"male_heads00.png", "female_heads00.png"}
    boxes = ft.head_boxes(present["male_heads00.png"])
    assert len(boxes) == 50 and boxes[0] == (18, 6, 38, 36)
    v = family(two_generations())
    edits = ft.Edits()
    ft.arrange(v, edits)
    svg = ft.to_svg(ft.scene(ft.layout(v, edits), gen.GAME_TITLE, present, images), present)
    assert f'viewBox="{5 * 56} {4 * 56} 56 56"' in svg            # Cal: head 4, column 5


def test_vanilla_head_sheets_have_fifty_faces(vanilla_dir):
    present = ft.sheets_present(gen.GAME, vanilla_dir / "Images")
    assert set(present) == set(ft.SHEETS[gen.GAME])
    for path in present.values():
        assert ft._png_size(path) == (12 * ft.HEAD_W, 50 * ft.HEAD_H)
        boxes = ft.head_boxes(path)
        assert len(boxes) == 50 and all(box[3] <= ft.FACE_H + 13 for box in boxes.values())


def test_descriptors_and_statuses_in_family_words():
    v = family(two_generations())
    edits = ft.Edits()
    ft.arrange(v, edits)
    lay = ft.layout(v, edits)
    text = {p.name: ft.default_text(lay, p) for p in v.known()}
    assert "Founder" in text["Ann"] and "(deceased)" in text["Ann"]
    assert "Married in" in text["Bob"] and "Heir" in text["Cal"] and "Adopted" in text["Ivy"]
    assert "(no longer in the house)" in text["Dee"]
    assert not any("game units" in line for lines in text.values() for line in lines)
    assert "30 years old" in text["Cal"]
    edits.show_heir = False                       # the Heir option
    ft.arrange(v, edits)
    assert "Heir" not in ft.default_text(ft.layout(v, edits), by_name(v, "Cal"))
    assert ft.status_label(by_name(v, "Dee")) == "(no longer in the house)"


def test_text_box_group_settings_and_shapes_survive_a_save(tmp_path):
    edits = ft.Edits(title="Our family")
    edits.text_box_opacity, edits.text_box_colour, edits.text_box_border_width = 60.0, "#ffeecc", 2.0
    edits.shapes["Female"] = "heart" if "heart" in ft.PORTRAIT_SHAPES else next(iter(ft.PORTRAIT_SHAPES))
    edits.group_opts["Male"] = {"show_years": False}
    path = ft.Edits.path(tmp_path, gen.GAME, 2)
    assert path == tmp_path / "Virtual Families 1 Patcher" / "Save 2" / "Data" / "Family Tree" / \
        "Virtual Families 1 Family Tree Edits - Save 2.json"
    edits.save(path)
    back = ft.Edits.load(path)
    assert (back.title, back.text_box_opacity, back.text_box_colour, back.text_box_border_width) == (
        "Our family", 60.0, "#ffeecc", 2.0)
    assert back.shapes["Female"] == edits.shapes["Female"] and back.group_opts["Male"] == {"show_years": False}
    v = family(two_generations())
    ft.arrange(v, back)
    cal = by_name(v, "Cal")
    assert not any("years old" in line for line in ft.default_text(ft.layout(v, back), cal))


def test_write_puts_the_page_report_and_picture_beside_the_save(tmp_path):
    (tmp_path / "Virtual Families1.ldw").write_bytes(two_generations())
    images = fake_images(tmp_path / "game" / "Images")
    before = (tmp_path / "Virtual Families1.ldw").read_bytes()
    written = ft.write(tmp_path, gen.GAME, 1, images)
    out = tmp_path / "Virtual Families 1 Patcher" / "Save 1" / "Family Tree"
    assert written.report.parent == out and written.page.parent == out
    assert "Testfamily" in written.report.read_text("utf-8")
    assert "<svg" in written.page.read_text("utf-8")
    import vf1_gdiplus
    if vf1_gdiplus.available():
        assert written.picture is not None and written.picture.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert (tmp_path / "Virtual Families1.ldw").read_bytes() == before


def test_export_jpg_and_png_at_a_scale(tmp_path):
    import vf1_gdiplus
    if not vf1_gdiplus.available():
        pytest.skip("GDI+ is Windows only")
    v = family(two_generations())
    edits = ft.Edits()
    ft.arrange(v, edits)
    sc = ft.scene(ft.layout(v, edits), gen.GAME_TITLE, {})
    assert vf1_gdiplus.save_scene(sc, {}, tmp_path / "t.png", scale=0.5)
    assert vf1_gdiplus.save_scene(sc, {}, tmp_path / "t.jpg")
    assert (tmp_path / "t.jpg").read_bytes()[:2] == b"\xff\xd8"
    w, h = ft._png_size(tmp_path / "t.png")
    assert abs(w - sc.width * 0.5) <= 2 and abs(h - sc.height * 0.5) <= 2


# ---------------------------------------------------------------- the editor window
@pytest.fixture(scope="module")
def tk_root():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no Tk display: {exc}")
    root.withdraw()
    yield root
    root.destroy()


class FakeApp:
    def __init__(self, root):
        self.root = root
        self.tree_style = None
        self.tree_window = {}
        self.saved = 0

    def _run_with_wait(self, label, func):
        return func()

    def _save_settings(self):
        self.saved += 1


def test_editor_opens_selects_and_saves_a_tree_file(tk_root, tmp_path):
    import vf1_family_tree_window as w
    (tmp_path / "Virtual Families1.ldw").write_bytes(two_generations())
    images = fake_images(tmp_path / "game" / "Images")
    v = gen.load_village(tmp_path, gen.GAME, 1)
    ed = w.TreeEditor(FakeApp(tk_root), tmp_path, gen.GAME, 1, gen.GAME_TITLE, images, v, ft.Edits())
    try:
        ed.withdraw()
        tk_root.update()
        cal = by_name(ed.village, "Cal")
        ed._select([cal.id])
        ed._refresh_selected()
        info = ed.info_tab.text.get("1.0", "end")
        assert "Cal" in info and "Heir" in info and "Partners" in info
        assert [ed.village.people[q].name for q in w.find_villagers(ed.village, ed.edits, "adopted")] == ["Ivy"]
        assert ed._save_tree()
        tree = ft.data_folder(tmp_path, 1) / f"Virtual Families 1 Family Tree - Save 1{ft.TREE_SUFFIX}"
        data = json.loads(tree.read_text("utf-8"))
        assert data["format"] == ft.TREE_FORMAT and data["slot"] == 1 and data["family"] == "Testfamily"
        assert ft.Edits.path(tmp_path, gen.GAME, 1).is_file()
        assert sorted(p.name for p in tmp_path.iterdir()) == ["Virtual Families 1 Patcher", "Virtual Families1.ldw",
                                                              "game"]
    finally:
        ed.destroy()


def test_the_picker_lists_each_slot_and_opens_the_family(tk_root, tmp_path, monkeypatch):
    import vf1_family_tree_window as w
    (tmp_path / "Virtual Families1.ldw").write_bytes(two_generations())
    (tmp_path / "Virtual Families3.ldw").write_bytes(b"broken")
    opened = []
    monkeypatch.setattr(w, "_open_editor", lambda app, dialog, folder, game, info, title, images:
                        opened.append((folder, game, info.slot, title, images)))
    dialog = w.open_family_tree(FakeApp(tk_root), folders=[tmp_path])
    try:
        rows = dialog._vf1_slots.get(0, "end")
        assert rows[0].startswith("Save 1: Testfamily (2 generations)") and rows[1] == "Save 2: (empty)"
        assert rows[2].startswith("Save 3: cannot be read")
        dialog._vf1_start()
        assert opened == [(tmp_path, gen.GAME, 1, gen.GAME_TITLE, None)]
    finally:
        dialog.destroy()


def test_side_panel_tabs_scroll_when_taller_than_the_window(tk_root, tmp_path):
    import vf1_family_tree_window as w
    from vf1_tree_editor_tools import ScrollingTab
    (tmp_path / "Virtual Families1.ldw").write_bytes(two_generations())
    v = gen.load_village(tmp_path, gen.GAME, 1)
    ed = w.TreeEditor(FakeApp(tk_root), tmp_path, gen.GAME, 1, gen.GAME_TITLE, None, v, ft.Edits())
    try:
        ed.withdraw()
        tk_root.update()
        tabs = [ed.notebook.tab(t, "text") for t in ed.notebook.tabs()]
        assert "Family Member Info" in tabs and "Marks" in tabs
        assert ScrollingTab
        for page in ed.notebook.tabs():
            outer = ed.nametowidget(page)
            # every page has its own vertical scroll bar (a ScrollingTab, or the info tab's text)
            assert any(c.winfo_class() == "TScrollbar" for c in outer.winfo_children()), \
                ed.notebook.tab(page, "text")
    finally:
        ed.destroy()


def test_tools_tab_has_the_family_tree_maker(tk_root, tmp_path, monkeypatch):
    import tkinter as tk
    import vf1_patcher_gui as gui
    monkeypatch.setattr(gui, "local_settings_path", lambda base_dir=None: tmp_path / "local.json")
    monkeypatch.setattr(gui, "guess_game_dir", lambda: "")
    top = tk.Toplevel(tk_root)
    top.withdraw()
    app = gui.VF1PatcherGUI(top)
    try:
        texts = []

        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)
        texts = [w.cget("text") for w in walk(top) if w.winfo_class() in ("TLabel", "TLabelframe")]
        assert "Family Tree Maker" in texts and "family_tree" in app.help_keys
        app.tree_style, app.tree_window = {"font": "Arial"}, {"zoom": 2}
        app._save_settings()
        assert gui.load_tree_settings() == {"style": {"font": "Arial"}, "window": {"zoom": 2}}
        gui.save_saved_paths(vanilla_game_dir=str(tmp_path))     # saving the paths keeps the tree's look
        assert gui.load_tree_settings()["style"] == {"font": "Arial"}
    finally:
        for pending in tk_root.tk.splitlist(tk_root.tk.call("after", "info")):
            tk_root.tk.call("after", "cancel", pending)
        top.destroy()


def test_runner_from_the_family_trees_likes_and_twins_on_the_way():
    villagers = {0: villager_record(name="Ma", sex=1, age=600, head=1, preg=590, babies=2),
                 1: villager_record(name="Pa", age=620, head=2),
                 2: villager_record(name="B1", present=0, age=0, head=3), 3: villager_record(name="B2", present=0, head=4)}
    data = build_save(villagers, [family_record(peep("Ma", sex=1, head=1, slot=0, index=-1, likes=" running, art"),
                                                peep("Pa", head=2, slot=1, likes=" exercising", dislikes=" running"),
                                                [peep("B1", head=3, slot=2), peep("B2", head=4, slot=3)])],
                      pending=(2, 3, -1))
    v = family(data)
    ma, pa = by_name(v, "Ma"), by_name(v, "Pa")
    assert ma.runner and ma.likes == ["running", "art"] and not pa.runner      # a dislike is no runner
    babies = [p for p in v.people.values() if p.upcoming]
    assert len(babies) == 2 and babies[0].litter == babies[1].litter is not None
    edits = ft.Edits()
    ft.arrange(v, edits)
    lay = ft.layout(v, edits)
    assert "Runner" in ft.default_text(lay, ma) and "Runner" not in ft.default_text(lay, pa)
    assert ft.default_text(lay, babies[0]) == ["Upcoming child", "(twins)"]
    edits.show_runner = False
    assert "Runner" not in ft.default_text(ft.layout(v, edits), ma)


def test_career_adopted_and_deceased_labels_and_their_options():
    """The new portrait labels: the career in the executable's own words (career 0x112 + id, level 0x1C1 + level),
    Adopted for every way in that is not a birth, Deceased; each one its own tick box, ticked by default."""
    p = gen.Person(0, "Ann", 1, 1, sex="Female", alive=True)
    p.career, p.career_level = 0, 1
    assert ft.career_words(p) == "Career: Pastry Designer, Novice"
    p.career_level = None                            # a Family Tree entry only: no level known
    assert ft.career_words(p) == "Career: Pastry Designer"
    p.career = None
    assert ft.career_words(p) == ""
    for how in ("Adopted", "Spawn Child", "Adopt New Person"):
        assert ft.is_adopted(gen.Person(1, "Kid", 1, 1, how=how))
    assert not ft.is_adopted(gen.Person(1, "Kid", 1, 1, how="Married in"))
    keys = [k for k, _words in ft.DESCRIPTOR_OPTIONS]
    for key in ("show_divorced", "show_deceased", "show_career", "show_adopted", "show_remarried", "show_spouse_order",
                "show_arrived"):
        assert key in keys and getattr(ft.Edits(), key) is True
    e = ft.Edits()
    e.show_career = False
    back = ft.Edits.from_data(e.to_data())
    assert back.show_career is False and back.show_divorced is True
