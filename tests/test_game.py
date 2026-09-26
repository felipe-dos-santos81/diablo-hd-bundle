import json

import pytest

from dtx import refdata
from dtx.catalog import build_catalog
from dtx.extract import run_extract
from dtx.formats.pcx import decode_pcx
from dtx.formats.sheet import split_sheet
from dtx.formats.width import scan_frame
from dtx.handlers import Context
from dtx.mpq import ArchiveStack

pytestmark = pytest.mark.game


@pytest.fixture(scope="module")
def stack(game_dir):
    with ArchiveStack.open_game(game_dir, refdata.listfile_path()) as s:
        yield s


def test_title_is_640x480(stack):
    frame, _ = decode_pcx(stack.read("ui_art\\title.pcx")[1])
    assert (frame.width, frame.height) == (640, 480)


def test_town_palette_size(stack):
    assert len(stack.read("levels\\towndata\\town.pal")[1]) == 768


def test_tileset_geometry(stack, tmp_path):
    ctx = Context(stack, tmp_path, False)
    assert ctx.tileset("levels\\l1data\\l1").column_frames[0].height == 160
    assert ctx.tileset("levels\\towndata\\town").column_frames[0].height == 256


def test_cl2_skip_table_assumption(stack):
    """Frames with table widths must satisfy the skip-table rule (plan Task 6 assumption)."""
    widths = refdata.load_widths()
    checked = matched = 0
    for name in [n for n in widths if n.startswith("monsters\\")][:20]:
        found = stack.read(name)
        if not found:
            continue
        for group in split_sheet(found[1]):
            for raw in group:
                checked += 1
                matched += scan_frame("cl2", raw).fits(widths[name])
    assert checked > 0
    assert matched / checked >= 0.99, f"{matched}/{checked} frames satisfy the skip-table rule"


def test_listfile_coverage(stack):
    """Unnamed graphics-type entries are at most 1% (audio .wav entries are out of scope)."""
    named, unnamed = stack.names()
    unnamed_graphics = [n for names in unnamed.values() for n in names if not n.lower().endswith(".wav")]
    named_graphics = [n for n in named if not n.lower().endswith(".wav")]
    total_graphics = len(named_graphics) + len(unnamed_graphics)
    assert len(unnamed_graphics) / total_graphics <= 0.01, unnamed_graphics


def test_every_graphics_file_is_catalogued(stack):
    named, _ = stack.names()
    entries, skips = build_catalog(named, refdata.load_widths(), refdata.load_variants())
    graphics_skips = [s for s in skips if s.path.endswith((".cel", ".cl2", ".pcx")) and "part of tileset" not in s.reason]
    assert graphics_skips == []


def test_parallel_matches_serial(game_dir, tmp_path):
    only = {"palette", "trn"}
    serial = run_extract(game_dir, tmp_path / "a", only=only, jobs=1)
    parallel = run_extract(game_dir, tmp_path / "b", only=only, jobs=2)
    assert serial["summary"]["failed"] == 0
    assert parallel["summary"]["failed"] == 0
    assert serial["summary"]["exported"] == parallel["summary"]["exported"] > 0
    assets_a = json.loads((tmp_path / "a" / "manifest.json").read_text())["assets"]
    assets_b = json.loads((tmp_path / "b" / "manifest.json").read_text())["assets"]
    assert assets_a == assets_b
