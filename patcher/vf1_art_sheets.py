"""Every picture file of the game folder, whole and cut into the cells the game cuts it into (the image table
0x4F2D00 and ldwImageGrid::GetCellRect 0x40AD40, vf1_game_art), and the patcher's own pictures.

Whether the game ever shows a picture or a cell comes from the area modules' USAGE / CELL_LABELS / CELL_UNUSED /
CELL_DRAW (vf1_art_meters, vf1_art_ui, vf1_art_house, vf1_art_misc), each proved there against the game's code;
the files the image table does not name are listed below with the code that loads them or why none does.
"""
from __future__ import annotations

from pathlib import Path

import vf1_game_art as ga
import vf1_picture_image as pi

TITLE = "Picture files"
SUB = "Picture files"                # the sub-category every sheet goes in, beside the area's assembled pictures

AREA_MODULES = ("vf1_art_meters", "vf1_art_ui", "vf1_art_house", "vf1_art_misc")

# Image id -> the catalogue's top-level category.
_CATEGORY_IDS = {
    "Meters and bars": (0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x38, 0x39, 0x3A, 0xCC),
    "Buttons and controls": (*range(0x22, 0x2C), 0x2F, 0x30, *range(0x31, 0x38), 0x48, *range(0x49, 0x4D),
                             *range(0xC3, 0xCA)),
    "Dialogs and panels": (0x2C, 0x2D, 0x2E, 0xC1, 0xC2, 0xCA, 0xCB, 0xCD),
    "Icons and cursors": (0x01, 0x02, 0x3B, 0x6C, 0x6D, 0xD1, 0xD3, 0x40, 0x41, 0x42),
    "House and yard": (0x1E, 0x1F, 0x20, 0x59, 0x8A, 0x89, 0x8F, 0x90, 0x87, 0x8E, 0xD5, 0xD4, 0x11, 0x12, 0x13),
    "Furniture and objects": (*range(0x14, 0x1A), 0x21, *range(0x80, 0x89), 0x8B, 0x8C, 0x8D,
                              *range(0x91, 0x9B), 0xBF),
    "Food and cooking": (0x0E, 0x0F, 0x10, 0x1A, 0x1B, 0x1C, 0x1D),
    "Weather, day and night": (0x79, 0x9B, 0x61, 0xA6, 0xA7, 0x3E, *range(0xAE, 0xB8)),
    "Effects and animations": (*range(0x5B, 0x61), *range(0x62, 0x68), 0x69, 0x6A, 0x6B, *range(0x6E, 0x77),
                               0x78, 0x7A, 0x7F, 0xA5),
    "Animals and insects": (0x0D, 0x7B, 0x7C, 0x7D, 0x7E, *range(0xA8, 0xAE), 0x03, 0xD2),
    "People": (0x04, 0x05, *range(0x9C, 0xA5), 0x68),
    "Store": (0xB8, 0xB9, 0xCE, 0xCF, 0xD0),
    "Collectibles and collections": (0x52, 0x53, 0x54, 0x55, 0x77),
    "Screens and backgrounds": (0x3C, 0x3D, 0x3F, 0x5A, 0x43, 0x44, 0x45, 0x46, 0x47, 0x4F, 0x50, 0x51, 0x57,
                                0x58, *range(0xBA, 0xBF), 0xC0),
}
CATEGORY = {image: cat for cat, ids in _CATEGORY_IDS.items() for image in ids}

NOT_NAMED = ("No string in the game names this file, and the only picture name the game builds is the map tiles' "
             "(0x4D7A0C), so the game never loads it.")
# Files in a game folder the image table does not name: (category, used, why).
OTHER_FILES = {
    "splash_bg.jpg": ("Screens and backgrounds", True,
                      "Shown when the game starts without the LDW flash intro (ForceStaticSplash, Windows 2000, or "
                      "the intro not starting) (0x448A30)."),
    "help1.jpg": ("Screens and backgrounds", False, NOT_NAMED),
    "help2.jpg": ("Screens and backgrounds", False, NOT_NAMED),
    "help3.jpg": ("Screens and backgrounds", False, NOT_NAMED),
    "help4.jpg": ("Screens and backgrounds", False, NOT_NAMED),
    "credits.jpg": ("Screens and backgrounds", False, NOT_NAMED),
    "drm/virtualfamilies_drm.jpg": ("Screens and backgrounds", False,
                                    "Art of the copy-protection web page beside the game. " + NOT_NAMED),
    "drm/logo1.gif": ("Icons and cursors", False, "Art of the copy-protection web page beside the game. " + NOT_NAMED),
}
MAP_WHY = "A tile of the yard and the house, loaded by 0x495C60 and drawn by 0x495D90."
ICON = ("Icons and cursors", True, "The game window's icon: 0x408639 loads it (SDL_LoadBMP_RW) and gives it to "
        "SDL_SetWindowIcon.")
