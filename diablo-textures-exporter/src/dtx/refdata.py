from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from dtx.paths import canonical

DATA_DIR = Path(__file__).parent / "data"
PINNED_DEVILUTIONX = "8bef7bce51641b8faa1f56f4119e5b6ee6ec6f3f"

# Constant widths from DevilutionX Source/*.cpp LoadCel(...) calls at the pinned commit.
MANUAL_WIDTHS: dict[str, int] = {
    "ctrlpan\\p8but2.cel": 33, "ctrlpan\\talkbutt.cel": 61, "ctrlpan\\golddrop.cel": 261,
    "ctrlpan\\p8bulbs.cel": 88, "ctrlpan\\panel8bu.cel": 71,
    "data\\diabsmal.cel": 296, "data\\pentspin.cel": 48, "data\\pentspn2.cel": 12,
    "data\\square.cel": 64, "data\\textbox.cel": 591, "data\\textbox2.cel": 271,
    "data\\textslid.cel": 12, "data\\spelli2.cel": 37, "data\\hf_logo3.cel": 430,
    "items\\duricons.cel": 32, "items\\map\\mapztown.cel": 640, "towners\\animals\\cow.cel": 128,
    "levels\\towndata\\towns.cel": 64, "levels\\l1data\\l1s.cel": 64,
    "levels\\l2data\\l2s.cel": 64, "nlevels\\l5data\\l5s.cel": 64,
    # Side panels are SidePanelSize.width = 320 (Source/control/control.hpp:38; loaded in
    # Source/panels/spell_book.cpp:123, Source/control/control_panel.cpp:421, Source/inv.cpp:1181).
    # Inference would pick 640, which also fits by packing two 320-px rows into one.
    "data\\spellbk.cel": 320, "data\\quest.cel": 320, "data\\char.cel": 320,
    "data\\inv\\inv.cel": 320, "data\\inv\\inv_rog.cel": 320, "data\\inv\\inv_sor.cel": 320,
}
MONSTER_ANIMS = "nwahds"
ARMOUR = "lmh"
WEAPONS = "nusdbamht"
PLAYER_ANIMS = {
    "st": "stand", "as": "stand", "wl": "walk", "aw": "walk", "at": "attack", "ht": "swHit",
    "bl": "block", "lm": "lightning", "fm": "fire", "qm": "magic", "dt": "death",
}
# DevilutionX dungeon_type -> the level's default palette.
LEVEL_TYPE_PALETTES = {
    "DTYPE_CATHEDRAL": "levels\\l1data\\l1_1.pal", "DTYPE_CATACOMBS": "levels\\l2data\\l2_1.pal",
    "DTYPE_CAVES": "levels\\l3data\\l3_1.pal", "DTYPE_HELL": "levels\\l4data\\l4_1.pal",
    "DTYPE_CRYPT": "nlevels\\l5data\\l5base.pal", "DTYPE_NEST": "nlevels\\l6data\\l6base1.pal",
}
# Dungeon level bands (currlevel): 1-4 cathedral, 5-8 catacombs, 9-12 caves, 13-16 hell,
# 17-20 Hellfire nest, 21-24 Hellfire crypt.
LEVEL_BANDS = (
    (1, 4, "DTYPE_CATHEDRAL"), (5, 8, "DTYPE_CATACOMBS"), (9, 12, "DTYPE_CAVES"),
    (13, 16, "DTYPE_HELL"), (17, 20, "DTYPE_NEST"), (21, 24, "DTYPE_CRYPT"),
)
BARE_EXTENSIONS = (".cel", ".cl2", ".pcx", ".pal", ".trn")
LITERAL = re.compile(r'"((?:[A-Za-z0-9_]+\\\\)+[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9]{2,4})?)"')
RAW_LITERAL = re.compile(r'R"\(((?:[A-Za-z0-9_]+\\)+[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9]{2,4})?)\)"')


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return [{k: (v or "") for k, v in row.items()} for row in csv.DictReader(f, delimiter="\t")]


def read_kv_tsv(path: Path) -> dict[str, str]:
    return {row["Variable"]: row["Value"] for row in read_tsv(path)}


def _set_width(widths: dict[str, int | list[int]], path: str, value: int) -> None:
    """Record a width, ignoring non-positive values and never overwriting an existing entry
    (so MANUAL_WIDTHS, and the first positive value seen for a path, always win)."""
    if value <= 0:
        return
    if path not in widths:
        widths[path] = value


