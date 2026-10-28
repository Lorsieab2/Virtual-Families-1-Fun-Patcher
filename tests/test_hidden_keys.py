"""Game Mechanics, "Hidden keys, clicks and cheats": the page's lines, and the stock exe's key codes, key handlers,
click spots and tip rolls they come from (pinned against the vanilla exe; those tests skip without VF1_VANILLA_DIR).

How the engine reads keys (ldwGame::Run 0x402CC0 -> 0x40A0D0 -> 0x4092D0 -> the SDL pump 0x4047B0, every frame):
a typed character is posted as (5, 0, character) (SDL_TEXTINPUT, 0x4049C4), so the store's 0x72 is a small r
typed; Esc, Enter, F1 and the other named keys are posted as (6, id, key) through the tables at 0x404ADC / 0x404B54.
A scene gets them while it is active (ldwScene::SetActive 0x40C700 registers it), through its vtable slot 2.
"""
import re
import struct
from pathlib import Path

import pytest

import vf1_game_mechanics as gm

FACTS = [f for f in gm.facts() if f.group == gm.KEYS]
PAGE = gm.render()


def find(pattern):
    hits = [f for f in FACTS if re.search(pattern, f.text)]
    assert len(hits) == 1, pattern
    return hits[0]


# ------------------------------------------------------------------ the page


def test_the_group_comes_first_and_is_named_as_the_owner_asked():
    assert gm.GROUPS[0] == gm.KEYS == "Hidden keys, clicks and cheats"
    assert gm.facts()[0].group == gm.KEYS
    assert PAGE.index("\n\nHidden keys, clicks and cheats\n") < PAGE.index("\n\nTime and ageing\n")


def test_the_store_key_is_a_small_r_once_an_hour_of_real_time_emulated():
    line = find(r"^The store's hidden key: typing a small r while the store page is open")
    assert line.label == gm.VERIFIED_E and not line.sub
    for words in ("a capital R does nothing", "redraws all six Flea Market items at once, for free",
                  "new Male Outfit and Female Outfit pictures", "more than 1 hour of real time",
                  "exactly 1 hour after a draw nothing happens; 1 hour and 1 second after, they are redrawn",
                  "4 hours of real time after the key", "at any game speed, also while paused"):
        assert words in line.text, words
    assert find(r"^What the redraw does not change: the half-price grocery").label == gm.VERIFIED_E
    fix = find(r"^With the patcher \(Fix Vanilla Game Bugs, on by default\): the R key's redraw")
    assert fix.label == gm.VERIFIED_C and fix.sub


def test_esc_adopts_and_marries():
    assert find(r"^Esc on the Adoption screen is the Adopt button").label == gm.VERIFIED_C
    assert find(r"^Esc on the marriage proposal screen .* is the Marry button").label == gm.VERIFIED_C


def test_house_keys_and_the_tv_remote():
    find(r"S the Store, D the Details screen .* F the Family screen, C the Collections screen, T the Trophies screen; "
         r"Esc goes to the main menu")
    find(r"^In the house, the number keys 1 to 9")
    find(r"^In the house, K \(either case\) or a capital R loses the TV remote at once")
    remote = find(r"^The TV remote: a new family's remote starts lost")
    assert "23 to 28 hours of real time" in remote.text and "20.001% each" in remote.text
    assert "19.998% for the 27th and 28th" in remote.text and "every 2 seconds of real time" in remote.text
    find(r"^While the remote is lost, TV Night never happens")
    find(r"^The shed door: a new family's shed door needs fixing")


def test_dead_code_is_marked_and_never_offered_as_something_to_do():
    dead = [f for f in FACTS if f.text.startswith("DEAD (never runs)")]
    assert len(dead) == 2
    for fact in dead:
        assert fact.label == gm.VERIFIED_C
    tools = find(r"^DEAD \(never runs\): three developer tools")
    assert "None can be reached in the shipped game" in tools.text
    assert "DEAD (never runs)" in gm.LABEL_NOTE
    # nowhere else on the page is a developer tool described
    assert sum("Light Source Editor" in f.text for f in gm.facts()) == 1


