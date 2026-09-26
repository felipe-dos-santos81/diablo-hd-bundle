from fakes import FakeArchive

from dtx.mpq import ArchiveStack

HF = FakeArchive("hellfire.mpq", {"data\\a.cel": b"new"}, unnamed=["File00000007.wav"])
DD = FakeArchive("DIABDAT.MPQ", {"data\\a.cel": b"old", "Data/B.pcx": b"b"})


def test_read_prefers_highest_priority():
    stack = ArchiveStack([HF, DD])
    assert stack.read("DATA\\A.CEL") == ("hellfire.mpq", b"new")
    assert stack.read("data/b.pcx") == ("DIABDAT.MPQ", b"b")
    assert stack.read("missing.cel") is None


def test_versions_lists_every_archive():
    stack = ArchiveStack([HF, DD])
    assert stack.versions("data\\a.cel") == [("hellfire.mpq", b"new"), ("DIABDAT.MPQ", b"old")]


def test_names_canonical_and_unnamed():
    named, unnamed = ArchiveStack([HF, DD]).names()
    assert named == ["data\\a.cel", "data\\b.pcx"]
    assert unnamed == {"hellfire.mpq": ["File00000007.wav"], "DIABDAT.MPQ": []}
