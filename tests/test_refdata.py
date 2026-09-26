import json

from fakes import FakeArchive
from dtx.mpq import ArchiveStack
from dtx.refdata import build


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