def test_no_cheat_codes_and_the_only_switches():
    assert find(r"^Cheat codes: there are none").label == gm.VERIFIED_C
    ini = find(r"^Settings in ldw\.ini")
    for key in ("FullScreen", "ForceFullScreen", "ForceWindowed", "ForceStaticSplash", "Distributor",
                "reads no registry value and ignores its command line"):
        assert key in ini.text, key


def rolls(k, n):
    return 32768 // n + (1 if k < 32768 % n else 0)


def test_random_tips_their_odds_and_every_text():
    assert len(gm.RANDOM_TIPS) == 50 and len(set(gm.RANDOM_TIPS)) == 50
    spot = find(r"^Random tips, click spot")
    assert (rolls(0, 50), rolls(17, 50), rolls(18, 50)) == (656, 656, 655)
    assert "tips 1 to 18: 2.002% each; tips 19 to 50: 1.999% each" in spot.text
    assert "across from 171 to 221 and down from 562 to 584" in spot.text and "no wait and no limit" in spot.text
    load = find(r"^Random tips, loading screen")
    assert (rolls(7, 30), rolls(8, 30)) == (1093, 1092)
    assert "tips 1 to 8: 3.336% each; tips 9 to 30: 3.333% each" in load.text
    for n, tip in enumerate(gm.RANDOM_TIPS, 1):
        assert f"{n}. “{tip}”" in PAGE, n


def test_every_click_spot_line():
    for pattern in (r"^the refrigerator: shows “Food available:", r"^the kitchen trash can",
                    r"^the TV wall in the living room", r"^the bathroom's two sinks", r"^the office desk:",
                    r"^the office computer", r"^the hall cabinet", r"^sounds only:"):
        assert find(pattern).sub, pattern


# ------------------------------------------------------------------ the vanilla exe

BASE = 0x400000


@pytest.fixture(scope="module")
def exe(vanilla_dir):
    return (vanilla_dir / "Virtual Families.exe").read_bytes()


def at(exe, va, n):
    return exe[va - BASE:va - BASE + n]


def u32(exe, va):
    return struct.unpack_from("<I", exe, va - BASE)[0]


def call_target(exe, va):
    assert exe[va - BASE] == 0xE8, hex(va)
    return va + 5 + struct.unpack_from("<i", exe, va - BASE + 1)[0]


def test_a_typed_character_is_posted_as_itself(exe):
    # SDL_TEXTINPUT of one byte: movsx eax, byte [esp+0x30] ; push eax ; push ebx(0) ; push 5 -> Post(5, 0, ch)
    assert at(exe, 0x4049C4, 9) == bytes.fromhex("0fbe44243050536a05")
    # Backspace is posted as character 8; Alt+F4 tests KMOD_ALT (0x300)
    assert at(exe, 0x40494A, 5) == bytes.fromhex("6a08516a05")
    assert at(exe, 0x4048A8, 8) == bytes.fromhex("f744243c00030000")


def test_the_named_keys_ids(exe):
    # SDL keycodes 8..0x7F through the byte table 0x404ADC and the jump table 0x404AC4; the target loads the id
    def key_id(target):
        code = at(exe, target, 5)
        return struct.unpack_from("<I", code, 1)[0] if code[0] == 0xB8 else None
    small = {}
    for sym in range(8, 0x80):
        case = exe[0x404ADC - BASE + sym - 8]
        target = u32(exe, 0x404AC4 + 4 * case)
        small[sym] = target
    assert key_id(small[0x1B]) == 1000 and key_id(small[0x0D]) == 1003 and key_id(small[0x09]) == 1002
    assert key_id(small[0x7F]) == 1013
    assert small[ord("r")] == small[ord("a")] == 0x404A87               # letters are not keys: they come as text
    f1 = 0x40487D
    assert key_id(f1) == 1018
    f_keys = [key_id(u32(exe, 0x404B54 + 4 * k)) for k in range(9)]      # F2 .. F10
    assert f_keys[0:2] == [1019, 1020] and f_keys[3:] == [1022, 1023, 1024, 1025, 1026, 1027]
    assert u32(exe, 0x404B54 + 4 * 2) == 0x4048A8                         # F4: Alt+F4 quits, else 1021