def _add_bare(names: set[str], name: str) -> None:
    if re.search(r"\.[a-z0-9]{2,4}$", name):
        names.add(name)
    else:
        names.update(name + ext for ext in BARE_EXTENSIONS)


def source_names(source: Path) -> set[str]:
    names: set[str] = set()
    for path in source.rglob("*"):
        if path.suffix not in {".cpp", ".h", ".hpp"}:
            continue
        text = path.read_text(errors="ignore")
        for m in LITERAL.finditer(text):
            _add_bare(names, canonical(m.group(1).replace("\\\\", "\\")))
        for m in RAW_LITERAL.finditer(text):
            _add_bare(names, canonical(m.group(1)))
    return names


def level_names() -> set[str]:
    names: set[str] = set()
    parts = ("cel", "min", "til", "sol", "amp")
    for n in range(1, 5):
        d = f"levels\\l{n}data\\"
        names |= {f"{d}l{n}.{e}" for e in parts} | {f"{d}l{n}s.cel"}
        names |= {f"{d}l{n}_{v}.pal" for v in range(1, 6)}
    for d in ("levels\\towndata\\", "nlevels\\towndata\\"):
        names |= {f"{d}town.{e}" for e in parts + ("pal",)} | {f"{d}towns.cel"}
    names |= {f"nlevels\\l5data\\l5.{e}" for e in parts} | {"nlevels\\l5data\\l5s.cel", "nlevels\\l5data\\l5base.pal"}
    names |= {f"nlevels\\l6data\\l6.{e}" for e in parts} | {"nlevels\\l6data\\l6base.pal"}
    names |= {f"nlevels\\l6data\\l6base{v}.pal" for v in range(1, 6)}
    return names


def _int(value: str | None) -> int:
    try:
        return int((value or "").strip())
    except ValueError:
        return 0


def _object_level_palette(row: dict[str, str]) -> str | None:
    level_type = (row.get("levelType") or "").strip()
    if level_type in LEVEL_TYPE_PALETTES:
        return LEVEL_TYPE_PALETTES[level_type]
    low, high = _int(row.get("minLevel")), _int(row.get("maxLevel"))
    if low <= 0 or high <= 0:
        return None
    for first, last, dtype in LEVEL_BANDS:
        if first <= low and high <= last:
            return LEVEL_TYPE_PALETTES[dtype]
    return None


def object_palettes(dvx: Path) -> dict[str, str]:
    """Object sprite -> level palette, from objdat.tsv levelType, or from minLevel..maxLevel when
    the range lies inside one dungeon band. The first mapping found for a file wins."""
    tables = [dvx / "assets" / "txtdata" / "objects" / "objdat.tsv",
              dvx / "mods" / "hf" / "txtdata" / "objects" / "objdat.tsv"]
    palettes: dict[str, str] = {}
    for table in tables:
        if not table.exists():
            continue
        for row in read_tsv(table):
            file = canonical(row["file"].strip())
            palette = _object_level_palette(row)
            if file and palette:
                palettes.setdefault(f"objects\\{file}.cel", palette)
    return palettes


