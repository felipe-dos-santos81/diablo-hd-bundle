from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from dtx.paths import directory, extension, stem

DEFAULT_PALETTE = "levels\\towndata\\town.pal"


@dataclass(frozen=True)
class TilesetSpec:
    key: str
    cells_per_column: int
    palette_preference: tuple[str, ...]


TILESETS: dict[str, TilesetSpec] = {
    s.key: s
    for s in (
        TilesetSpec("levels\\towndata\\town", 16, ("levels\\towndata\\town.pal",)),
        TilesetSpec("nlevels\\towndata\\town", 16, ("nlevels\\towndata\\town.pal", "levels\\towndata\\town.pal")),
        TilesetSpec("levels\\l1data\\l1", 10, ("levels\\l1data\\l1_1.pal",)),
        TilesetSpec("levels\\l2data\\l2", 10, ("levels\\l2data\\l2_1.pal",)),
        TilesetSpec("levels\\l3data\\l3", 10, ("levels\\l3data\\l3_1.pal",)),
        TilesetSpec("levels\\l4data\\l4", 16, ("levels\\l4data\\l4_1.pal",)),
        TilesetSpec("nlevels\\l5data\\l5", 10, ("nlevels\\l5data\\l5base.pal",)),
        TilesetSpec("nlevels\\l6data\\l6", 10, ("nlevels\\l6data\\l6base1.pal", "nlevels\\l6data\\l6base.pal")),
    )
}
DUN_OWNERS: dict[str, str] = {directory(k + ".x"): k for k in TILESETS}

SPRITE_PREFIXES = (
    ("monsters\\", "monster_anim"), ("plrgfx\\", "player_anim"), ("towners\\", "towner_anim"),
    ("missiles\\", "missile"), ("objects\\", "object"), ("items\\", "item"), ("data\\inv\\", "item"),
    ("ctrlpan\\", "ui_sprite"), ("data\\", "ui_sprite"), ("gendata\\", "ui_sprite"),
    ("ui_art\\", "ui_sprite"), ("levels\\", "level_sprite"), ("nlevels\\", "level_sprite"),
)
SPRITE_KINDS = frozenset({k for _, k in SPRITE_PREFIXES} | {"unknown_graphic"})
KINDS = ("palette", "trn", "ui_image", "tileset", "layout") + tuple(sorted(SPRITE_KINDS))


@dataclass(frozen=True)
class Entry:
    path: str
    kind: str
    palette: str | None = None
    palette_alternatives: tuple[str, ...] = ()
    width_hint: int | tuple[int, ...] | None = None
    variants: tuple[str, ...] = ()
    tileset: str | None = None


@dataclass(frozen=True)
class Skip:
    path: str
    reason: str


def choose_palette(preference: Iterable[str], pal_dir: str, names: set[str]) -> tuple[str | None, tuple[str, ...]]:
    in_dir = sorted(n for n in names if extension(n) == "pal" and directory(n) == pal_dir)
    default = next((p for p in preference if p in names), None)
    if default is None:
        default = in_dir[0] if in_dir else (DEFAULT_PALETTE if DEFAULT_PALETTE in names else None)
    return default, tuple(p for p in in_dir if p != default)


def classify(name: str, names: set[str], widths: Mapping, variants: Mapping) -> Entry | Skip:
    ext, base, folder = extension(name), stem(name), directory(name)
    if ext == "pal":
        return Entry(name, "palette")
    if ext == "trn":
        return Entry(name, "trn")
    if ext == "pcx":
        return Entry(name, "ui_image")
    if base in TILESETS and ext in ("cel", "min", "til", "sol"):
        if ext != "cel":
            return Skip(name, f"part of tileset {base}")
        missing = [e for e in ("min", "til", "sol") if f"{base}.{e}" not in names]
        if missing:
            return Skip(name, "tileset is missing " + ", ".join(missing))
        palette, alternatives = choose_palette(TILESETS[base].palette_preference, folder, names)
        return Entry(name, "tileset", palette, alternatives, tileset=base)
    if ext == "dun":
        owner = DUN_OWNERS.get(folder)
        if owner is None:
            return Skip(name, "layout directory has no known tileset")
        palette, alternatives = choose_palette(TILESETS[owner].palette_preference, folder, names)
        return Entry(name, "layout", palette, alternatives, tileset=owner)
    if ext in ("cel", "cl2"):
        kind = next((k for prefix, k in SPRITE_PREFIXES if name.startswith(prefix)), "unknown_graphic")
        palette, alternatives = DEFAULT_PALETTE, ()
        owner = DUN_OWNERS.get(folder)
        if kind == "level_sprite" and owner is not None:
            palette, alternatives = choose_palette(TILESETS[owner].palette_preference, folder, names)
        hint = widths.get(name)
        if isinstance(hint, list):
            hint = tuple(hint)
        return Entry(name, kind, palette, alternatives, width_hint=hint, variants=tuple(variants.get(name, ())))
    return Skip(name, "not graphics")


def build_catalog(names: Iterable[str], widths: Mapping, variants: Mapping) -> tuple[list[Entry], list[Skip]]:
    name_set = set(names)
    entries: list[Entry] = []
    skips: list[Skip] = []
    for name in sorted(name_set):
        result = classify(name, name_set, widths, variants)
        (entries if isinstance(result, Entry) else skips).append(result)
    return entries, skips
