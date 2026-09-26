from dtx.catalog import Entry, Skip, build_catalog, classify

NAMES = {
    "levels\\towndata\\town.pal", "levels\\l1data\\l1_1.pal", "levels\\l1data\\l1_2.pal",
    "levels\\l1data\\l1.cel", "levels\\l1data\\l1.min", "levels\\l1data\\l1.til", "levels\\l1data\\l1.sol",
    "levels\\l1data\\skngdo.dun", "levels\\l1data\\l1s.cel", "levels\\l2data\\l2.cel",
    "monsters\\zombie\\zombien.cl2", "ui_art\\title.pcx", "monsters\\zombie\\bluered.trn",
    "sfx\\misc\\walk1.wav", "weird\\thing.cel", "arena\\church.dun", "data\\inv\\objcurs.cel",
}
WIDTHS = {"monsters\\zombie\\zombien.cl2": 128, "data\\inv\\objcurs.cel": [33, 32]}
VARIANTS = {"monsters\\zombie\\zombien.cl2": ["monsters\\zombie\\bluered.trn"]}


def c(name):
    return classify(name, NAMES, WIDTHS, VARIANTS)


def test_simple_kinds():
    assert c("levels\\towndata\\town.pal").kind == "palette"
    assert c("monsters\\zombie\\bluered.trn").kind == "trn"
    assert c("ui_art\\title.pcx").kind == "ui_image"


def test_tileset_entry_and_parts():
    entry = c("levels\\l1data\\l1.cel")
    assert entry == Entry("levels\\l1data\\l1.cel", "tileset", "levels\\l1data\\l1_1.pal",
                          ("levels\\l1data\\l1_2.pal",), tileset="levels\\l1data\\l1")
    assert c("levels\\l1data\\l1.min") == Skip("levels\\l1data\\l1.min", "part of tileset levels\\l1data\\l1")


def test_tileset_missing_parts():
    skip = c("levels\\l2data\\l2.cel")
    assert isinstance(skip, Skip) and "missing min, til, sol" in skip.reason


def test_layout():
    entry = c("levels\\l1data\\skngdo.dun")
    assert entry.kind == "layout" and entry.tileset == "levels\\l1data\\l1"
    assert entry.palette == "levels\\l1data\\l1_1.pal"
    assert isinstance(c("arena\\church.dun"), Skip)


def test_sprites():
    monster = c("monsters\\zombie\\zombien.cl2")
    assert monster.kind == "monster_anim" and monster.width_hint == 128
    assert monster.palette == "levels\\towndata\\town.pal"
    assert monster.variants == ("monsters\\zombie\\bluered.trn",)
    assert c("data\\inv\\objcurs.cel").width_hint == (33, 32)
    level_sprite = c("levels\\l1data\\l1s.cel")
    assert level_sprite.kind == "level_sprite" and level_sprite.palette == "levels\\l1data\\l1_1.pal"
    assert c("weird\\thing.cel").kind == "unknown_graphic"


def test_not_graphics():
    assert c("sfx\\misc\\walk1.wav") == Skip("sfx\\misc\\walk1.wav", "not graphics")


def test_build_catalog_partitions_everything():
    entries, skips = build_catalog(NAMES, WIDTHS, VARIANTS)
    assert len(entries) + len(skips) == len(NAMES)


LEVEL_PALETTES = {
    "levels\\l1data\\l1_1.pal", "levels\\l2data\\l2_1.pal", "levels\\l3data\\l3_1.pal",
    "levels\\l4data\\l4_1.pal", "nlevels\\l5data\\l5base.pal", "nlevels\\l6data\\l6base1.pal",
}
PALETTE_NAMES = LEVEL_PALETTES | {
    "levels\\towndata\\town.pal", "gendata\\cutl1d.cel", "gendata\\cutl1d.pal",
    "objects\\l5door.cel", "objects\\chest1.cel",
}
OBJECT_PALETTES = {"objects\\l5door.cel": "nlevels\\l5data\\l5base.pal"}


def test_sibling_palette_is_the_default():
    # DevilutionX Source/interfac.cpp loads gendata\cutl1d.pal for gendata\cutl1d.cel.
    entry = classify("gendata\\cutl1d.cel", PALETTE_NAMES, {}, {}, OBJECT_PALETTES)
    assert entry.palette == "gendata\\cutl1d.pal"
    assert "gendata\\cutl1d.pal" not in entry.palette_alternatives


def test_object_palette_from_table():
    entry = classify("objects\\l5door.cel", PALETTE_NAMES, {}, {}, OBJECT_PALETTES)
    assert entry.kind == "object" and entry.palette == "nlevels\\l5data\\l5base.pal"
    assert set(entry.palette_alternatives) == (LEVEL_PALETTES | {"levels\\towndata\\town.pal"}) - {
        "nlevels\\l5data\\l5base.pal"}


def test_object_on_every_level_keeps_town_palette_with_level_alternatives():
    entry = classify("objects\\chest1.cel", PALETTE_NAMES, {}, {}, OBJECT_PALETTES)
    assert entry.palette == "levels\\towndata\\town.pal"
    assert set(entry.palette_alternatives) == LEVEL_PALETTES


def test_build_catalog_passes_object_palettes():
    entries, _ = build_catalog(PALETTE_NAMES, {}, {}, OBJECT_PALETTES)
    door = next(e for e in entries if e.path == "objects\\l5door.cel")
    assert door.palette == "nlevels\\l5data\\l5base.pal"