def table_widths(dvx: Path) -> tuple[dict[str, int | list[int]], dict[str, list[str]], set[str]]:
    txt = dvx / "assets" / "txtdata"
    # Hellfire-only monsters and missiles are defined in the Hellfire mod's tables.
    table_dirs = [txt, dvx / "mods" / "hf" / "txtdata"]
    widths: dict[str, int | list[int]] = dict(MANUAL_WIDTHS)
    variants: dict[str, list[str]] = {}
    names: set[str] = set()

    monster_rows = [row for t in table_dirs if (t / "monsters" / "monstdat.tsv").exists()
                    for row in read_tsv(t / "monsters" / "monstdat.tsv")]
    def add_variant(base: str, trn_path: str) -> None:
        for anim in MONSTER_ANIMS:
            lst = variants.setdefault(f"{base}{anim}.cl2", [])
            if trn_path not in lst:
                lst.append(trn_path)
        names.add(trn_path)

    monster_bases: dict[str, str] = {}
    for row in monster_rows:
        base = "monsters\\" + canonical(row["assetsSuffix"])
        monster_bases.setdefault(row["_monster_id"].strip(), base)
        trn = canonical(row["trnFile"].strip())
        for anim in MONSTER_ANIMS:
            _set_width(widths, f"{base}{anim}.cl2", int(row["width"]))
        if trn:
            add_variant(base, f"monsters\\{trn}.trn")
    # A unique monster recolours its base type's sprites with monsters\\monsters\\<trn>.trn
    # (Source/monster.cpp InitTRNForUniqueMonster).
    unique_rows = [row for t in table_dirs if (t / "monsters" / "unique_monstdat.tsv").exists()
                   for row in read_tsv(t / "monsters" / "unique_monstdat.tsv")]
    for row in unique_rows:
        for key, value in row.items():
            if key and "trn" in key.lower() and value.strip():
                names.add(f"monsters\\monsters\\{canonical(value.strip())}.trn")
        trn = canonical((row.get("trn") or "").strip())
        base = monster_bases.get((row.get("type") or "").strip())
        if trn and base:
            add_variant(base, f"monsters\\monsters\\{trn}.trn")

    missile_rows = [row for t in table_dirs if (t / "missiles" / "missile_sprites.tsv").exists()
                    for row in read_tsv(t / "missiles" / "missile_sprites.tsv")]
    for row in missile_rows:
        name = canonical(row["name"].strip())
        if not name:
            continue
        count = int(row["numFrames"])
        paths = [f"missiles\\{name}.cl2"] + [f"missiles\\{name}{i}.cl2" for i in range(0, count + 1)]
        for path in paths:
            _set_width(widths, path, int(row["width"]))

    for row in read_tsv(txt / "objects" / "objdat.tsv"):
        file = canonical(row["file"].strip())
        if file:
            _set_width(widths, f"objects\\{file}.cel", int(row["animWidth"]))

    for sprites in sorted((txt / "classes").glob("*/sprites.tsv")):
        kv = read_kv_tsv(sprites)
        folder, char = canonical(kv["classPath"]), kv["classChar"].lower()
        for armour in ARMOUR:
            for weapon in WEAPONS:
                prefix = f"{char}{armour}{weapon}"
                for anim, key in PLAYER_ANIMS.items():
                    width_key = "bow" if (anim == "at" and weapon == "b") else key
                    _set_width(widths, f"plrgfx\\{folder}\\{prefix}\\{prefix}{anim}.cl2", int(kv[width_key]))

    for cursor_widths, cel in ((dvx / "assets" / "data" / "inv" / "objcurs-widths.txt", "data\\inv\\objcurs.cel"),
                               (dvx / "mods" / "hf" / "data" / "inv" / "objcurs2-widths.txt",
                                "data\\inv\\objcurs2.cel")):
        if cursor_widths.exists():
            widths[cel] = [int(v) for v in cursor_widths.read_text().split()]
    return widths, variants, names


def build(dvx: Path, stack, out_dir: Path = DATA_DIR, community: Path | None = None) -> dict:
    widths, variants, names = table_widths(dvx)
    names |= set(widths) | source_names(dvx / "Source") | level_names()
    # The current listfile is always a candidate source, so a rebuild never loses names
    # (e.g. community names when the community listfile is not available).
    current = out_dir / "listfile.txt"
    sources = ([current] if current.exists() else []) + ([community] if community is not None else [])
    for listfile in sources:
        names |= {canonical(line.strip()) for line in listfile.read_text(errors="ignore").splitlines()
                  if line.strip()}
    present = sorted(n for n in names if stack.has(n))
    present_set = set(present)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "listfile.txt").write_text("\n".join(present) + "\n")
    kept_widths = {k: widths[k] for k in sorted(widths) if k in present_set}
    (out_dir / "widths.json").write_text(json.dumps(kept_widths, indent=1) + "\n")
    kept_variants = {}
    for k in sorted(variants):
        if k in present_set:
            trns = [t for t in variants[k] if t in present_set]
            if trns:
                kept_variants[k] = trns
    (out_dir / "variants.json").write_text(json.dumps(kept_variants, indent=1) + "\n")
    kept_palettes = {k: v for k, v in sorted(object_palettes(dvx).items()) if k in present_set and v in present_set}
    (out_dir / "palettes.json").write_text(json.dumps(kept_palettes, indent=1) + "\n")
    return {"candidates": len(names), "present": len(present)}


def listfile_path() -> Path:
    return DATA_DIR / "listfile.txt"


def load_widths() -> dict:
    path = DATA_DIR / "widths.json"
    return json.loads(path.read_text()) if path.exists() else {}


def load_palettes() -> dict:
    path = DATA_DIR / "palettes.json"
    return json.loads(path.read_text()) if path.exists() else {}


def load_variants() -> dict:
    path = DATA_DIR / "variants.json"
    return json.loads(path.read_text()) if path.exists() else {}
