"""The five achievements for the patcher's own features (Love Is Love, Instant Family,
New Blood, Clean Sweep, Green Thumb) in native/vf1fun/patcher_achievements.inc.

Two kinds of check:
- Static: the rows and enum entries exist with the right names and bits, the bit
  mask that loads the saved achievements covers all of them, and each feature's
  real code path (the function that does the work) calls its Earn function. Removing
  a call makes these fail.
- Harness: the Earn functions, compiled with the same MSVC settings as native/build.bat
  (the source is included, as in test_hook_install.py), set exactly their own bit and
  the right table name. The harness skips where the Visual Studio toolchain is missing."""
import os
import re
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

NATIVE = ROOT / "native" / "vf1fun"
ACH_SRC = (NATIVE / "patcher_achievements.inc").read_text(encoding="utf-8")
FAMILY_SRC = (NATIVE / "family.inc").read_text(encoding="utf-8")
FEATURES_SRC = (NATIVE / "features.inc").read_text(encoding="utf-8")
VF1FUN_SRC = (NATIVE / "vf1fun.cpp").read_text(encoding="utf-8")
VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")

# enum name, table name, table description, Earn function, function that does the real work (file, signature)
NEW = [
    ("ACH_LOVE_IS_LOVE", "Love Is Love",
     "Marry a same-sex couple with Same-Sex Marriage on.", "EarnLoveIsLove",
     (FAMILY_SRC, r"static void SameGenderWedding\(")),
    ("ACH_INSTANT_FAMILY", "Instant Family",
     "Spawn a child into the family with the Spawn Child cheat.", "EarnInstantFamily",
     (FAMILY_SRC, r"static const wchar_t \*SpawnChild\(")),
    ("ACH_NEW_BLOOD", "New Blood",
     "Adopt a new person into the family tree.", "EarnNewBlood",
     (FAMILY_SRC, r"static bool __fastcall AdoptStartFamilyTree\(")),
    ("ACH_CLEAN_SWEEP", "Clean Sweep",
     "Have the Maid clean up the house.", "EarnCleanSweep",
     (FEATURES_SRC, r"static void MaidVisit\(")),
    ("ACH_GREEN_THUMB", "Green Thumb",
     "Have the Gardener pull the weeds.", "EarnGreenThumb",
     (FEATURES_SRC, r"static void GardenerVisit\(")),
]
OLD_COUNT = 12


