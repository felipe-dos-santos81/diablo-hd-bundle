import pytest
from fakes import FakeArchive

import dtx.mpq as mpq
from dtx.mpq import ArchiveStack, StormLibError

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


def test_open_game_closes_already_opened_archives_on_failure(tmp_path, monkeypatch):
    closed = []
    construction_count = 0

    class FakeMpqArchive:
        def __init__(self, path):
            nonlocal construction_count
            construction_count += 1
            self.path = path
            self.name = path.name
            if construction_count == 3:
                raise StormLibError("boom")

        def close(self):
            closed.append(self.name)

    monkeypatch.setattr(mpq, "MpqArchive", FakeMpqArchive)

    for name in mpq.GRAPHICS_ARCHIVES:
        (tmp_path / name).write_bytes(b"")

    with pytest.raises(StormLibError):
        ArchiveStack.open_game(tmp_path)

    assert closed == ["hfmonk.mpq", "hellfire.mpq"]
