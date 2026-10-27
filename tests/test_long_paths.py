"""Deep folders: the patcher's own files may pass MAX_PATH (it uses the \\\\?\\ form for them); a game file never may
(the modded folder is refused before anything is written)."""
import json
import re
import sys
from pathlib import Path

import pytest

import vf1_patcher as vp


def deep_folder(base: Path, length: int) -> Path:
    """A folder under ``base`` whose path is exactly ``length`` characters (segments of at most 60)."""
    path = str(base.resolve())
    assert len(path) + 2 <= length, "the test's base folder is already too deep"
    while len(path) < length:
        room = length - len(path) - 1          # the separator
        step = min(room, 60)
        if room - step == 1:                   # never leave room for only a separator
            step -= 1
        path += "\\" + "d" * step
    assert len(path) == length
    return Path(path)


def game_file_rels(vanilla: Path, manifest: dict) -> list[str]:
    """Every game file a modded folder can get (a superset of what one run writes)."""
    rels = [*vp.vanilla_rel_files(vanilla), vp.DLL_REL, vp.SETTINGS_REL, vp.manifest_output_exe_name(manifest)]
    for setting in vp.manifest_settings(manifest).values():
        for f in setting.files:
            rels += [f.target, vp.original_store_rel(f.target)]
    return rels


def apply(*args):
    return vp.main(["apply", *args])


@pytest.mark.skipif(sys.platform != "win32", reason="the \\\\?\\ form is Windows'")
def test_long_path_and_shown_path():
    assert str(vp.long_path("C:\\a\\b")) == "\\\\?\\C:\\a\\b"
    assert vp.long_path(vp.long_path("C:\\a\\b")) == vp.long_path("C:\\a\\b")
    assert str(vp.long_path("\\\\server\\share\\x")) == "\\\\?\\UNC\\server\\share\\x"
    assert vp.shown_path(vp.long_path("\\\\server\\share\\x")) == "\\\\server\\share\\x"
    assert vp.shown_path("see \\\\?\\C:\\a and \\\\?\\UNC\\s\\h") == "see C:\\a and \\\\s\\h"
    assert str(vp.PatchError("in \\\\?\\C:\\a")) == "in C:\\a"
    error = FileNotFoundError(2, "gone", str(vp.long_path("C:\\a\\b")))     # quotes its path as repr() does
    assert vp.shown_path(str(error)) == str(FileNotFoundError(2, "gone", "C:\\a\\b"))
    unc = FileNotFoundError(2, "gone", str(vp.long_path("\\\\s\\h\\b")))
    assert vp.shown_path(str(unc)) == str(FileNotFoundError(2, "gone", "\\\\s\\h\\b"))


def test_a_deep_modded_folder_builds_backs_up_and_restores(vanilla_unchanged, tmp_path, capsys):
    """The modded folder as deep as the game allows: its game files reach 259 characters, its backup copies and
    a chosen log pass 260, and every one is written, read back and restored."""
    manifest = vp.read_json(vp.DEFAULT_MANIFEST)
    longest = max(len(rel) for rel in game_file_rels(vanilla_unchanged, manifest))
    out = deep_folder(tmp_path, vp.MAX_GAME_PATH - 1 - longest)
    log = deep_folder(tmp_path / "log", 270) / "patch log.json"
    assert apply("--exe", str(vanilla_unchanged / vp.VANILLA_EXE), "--output-dir", str(out)) == 0
    assert vp.long_path(out / vp.DLL_REL).is_file()
    assert apply("--output-dir", str(out), "--disable-all", "--log", str(log)) == 0   # backs up the first build
    text = vp.long_path(log).read_text(encoding="utf-8")
    assert "\\\\?\\" not in text.replace("\\\\", "\\")
    backup = Path(json.loads(text)["backup_dir"])
    copies = [p for p in vp.long_path(backup).rglob("*") if p.is_file()]
    assert copies and max(len(vp.shown_path(p)) for p in copies) > 260
    assert "\\\\?\\" not in capsys.readouterr().out
    assert vp.main(["restore", "--backup-dir", str(backup)]) == 0
    assert vp.long_path(backup / "restore_log.json").is_file()


@pytest.mark.parametrize("dry_run", [False, True])
def test_a_modded_folder_too_deep_for_the_game_is_refused_up_front(vanilla_unchanged, tmp_path, dry_run, capsys):
    longest = max(len(rel) for rel in vp.vanilla_rel_files(vanilla_unchanged))
    out = deep_folder(tmp_path, vp.MAX_GAME_PATH - longest)        # that vanilla file would be 260 characters
    args = ["--exe", str(vanilla_unchanged / vp.VANILLA_EXE), "--output-dir", str(out)]
    assert apply(*args, *(["--dry-run"] if dry_run else [])) == 2
    message = capsys.readouterr().err
    assert "too long for the game" in message and "Nothing was changed" in message
    over = int(re.search(r"would be (\d+) characters", message).group(1)) - vp.MAX_GAME_PATH
    assert over >= 1 and f"at least {over} character{'' if over == 1 else 's'} shorter" in message
    assert "\\\\?\\" not in message
    assert not vp.long_path(out).exists()                            # nothing written, no backup


def test_reconfiguring_checks_the_files_it_would_write(tmp_path):
    out = deep_folder(tmp_path, 200)
    vp.check_game_path_lengths(out, ["a" * (vp.MAX_GAME_PATH - 201)])
    with pytest.raises(vp.PatchError, match="too long for the game"):
        vp.check_game_path_lengths(vp.long_path(out), ["a" * (vp.MAX_GAME_PATH - 200)])