PATCHER_SETS = (
    (ga.PAYLOAD / "CustomImages", "Custom map and game pictures",
     "Put in the game's Images folder in place of the game's own by the patcher's Custom Map/Game Images patch."),
    (ga.PAYLOAD / "GlowingCollectables", "Glowing collectables",
     "Put in the game's Images folder in place of the game's own by the patcher's Glowing Collectables patch."),
    (ga.PAYLOAD / "UnicodeText", "Unicode font letters",
     "The patcher-made letters of a font the game loads, which the Render Unicode with In-Game Fonts patch puts in "
     "the Virtual Families 1 Patcher Files folder for its vf1text.dll (the game's own font picture is not changed)."),
    (ga.TREE_PICTURES, "Family tree backgrounds",
     "A background the patcher's family tree pictures can be drawn on (the patcher's own; the game never shows it)."),
)
FONT_FILES_HANDLED_BY = "vf1_art_fonts"      # the font pictures are listed (whole and every glyph) there


def _areas() -> list:
    out = []
    for name in AREA_MODULES:
        try:
            out.append(__import__(name))
        except ImportError:
            continue
    return out


def merged() -> tuple[dict, dict, dict, dict]:
    """(USAGE, CELL_LABELS, CELL_UNUSED, CELL_DRAW) of every area module together."""
    usage, labels, unused, draw = {}, {}, {}, {}
    for mod in _areas():
        usage.update(getattr(mod, "USAGE", {}))
        labels.update(getattr(mod, "CELL_LABELS", {}))
        unused.update(getattr(mod, "CELL_UNUSED", {}))
        draw.update(getattr(mod, "CELL_DRAW", {}))
    return usage, labels, unused, draw


def _font_files() -> set[str]:
    try:
        import vf1_art_fonts
        return {name.lower() for name in vf1_art_fonts.font_files()}
    except (ImportError, AttributeError):
        return set()


def table_ids_by_file() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for image in ga.TABLE:
        if image == 0:
            continue
        for name in ga.table_files(image):
            out.setdefault(name.lower(), []).append(image)
    return out


CELLS_CHECKED = ("Cut where the game's own GetCellRect 0x40AD40, run in Unicorn, cuts it; the cell's own pixels, "
                 "as the game's plain blit draws them.")
WHOLE_CHECKED = "The file's own pixels, as the game's picture loader reads them."


def _cell_draw_checked(scale: float, alpha: float) -> str:
    if scale == 1.0 and alpha == 1.0:
        return CELLS_CHECKED
    return (CELLS_CHECKED.replace("as the game's plain blit draws them", "")
            .rstrip(", ") + f", at {scale:g} size and {alpha:g} see-through as the game's blitter 0x404C30 draws "
            "every one of them.")


def _sheet_arts(files: ga.GameFiles, name: str, path_name: str, category: str, used: bool, why: str,
                image: int | None, labels: dict, unused: dict, draw: dict, key_prefix: str,
                patcher: bool = False) -> list[ga.Art]:
    arts = []
    shape = ga.grid_shape(image) if image is not None else None
    files_across = ga.TABLE[image][3] if image is not None else 1
    sub = f"{category}/{SUB}"
    if shape is None or shape == (1, 1):
        what = "drawn whole" if shape is None else "one cell, the whole picture"
        arts.append(ga.Art(f"{key_prefix}/{name.lower()}", sub, f"{name} ({what})", (ga.whole(path_name),), used,
                           why, WHOLE_CHECKED if not patcher else "", patcher))
        return arts
    cols, rows = shape
    sheet_names = [path_name] if files_across == 1 else [
        path_name.replace(Path(path_name).name, n) for n in ga.table_files(image)]
    for k, sheet in enumerate(sheet_names):
        sheet_label = Path(sheet).name
        arts.append(ga.Art(f"{key_prefix}/{sheet_label.lower()}", sub,
                           f"{sheet_label} (the whole sheet: the game draws its cells, never the whole sheet)",
                           (ga.whole(sheet),), used, why, WHOLE_CHECKED if not patcher else "", patcher))
    scale, alpha, draw_why = draw.get(image, (1.0, 1.0, "")) if image is not None else (1.0, 1.0, "")
    sizes = [files.size(s) for s in sheet_names]
    group = f"{sub}/{Path(path_name).stem if files_across == 1 else Path(path_name).name}"
    for row in range(rows):
        for col in range(cols):
            index = row * cols + col
            file_index, rect = ga.cell_rect(sizes[0], cols, rows, col, row, files_across)
            label = labels.get((image, index))
            text = f"Cell {index + 1} (row {row + 1}, column {col + 1})" + (f": {label}" if label else "")
            cell_used, cell_why = used, why
            if used and (image, index) in unused:
                cell_used, cell_why = False, unused[(image, index)]
            if draw_why:
                cell_why = f"{cell_why} {draw_why}"
            layer = pi.Draw("cell", sheet_names[file_index], rect, 0, 0, scale, alpha)
            arts.append(ga.Art(f"{key_prefix}/{Path(path_name).name.lower()}/{index}", group, text, (layer,),
                               cell_used, cell_why, "" if patcher else _cell_draw_checked(scale, alpha), patcher))
    return arts


