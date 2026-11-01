#!/usr/bin/env python3
"""Package a player release: outputs/Virtual-Families-1-Fun-Patcher-<version>.zip.

usage: package_release.py VERSION [--dll PATH] [--out-dir DIR]
       package_release.py --transparency-log    (rewrite release/Transparency Log.txt)

Needs build/vf1fun.dll (native/build.bat), patcher/stub.json
(tools/build_stub.py) and payload/ (the files settings install, in the repository). The layout follows the Virtual Families 2 patcher's
release bundle: one folder, "Virtual-Families-1-Fun-Patcher-<version>", holding only what the player opens

  Launch_GUI.bat, Apply_<version>_Patcher.bat, How to Use.txt,
  README-<version>-PATCHER.txt, Transparency Log.txt

and one folder, "Virtual Families 1 Fun Patcher Files" (vf1_patcher.BUNDLE_FOLDER, as the Virtual Villagers
patcher's "Virtual Villagers Fun Patcher Files"), holding the rest, which the two .bat files run from it:

  manifest.json, vf1_patcher.py, vf1_patcher_gui.py, vf1_save_backup.py (Back Up Saves / Restore Saves),
  vf1_save.py, vf1_rename_family.py (Rename Family), vf1_copy_slot.py (Copy Player Slot),
  vf1_game_speed.py (Game Speed),
  vf1_game_mechanics.py (Game Mechanics), the Picture Maker (vf1_picture_maker.py, vf1_people_pictures.py,
  vf1_picture_image.py),
  vf1_how_to_use.py and how_to_use.json (the "?" guides), the Family Tree
  Maker (vf1_genealogy.py, vf1_family_history.py, vf1_tree_memory.py, vf1_family_tree*.py,
  vf1_member_info.py, vf1_relationships.py, vf1_line_colours.py, vf1_tree_editor_tools.py, vf1_gdiplus.py, and its backgrounds
  and logos in tree_pictures/), the Game Text tool and Render Unicode with In-Game Fonts' shared text rule
  (vf1_text.py, vf1_names.py -- the whole names of the one name limit --, vf1_game_fonts.py, vf1_glyph_gdi.py, vf1_glyph_maker.py, vf1_game_text.py, vf1_unicode_font.py, and
  payload/UnicodeText), stub.json, payload/vf1fun.dll

manifest.json gets the version and the SHA-256 and size of every payload
file, which the patcher checks before it installs them. No game files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patcher"))
import vf1_patcher  # noqa: E402

TRANSPARENCY_LOG = ROOT / "release" / "Transparency Log.txt"


def load_manifest() -> dict:
    return json.loads((ROOT / "patcher" / "manifest.json").read_text(encoding="utf-8"))


def write_transparency_log() -> Path:
    TRANSPARENCY_LOG.write_text(vf1_patcher.transparency_log_text(load_manifest()), encoding="utf-8", newline="\r\n")
    return TRANSPARENCY_LOG


def build(version: str, dll: Path, out_dir: Path, payload_root: Path | None = None) -> Path:
    top = f"Virtual-Families-1-Fun-Patcher-{version}"
    manifest = load_manifest()
    vf1_patcher.manifest_settings(manifest)  # refuse an inconsistent manifest
    vf1_patcher.manifest_output_exe_name(manifest)  # and a forbidden exe name
    payload = {vf1_patcher.DLL_NAME: dll}
    for setting in vf1_patcher.manifest_settings(manifest).values():
        for f in setting.files:
            path = (payload_root or ROOT / "patcher" / "payload") / f.source
            if not path.is_file() and f.source.lower().endswith(".dll"):
                path = ROOT / "build" / f.source   # a companion DLL is built (native\build_kids.bat), never committed
            payload[f.source] = path
    missing = [str(p) for p in [*payload.values(), vf1_patcher.STUB] if not p.is_file()]
    if missing:
        raise SystemExit("missing:\n  " + "\n  ".join(missing))
    manifest["version"] = version
    manifest["payload"] = {
        rel: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}
        for rel, path in sorted(payload.items())
    }
    text = lambda name: (ROOT / "release" / name).read_text(encoding="utf-8").replace("{VERSION}", version)
    crlf = lambda s: s.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    entries: dict[str, bytes] = {   # what the player opens, at the top
        "Launch_GUI.bat": crlf(text("Launch_GUI.bat")),
        f"Apply_{version}_Patcher.bat": crlf(text("Apply_Patcher.bat")),
        "How to Use.txt": crlf(text("How to Use.txt")),
        f"README-{version}-PATCHER.txt": crlf(text("README-PATCHER.txt")),
        "Transparency Log.txt": crlf(vf1_patcher.transparency_log_text(manifest)),
    }
    files: dict[str, bytes] = {     # the patcher's own files, in BUNDLE_FOLDER
        "manifest.json": (json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
        "vf1_patcher.py": (ROOT / "patcher" / "vf1_patcher.py").read_bytes(),
        "vf1_patcher_gui.py": (ROOT / "patcher" / "vf1_patcher_gui.py").read_bytes(),
        "vf1_save_backup.py": (ROOT / "patcher" / "vf1_save_backup.py").read_bytes(),
        "vf1_save.py": (ROOT / "patcher" / "vf1_save.py").read_bytes(),
        "vf1_rename_family.py": (ROOT / "patcher" / "vf1_rename_family.py").read_bytes(),
        "vf1_copy_slot.py": (ROOT / "patcher" / "vf1_copy_slot.py").read_bytes(),
        "vf1_game_speed.py": (ROOT / "patcher" / "vf1_game_speed.py").read_bytes(),
        "vf1_game_mechanics.py": (ROOT / "patcher" / "vf1_game_mechanics.py").read_bytes(),
        "vf1_picture_maker.py": (ROOT / "patcher" / "vf1_picture_maker.py").read_bytes(),
        "vf1_people_pictures.py": (ROOT / "patcher" / "vf1_people_pictures.py").read_bytes(),
        "vf1_picture_image.py": (ROOT / "patcher" / "vf1_picture_image.py").read_bytes(),
        "vf1_how_to_use.py": (ROOT / "patcher" / "vf1_how_to_use.py").read_bytes(),
        "vf1_genealogy.py": (ROOT / "patcher" / "vf1_genealogy.py").read_bytes(),
        "vf1_family_history.py": (ROOT / "patcher" / "vf1_family_history.py").read_bytes(),
        "vf1_tree_memory.py": (ROOT / "patcher" / "vf1_tree_memory.py").read_bytes(),
        "vf1_family_tree.py": (ROOT / "patcher" / "vf1_family_tree.py").read_bytes(),
        "vf1_family_tree_window.py": (ROOT / "patcher" / "vf1_family_tree_window.py").read_bytes(),
        "vf1_member_info.py": (ROOT / "patcher" / "vf1_member_info.py").read_bytes(),
        "vf1_relationships.py": (ROOT / "patcher" / "vf1_relationships.py").read_bytes(),
        "vf1_line_colours.py": (ROOT / "patcher" / "vf1_line_colours.py").read_bytes(),
        "vf1_tree_editor_tools.py": (ROOT / "patcher" / "vf1_tree_editor_tools.py").read_bytes(),
        "vf1_gdiplus.py": (ROOT / "patcher" / "vf1_gdiplus.py").read_bytes(),
        "vf1_text.py": (ROOT / "patcher" / "vf1_text.py").read_bytes(),
        "vf1_names.py": (ROOT / "patcher" / "vf1_names.py").read_bytes(),
        "vf1_game_fonts.py": (ROOT / "patcher" / "vf1_game_fonts.py").read_bytes(),
        "vf1_glyph_gdi.py": (ROOT / "patcher" / "vf1_glyph_gdi.py").read_bytes(),
        "vf1_glyph_maker.py": (ROOT / "patcher" / "vf1_glyph_maker.py").read_bytes(),
        "vf1_game_text.py": (ROOT / "patcher" / "vf1_game_text.py").read_bytes(),
        "vf1_unicode_font.py": (ROOT / "patcher" / "vf1_unicode_font.py").read_bytes(),
        "how_to_use.json": (ROOT / "patcher" / "how_to_use.json").read_bytes(),
        "stub.json": vf1_patcher.STUB.read_bytes(),
    }
    for path in sorted(vf1_patcher.TREE_PICTURES.glob("*.png")):   # the Family Tree Maker's own pictures
        files[f"tree_pictures/{path.name}"] = path.read_bytes()
    for rel, path in payload.items():
        files[f"payload/{rel}"] = path.read_bytes()
    # the Game Text tool's styles and glyph boxes for the font sheets the game never draws (the four game fonts'
    # files are payload above: Render Unicode with In-Game Fonts installs them)
    for path in sorted((ROOT / "patcher" / "payload" / "UnicodeText").glob("*.txt")):
        files.setdefault(f"payload/UnicodeText/{path.name}", path.read_bytes())
    entries.update({f"{vf1_patcher.BUNDLE_FOLDER}/{name}": data for name, data in files.items()})
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{top}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in entries.items():
            z.writestr(f"{top}/{name}", data)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", nargs="?")
    ap.add_argument("--dll", type=Path, default=ROOT / "build" / vf1_patcher.DLL_NAME)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "outputs")
    ap.add_argument("--payload", type=Path, default=ROOT / "patcher" / "payload", help="folder holding the files settings install")
    ap.add_argument("--transparency-log", action="store_true", help="rewrite release/Transparency Log.txt")
    args = ap.parse_args(argv)
    if args.transparency_log:
        print(write_transparency_log())
        return 0
    if not args.version:
        ap.error("VERSION is required")
    expected = vf1_patcher.transparency_log_text(load_manifest())
    if TRANSPARENCY_LOG.read_text(encoding="utf-8").replace("\r\n", "\n") != expected:
        print("release/Transparency Log.txt is out of date: run tools/package_release.py --transparency-log")
        return 1
    out = build(args.version, args.dll, args.out_dir, args.payload)
    data = out.read_bytes()
    print(f"{out}  {len(data):,} bytes  SHA-256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
