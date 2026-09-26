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
}
MONSTER_ANIMS = "nwahds"
ARMOUR = "lmh"
WEAPONS = "nusdbamht"
PLAYER_ANIMS = {
    "st": "stand", "as": "stand", "wl": "walk", "aw": "walk", "at": "attack", "ht": "swHit",
    "bl": "block", "lm": "lightning", "fm": "fire", "qm": "magic", "dt": "death",
}
BARE_EXTENSIONS = (".cel", ".cl2", ".pcx", ".pal", ".trn")
LITERAL = re.compile(r'"((?:[A-Za-z0-9_]+\\\\)+[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9]{2,4})?)"')
RAW_LITERAL = re.compile(r'R"\(((?:[A-Za-z0-9_]+\\)+[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9]{2,4})?)\)"')


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return [{k: (v or "") for k, v in row.items()} for row in csv.DictReader(f, delimiter="\t")]


def read_kv_tsv(path: Path) -> dict[str, str]:
    return {row["Variable"]: row["Value"] for row in read_tsv(path)}


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


def table_widths(dvx: Path) -> tuple[dict[str, int | list[int]], dict[str, list[str]], set[str]]:
    txt = dvx / "assets" / "txtdata"
    widths: dict[str, int | list[int]] = dict(MANUAL_WIDTHS)
    variants: dict[str, list[str]] = {}
    names: set[str] = set()

    for row in read_tsv(txt / "monsters" / "monstdat.tsv"):
        base = "monsters\\" + canonical(row["assetsSuffix"])
        trn = canonical(row["trnFile"].strip())
        for anim in MONSTER_ANIMS:
            path = f"{base}{anim}.cl2"
            widths[path] = int(row["width"])
            if trn:
                lst = variants.setdefault(path, [])
                if f"monsters\\{trn}.trn" not in lst:
                    lst.append(f"monsters\\{trn}.trn")
        if trn:
            names.add(f"monsters\\{trn}.trn")
    for row in read_tsv(txt / "monsters" / "unique_monstdat.tsv"):
        for key, value in row.items():
            if key and "trn" in key.lower() and value.strip():
                names.add(f"monsters\\monsters\\{canonical(value.strip())}.trn")

    for row in read_tsv(txt / "missiles" / "missile_sprites.tsv"):
        name = canonical(row["name"].strip())
        if not name:
            continue
        count = int(row["numFrames"])
        paths = [f"missiles\\{name}.cl2"] + [f"missiles\\{name}{i}.cl2" for i in range(0, count + 1)]
        for path in paths:
            widths[path] = int(row["width"])

    for row in read_tsv(txt / "objects" / "objdat.tsv"):
        file = canonical(row["file"].strip())
        if file:
            widths[f"objects\\{file}.cel"] = int(row["animWidth"])

    for sprites in sorted((txt / "classes").glob("*/sprites.tsv")):
        kv = read_kv_tsv(sprites)
        folder, char = canonical(kv["classPath"]), kv["classChar"].lower()
        for armour in ARMOUR:
            for weapon in WEAPONS:
                prefix = f"{char}{armour}{weapon}"
                for anim, key in PLAYER_ANIMS.items():
                    width_key = "bow" if (anim == "at" and weapon == "b") else key
                    widths[f"plrgfx\\{folder}\\{prefix}\\{prefix}{anim}.cl2"] = int(kv[width_key])

    objcurs = dvx / "assets" / "data" / "inv" / "objcurs-widths.txt"
    if objcurs.exists():
        widths["data\\inv\\objcurs.cel"] = [int(v) for v in objcurs.read_text().split()]
    return widths, variants, names


def build(dvx: Path, stack, out_dir: Path = DATA_DIR, community: Path | None = None) -> dict:
    widths, variants, names = table_widths(dvx)
    names |= set(widths) | source_names(dvx / "Source") | level_names()
    if community is not None:
        names |= {canonical(line.strip()) for line in community.read_text(errors="ignore").splitlines()
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
    return {"candidates": len(names), "present": len(present)}


def listfile_path() -> Path:
    return DATA_DIR / "listfile.txt"


def load_widths() -> dict:
    path = DATA_DIR / "widths.json"
    return json.loads(path.read_text()) if path.exists() else {}


def load_variants() -> dict:
    path = DATA_DIR / "variants.json"
    return json.loads(path.read_text()) if path.exists() else {}