def arts(files: ga.GameFiles) -> list[ga.Art]:
    usage, labels, unused, draw = merged()
    by_file = table_ids_by_file()
    fonts = _font_files()
    out: list[ga.Art] = []
    names = files.names()
    done = set()
    # the image table's files, in its order
    for image in ga.TABLE:
        if image == 0:
            continue
        name, _c, _r, files_across = ga.TABLE[image]
        stem_key = name.lower()
        if stem_key in done:
            continue
        ids = [i for i in ga.TABLE if ga.TABLE[i][0].lower() == stem_key]
        present = all(n.lower() in names for n in ga.table_files(image))
        if not present:
            continue                               # a file the game's table names but the game does not have
        done.add(stem_key)
        for n in ga.table_files(image):
            done.add(n.lower())
        uses = [usage[i] for i in ids if i in usage]
        used = any(u[0] for u in uses)
        why = " ".join(u[1] for u in uses if u[0] == used) if uses else ga.CHECK + ": where the game draws it."
        if len(ids) > 1:
            why = f"The image table names this file {len(ids)} times. " + " ".join(
                f"Picture {i:#04x}: {usage[i][1]}" for i in ids if i in usage)
        category = CATEGORY.get(image, "Screens and backgrounds")
        actual = names[ga.table_files(image)[0].lower()].name if files_across == 1 else name
        drawn_id = next((i for i in ids if i in usage and usage[i][0]), ids[0])
        out += _sheet_arts(files, actual, actual if files_across == 1 else name, category, used, why, drawn_id,
                           labels, unused, draw, "sheets")
    # every other file the folder has
    for lower, path in sorted(names.items()):
        if lower in done or lower in fonts or not lower.endswith((".png", ".jpg", ".gif", ".bmp")):
            continue
        rel = path.relative_to(files.folder / ga.IMAGES_DIR).as_posix()
        if lower.startswith("mapx") and lower.endswith(".jpg"):
            entry = ("House and yard", True, MAP_WHY)
        else:
            entry = OTHER_FILES.get(lower, ("Screens and backgrounds", False, NOT_NAMED))
        category, used, why = entry
        out.append(ga.Art(f"sheets/{lower}", f"{category}/{SUB}", f"{rel} (drawn whole)" if used else rel,
                          (ga.whole(rel),), used, why, WHOLE_CHECKED))
    if files.has("root:icon.bmp"):
        category, used, why = ICON
        out.append(ga.Art("sheets/icon.bmp", f"{category}/{SUB}", "icon.bmp (the window's icon)",
                          (ga.whole("root:icon.bmp"),), used, why,
                          "The file's own pixels (a lossless BMP, read as SDL_LoadBMP reads it)."))
    out += patcher_arts(files)
    return out


def patcher_arts(files: ga.GameFiles) -> list[ga.Art]:
    """The pictures the patcher brings (labelled "(patcher)"), each cut as the game cuts the picture it replaces."""
    by_file = table_ids_by_file()
    usage, labels, unused, draw = merged()
    out = []
    for folder, title, why in PATCHER_SETS:
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            if path.suffix.lower() not in (".png", ".jpg"):
                continue
            ids = by_file.get(path.name.lower(), [])
            image = ids[0] if ids else None
            replaces = f" It replaces the game's {path.name}." if ids or path.name.lower().startswith("mapx") else ""
            out += _sheet_arts(files, path.name, f"patcher:{path}", f"Patcher's own pictures/{title}", True,
                               why + replaces, image, labels, {}, {}, f"patcher/{folder.name.lower()}",
                               patcher=True)
    return out