def test_the_store_key_handler(exe):
    assert u32(exe, 0x4B7220 + 8) == 0x4499D0                            # theStoreScene vtable slot 2
    code = at(exe, 0x4499D0, 0x30)
    assert code[4:7] == bytes.fromhex("83f805")                            # a typed character (5)
    assert at(exe, 0x4499E0, 3) == bytes.fromhex("83f84d")                 # 'M'
    assert at(exe, 0x4499E5, 3) == bytes.fromhex("83f86d")                 # 'm'
    assert at(exe, 0x4499EA, 3) == bytes.fromhex("83f872")                 # 'r' (0x72), small only
    assert call_target(exe, 0x4499F4) == 0x496DB0                         # the once-an-hour gate
    assert at(exe, 0x4499FD, 2) == bytes.fromhex("6aff") and call_target(exe, 0x449A01) == 0x449480   # all specials
    assert at(exe, 0x449A06, 2) == bytes.fromhex("6a01") and call_target(exe, 0x449A0D) == 0x496C70   # outfits
    assert call_target(exe, 0x449A14) == 0x449100                         # the price labels
    assert at(exe, 0x449A40, 8) == bytes.fromhex("817c240ce8030000")     # Esc
    # the gate: allowed unless the due time is 10,800 to 14,400 real seconds away (= at most 1 hour since the draw)
    assert at(exe, 0x496DC5, 6) == bytes.fromhex("8d90302a0000") and at(exe, 0x496DCF, 6) == bytes.fromhex(
        "8d9040380000")
    assert call_target(exe, 0x496DBA) == 0x4036D0                         # GetSecondsFromGameStart: real time
    # the store is one scene: its command handler (slot 3) knows only button 1 (back to the house), no tabs; the
    # buy dialog's and the message box's key handler is the shared Enter / Esc one
    assert u32(exe, 0x4B7220 + 12) == 0x448F20 and at(exe, 0x448F2A, 5) == bytes.fromhex("837c240c01")
    assert u32(exe, 0x4B5C14 + 8) == u32(exe, 0x4B5B58 + 8) == 0x41CE50


def test_the_house_keys(exe):
    assert u32(exe, 0x4B6FFC + 8) == 0x440E00                            # theMainScene vtable slot 2
    table = at(exe, 0x440D78, 0x58)
    cases = {chr(0x20 + i): u32(exe, 0x440D28 + 4 * c) for i, c in enumerate(table)}
    default = cases["a"]
    assert default == 0x440D18
    used = {ch: t for ch, t in cases.items() if t != default}
    assert sorted(used) == sorted(" '123456789;CDFKMPRSTW[]cdfkmpstw")
    assert "r" not in used and used["R"] == used["K"] == used["k"] == 0x440C91
    assert call_target(exe, 0x440C94) == 0x423AE0                         # K / R: lose the TV remote
    for a, b in ("Ss", "Dd", "Ff", "Cc", "Tt", "Ww", "Mm", "Pp", "MP"):
        assert used[a] == used[b], a
    # the shortcuts call the scene's command (8, n): S 3 (store), D 1 (details), F 7 (family), C 4, T 8
    for ch, n in (("S", 3), ("D", 1), ("C", 4), ("T", 8), ("F", 7)):
        assert at(exe, used[ch] + 5, 4) == bytes([0x6A, n, 0x6A, 8]), ch
    # number keys: the view jumps (x, y) = these, top-left of the view
    views = {}
    for ch in "123456789":
        target = used[ch]
        views[ch] = target
    assert len(set(views.values())) == 9


def test_the_screens_that_share_esc_as_their_first_button(exe):
    # Achievements, Adoption, Dating and Family tree: slot 2 is 0x439150, which sends command (8, 1) on Esc
    for vtable in (0x4B6B8C, 0x4B6BD4, 0x4B6C64, 0x4B6CAC):
        assert u32(exe, vtable + 8) == 0x439150
    assert at(exe, 0x439150, 0x1E) == bytes.fromhex("837c240406751a817c2408e803000075108b018b500c6a016a08ffd2b001")
    # Adoption's command 1 is Adopt: it marks the child present (villager +0x13574 = 1)
    assert u32(exe, 0x4B6BD4 + 12) == 0x436780 and at(exe, 0x4367DF, 7) == bytes.fromhex("c6867435010001")
    # Dating's command 1 is Marry (button 1 is labelled Marry, 2 Reject)
    assert u32(exe, 0x4B6C64 + 12) == 0x438160


