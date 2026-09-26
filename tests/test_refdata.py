import json

from fakes import FakeArchive
from dtx.mpq import ArchiveStack
from dtx.refdata import build, table_widths


def tsv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n")


def fake_devilutionx(root):
    src = root / "Source"
    src.mkdir(parents=True)
    (src / "a.cpp").write_text(
        r'LoadCel("data\\pentspin", 48); LoadFileInMem("levels\\l1data\\skngdo.dun");'
        '\n' r'BufCopy(x, R"(nlevels\l6data\l6base)", rv, ".pal");'
    )
    txt = root / "assets" / "txtdata"
    tsv(txt / "monsters" / "monstdat.tsv",
        ["_monster_id", "name", "assetsSuffix", "soundSuffix", "trnFile", "availability", "width"],
        [["MT_BZOMBIE", "Ghoul", "zombie\\zombie", "", "zombie\\bluered", "Always", "128"]])
    tsv(txt / "monsters" / "unique_monstdat.tsv", ["name", "mTrnName"], [["Gharbad", "general"]])
    tsv(txt / "missiles" / "missile_sprites.tsv", ["id", "width", "width2", "name", "numFrames"],
        [["Arrow", "96", "16", "arrows", "1"], ["Fireball", "96", "16", "fireba", "2"]])
    tsv(txt / "objects" / "objdat.tsv", ["id", "file", "animWidth"], [["OBJ_L1LIGHT", "l1braz", "64"]])
    sprites = txt / "classes" / "warrior" / "sprites.tsv"
    tsv(sprites, ["Variable", "Value"], [
        ["classPath", "warrior"], ["classChar", "w"], ["trn", "warrior"], ["stand", "96"], ["walk", "96"],
        ["attack", "128"], ["bow", "96"], ["swHit", "96"], ["block", "96"], ["lightning", "96"],
        ["fire", "96"], ["magic", "96"], ["death", "128"]])
    inv = root / "assets" / "data" / "inv"
    inv.mkdir(parents=True)
    (inv / "objcurs-widths.txt").write_text("33\n32\n")


PRESENT = {
    "monsters\\zombie\\zombien.cl2": b"", "monsters\\zombie\\bluered.trn": b"",
    "monsters\\monsters\\general.trn": b"", "data\\pentspin.cel": b"",
    "levels\\l1data\\skngdo.dun": b"", "nlevels\\l6data\\l6base.pal": b"",
    "plrgfx\\warrior\\wlb\\wlbat.cl2": b"", "plrgfx\\warrior\\wln\\wlnst.cl2": b"",
    "missiles\\arrows.cl2": b"", "missiles\\fireba2.cl2": b"", "objects\\l1braz.cel": b"",
    "data\\inv\\objcurs.cel": b"", "levels\\l1data\\l1.min": b"", "extra\\community.cel": b"",
}


def test_build(tmp_path):
    dvx = tmp_path / "dvx"
    fake_devilutionx(dvx)
    community = tmp_path / "community.txt"
    community.write_text("EXTRA\\COMMUNITY.CEL\nnot\\present.cel\n")
    stack = ArchiveStack([FakeArchive("DIABDAT.MPQ", PRESENT)])
    out = tmp_path / "data"

    summary = build(dvx, stack, out, community)

    listed = (out / "listfile.txt").read_text().split()
    assert listed == sorted(PRESENT)
    assert summary["present"] == len(PRESENT)
    widths = json.loads((out / "widths.json").read_text())
    assert widths["monsters\\zombie\\zombien.cl2"] == 128
    assert widths["plrgfx\\warrior\\wln\\wlnst.cl2"] == 96
    assert widths["plrgfx\\warrior\\wlb\\wlbat.cl2"] == 96  # bow attack uses the bow width
    assert widths["missiles\\fireba2.cl2"] == 96
    assert widths["objects\\l1braz.cel"] == 64
    assert widths["data\\inv\\objcurs.cel"] == [33, 32]
    assert widths["data\\pentspin.cel"] == 48
    assert "monsters\\zombie\\zombiew.cl2" not in widths  # absent from archives
    variants = json.loads((out / "variants.json").read_text())
    assert variants == {"monsters\\zombie\\zombien.cl2": ["monsters\\zombie\\bluered.trn"]}


def test_object_width_ignores_non_positive_duplicate(tmp_path):
    # Real objdat.tsv reuses one file (e.g. l1braz) across several object ids: only one row
    # carries the real animWidth and the rest are 0 (candles, skull sticks, ...). The first
    # positive width seen for a path must win and a later 0 must never overwrite it.
    dvx = tmp_path / "dvx"
    txt = dvx / "assets" / "txtdata"
    tsv(txt / "monsters" / "monstdat.tsv",
        ["_monster_id", "name", "assetsSuffix", "soundSuffix", "trnFile", "availability", "width"], [])
    tsv(txt / "monsters" / "unique_monstdat.tsv", ["name", "mTrnName"], [])
    tsv(txt / "missiles" / "missile_sprites.tsv", ["id", "width", "width2", "name", "numFrames"], [])
    tsv(txt / "objects" / "objdat.tsv", ["id", "file", "animWidth"],
        [["OBJ_L1LIGHT", "l1braz", "64"], ["OBJ_L1CANDLE", "l1braz", "0"]])

    widths, _variants, _names = table_widths(dvx)

    assert widths["objects\\l1braz.cel"] == 64
    assert all(isinstance(v, list) or v > 0 for v in widths.values())


def test_reads_hellfire_mod_tables(tmp_path):
    # At the pinned commit Hellfire-only monsters, missiles and the objcurs2 cursor widths live
    # under mods/hf/ rather than assets/; without them hellfire.mpq sprites fall back to inference.
    dvx = tmp_path / "dvx"
    fake_devilutionx(dvx)
    hf = dvx / "mods" / "hf"
    tsv(hf / "txtdata" / "monsters" / "monstdat.tsv",
        ["_monster_id", "name", "assetsSuffix", "soundSuffix", "trnFile", "availability", "width"],
        [["MT_BZOMBIE", "Ghoul", "zombie\\zombie", "", "zombie\\bluered", "Always", "128"],
         ["MT_HELLBAT", "Hell Bat", "hellbat\\helbat", "", "", "Always", "96"]])
    tsv(hf / "txtdata" / "missiles" / "missile_sprites.tsv", ["id", "width", "width2", "name", "numFrames"],
        [["OrangeFlare", "96", "8", "ms_ora", "2"]])
    inv = hf / "data" / "inv"
    inv.mkdir(parents=True)
    (inv / "objcurs2-widths.txt").write_text("28\n56\n")

    widths, variants, _names = table_widths(dvx)

    assert widths["monsters\\hellbat\\helbata.cl2"] == 96
    assert widths["monsters\\zombie\\zombiea.cl2"] == 128
    assert variants["monsters\\zombie\\zombiea.cl2"] == ["monsters\\zombie\\bluered.trn"]  # not duplicated
    assert widths["missiles\\ms_ora1.cl2"] == 96
    assert widths["data\\inv\\objcurs2.cel"] == [28, 56]
    assert widths["data\\inv\\objcurs.cel"] == [33, 32]
