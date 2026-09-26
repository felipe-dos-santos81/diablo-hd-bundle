import pytest

from dtx.mpq import ArchiveStack

pytestmark = pytest.mark.game


def test_reads_real_palette(game_dir):
    with ArchiveStack.open_game(game_dir) as stack:
        archive, data = stack.read("levels\\towndata\\town.pal")
        assert archive == "DIABDAT.MPQ"
        assert len(data) == 768
        assert stack.has("ui_art\\title.pcx")