def test_the_tip_rolls_and_the_click_spot(exe):
    # the click spot's rectangle (theMainScene +0x88..+0x94) and rand(50) + the first tip's id 0x5FB
    assert at(exe, 0x444015, 0x28) == bytes.fromhex(
        "c78688000000ab000000c7868c000000e8010000c78690000000dd000000c7869400000048020000")
    assert at(exe, 0x4471BB, 4) == bytes.fromhex("6aff6a32") and call_target(exe, 0x4471BF) == 0x403650
    assert at(exe, 0x4471C7, 5) == bytes.fromhex("05fb050000")
    # the loading screen: rand(30) + 0x5FB
    assert at(exe, 0x440571, 2) == bytes.fromhex("6a1e") and at(exe, 0x440581, 5) == bytes.fromhex("05fb050000")
    # the view's rectangle the spot must be outside of: 0,0 .. 800,561
    assert struct.unpack_from("<4I", exe, 0x4FE180 - BASE) == (0, 0, 800, 561)


def test_the_random_tip_texts_are_the_exes(exe):
    texts = {}
    for off in range(0x4E0000 - BASE, 0x510000 - BASE, 4):
        sid, key, text = struct.unpack_from("<III", exe, off)
        if BASE <= key < 0x600000 and BASE <= text < 0x600000 and 0x5FB <= sid <= 0x62C:
            k = exe[key - BASE:key - BASE + 32].split(b"\0")[0]
            if k == b"eRandomTip%d" % (sid - 0x5FA):
                texts[sid - 0x5FA] = exe[text - BASE:text - BASE + 200].split(b"\0")[0].decode("latin-1")
    assert [texts[n] for n in range(1, 51)] == list(gm.RANDOM_TIPS)


def test_the_tv_remote(exe):
    # returned: on the coffee table (1562, 706); lost: a random spot (0x492A30 picks an area of kind 7)
    assert at(exe, 0x423AC3, 0x14) == bytes.fromhex("c786800100001a060000c78684010000c2020000")
    assert call_target(exe, 0x423AB0) == 0x403650 and at(exe, 0x423AAB, 2) == bytes.fromhex("6a05")  # 24 + rand(5)
    assert at(exe, 0x442A25, 3) == bytes.fromhex("83f832")                 # the remote's id, 0x32


def test_the_dead_developer_tools_are_never_reached(exe):
    text = exe[0x1000:0xB2000]
    # no code sets the scene to 5 (theAlignVillagerScene): mov dword [reg + 0x1B300], 5
    assert not re.search(rb"\xc7[\x80-\x87]\x00\xb3\x01\x00\x05\x00\x00\x00", text)
    # the light source editor (0x56B070) and the waypoint editor (0x56B08C) are static objects: the CRT initializers
    # 0x4B17B0 / 0x4B17C0 (listed at 0x4B24E0 / 0x4B24E4) build them, and nothing else refers to either object, so
    # no code can reach their key handlers 0x44DB30 / 0x44DED0
    assert at(exe, 0x4B17B0, 10) == bytes.fromhex("b970b05600e9e6c5f9ff")
    assert at(exe, 0x4B17C0, 10) == bytes.fromhex("b98cb05600e936c8f9ff")
    assert (u32(exe, 0x4B24E0), u32(exe, 0x4B24E4)) == (0x4B17B0, 0x4B17C0)
    for obj in range(0x56B070, 0x56B0A8):
        assert exe.count(struct.pack("<I", obj)) == (1 if obj in (0x56B070, 0x56B08C) else 0), hex(obj)
    for vtable, handler in ((0x4B93CC, 0x44DB30), (0x4B9428, 0x44DED0)):
        assert exe.count(struct.pack("<I", vtable)) == 1                  # stored only by its own constructor
        assert u32(exe, vtable + 8) == handler and exe.count(struct.pack("<I", handler)) == 1