def function_text(source, signature):
    """The text of the function whose header matches `signature`, through its matching closing brace."""
    m = re.search(signature, source)
    assert m, f"function not found: {signature}"
    depth, i, start = 0, source.index("{", m.end()), None
    start = i
    for j in range(start, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[m.start():j + 1]
    raise AssertionError("unterminated function")


def enum_names():
    body = re.search(r"enum \{ (ACH_LUCKY_70.*?ACH_COUNT) \};", ACH_SRC, re.S).group(1)
    return [n.strip() for n in body.replace("\n", " ").split(",") if n.strip()]


def table_rows():
    block = re.search(r"kAchievements\[ACH_COUNT\] = \{(.*?)\n\};", ACH_SRC, re.S).group(1)
    return re.findall(r'\{ L"((?:[^"\\]|\\.)*)", L"((?:[^"\\]|\\.)*)" \}', block)


# ---- static checks -------------------------------------------------------------------

def test_enum_appends_the_five_after_the_old_twelve_so_saved_bits_do_not_move():
    names = enum_names()
    assert names[:OLD_COUNT] == ["ACH_LUCKY_70", "ACH_GREAT_80", "ACH_MIGHTY_90", "ACH_CENTENARIAN",
                                 "ACH_OLDEST_IN_HISTORY", "ACH_RAINBOW", "ACH_SPIKY", "ACH_BLUES_CLUES",
                                 "ACH_DECADE_IN_BLUE", "ACH_NO_MORE_WORRIES", "ACH_WORLD_HUNGER",
                                 "ACH_EXTRAORDINAIRE"]
    assert names[OLD_COUNT:] == [n[0] for n in NEW] + ["ACH_COUNT"]


def test_table_has_the_five_new_rows_with_their_names_and_descriptions():
    rows = table_rows()
    assert len(rows) == len(enum_names()) - 1 == OLD_COUNT + len(NEW)
    for (_, name, how, _, _), row in zip(NEW, rows[OLD_COUNT:]):
        assert row == (name, how)


def test_the_five_are_the_only_new_names_and_do_not_clash():
    names = [r[0] for r in table_rows()]
    assert len(set(names)) == len(names)
    for _, name, _, _, _ in NEW:
        assert names.count(name) == 1


def test_saved_mask_covers_every_bit_and_the_total_matches_the_table():
    count = len(enum_names()) - 1
    mask = (1 << count) - 1
    assert f"& 0x{mask:X}" in FEATURES_SRC, "features.inc must load all 17 bits, not only the old 12"
    assert f"static const int kAchievementTotal = {count};" in VF1FUN_SRC


@pytest.mark.parametrize("enum, name, how, earn, where", NEW, ids=[n[1] for n in NEW])
def test_each_feature_calls_its_earn_function_where_the_work_is_done(enum, name, how, earn, where):
    source, signature = where
    body = function_text(source, signature)
    assert f"{earn}();" in body, f"{earn}() is not called from the feature's own code path"


@pytest.mark.parametrize("enum, name, how, earn, where", NEW, ids=[n[1] for n in NEW])
def test_each_earn_function_unlocks_its_own_bit(enum, name, how, earn, where):
    body = function_text(ACH_SRC, rf"static void {earn}\(\)")
    assert f"UnlockAchievement({enum})" in body


def test_new_wedding_and_adoption_checks_are_reached_on_the_real_paths():
    # Same-sex wedding: the Marry handler runs the earn on both the native and the patcher's own path.
    handler = function_text(FAMILY_SRC, r"static bool __fastcall DatingHandleMessage\(")
    assert "SameGenderWedding(resident, candidate, dowry)" in handler
    assert "EarnLoveIsLove();" in handler
    # Adopt New Person: the earn comes only after the game's add succeeded.
    adopt = function_text(FAMILY_SRC, r"static bool __fastcall AdoptStartFamilyTree\(")
    assert adopt.index("StartNextGeneration(tree, villager, -1)") < adopt.index("EarnNewBlood();")
    assert "if (added) EarnNewBlood();" in adopt
    # Spawn Child: the earn comes after the child is added, and only on the success path (return 0).
    spawn = function_text(FAMILY_SRC, r"static const wchar_t \*SpawnChild\(")
    assert spawn.index("AddOffspring(FamilyTree") < spawn.index("EarnInstantFamily();") < spawn.index("return 0;")


# ---- harness: the Earn functions set exactly their own bit -------------------------

HARNESS = r'''
#include "@SOURCE@"
#include <wchar.h>

struct Case { void (*fn)(); int bit; const wchar_t *name; };

int main() {
    const Case cases[] = {
@CASES@
    };
    int failures = 0;
    for (const Case &c : cases) {
        gVillage.achievements = 0;
        c.fn();
        unsigned expected = 1u << c.bit;
        bool exact = gVillage.achievements == expected;
        bool named = wcscmp(kAchievements[c.bit].name, c.name) == 0;
        c.fn();  // a second use is harmless
        bool again = gVillage.achievements == expected;
        if (!exact || !named || !again) {
            printf("FAIL bit %d: exact=%d named=%d again=%d got=%x\n", c.bit, exact, named, again,
                   gVillage.achievements);
            ++failures;
        }
    }
    printf("%d of %d checked\n", (int)(sizeof cases / sizeof cases[0]) - failures, (int)(sizeof cases / sizeof cases[0]));
    return failures ? 1 : 0;
}
'''

VCVARS_MISSING = not VCVARS.is_file()
SKIP_WITHOUT_TOOLCHAIN = pytest.mark.skipif(
    os.name != "nt" or VCVARS_MISSING,
    reason="needs the MSVC toolchain (vcvars32.bat) on Windows")


@pytest.fixture(scope="module")
def achievement_harness(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("achievements")
    cases = ",\n".join(f"        {{ {earn}, {enum}, L\"{name}\" }}" for enum, name, _, earn, _ in NEW)
    src = tmp_path / "achievement_harness.cpp"
    src.write_text(HARNESS.replace("@SOURCE@", (NATIVE / "vf1fun.cpp").as_posix()).replace("@CASES@", cases),
                   encoding="utf-8")
    exe = tmp_path / "achievement_harness.exe"
    script = tmp_path / "build_harness.bat"
    script.write_text(
        "@echo off\r\n"
        f'call "{VCVARS}" >nul || exit /b 1\r\n'
        f'cl /nologo /O2 /MT /EHsc /W3 "{src}" /Fo"{tmp_path}\\\\" /Fe"{exe}" '
        "/link user32.lib kernel32.lib shell32.lib gdiplus.lib gdi32.lib || exit /b 1\r\n",
        encoding="ascii")
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
        / "Microsoft Visual Studio" / "Installer"
    env = dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}")
    build = subprocess.run(["cmd", "/c", str(script)], capture_output=True, text=True, env=env)
    assert build.returncode == 0, build.stdout + build.stderr
    return exe


@SKIP_WITHOUT_TOOLCHAIN
def test_each_earn_function_sets_exactly_its_own_bit(achievement_harness):
    run = subprocess.run([str(achievement_harness)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "5 of 5 checked" in run.stdout
