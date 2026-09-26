from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from dtx.catalog import DEFAULT_PALETTE, TILESETS, Entry, TilesetSpec
from dtx.export import write_frame_pair, write_json, write_sheet, write_swatch
from dtx.formats.frame import Frame
from dtx.formats.levelcel import TileType, decode_level_cell
from dtx.formats.pal import cycling_for, decode_pal
from dtx.formats.pcx import decode_pcx
from dtx.formats.render import compose, place_pieces, tile_pieces
from dtx.formats.sheet import read_sheet, split_sheet
from dtx.formats.tileset import (
    CellRef, cell_types, cell_users, compose_column, parse_dun, parse_min, parse_sol, parse_til,
)
from dtx.formats.trn import decode_trn
from dtx.formats.width import resolve_widths, scan_frame
from dtx.paths import extension, rel_path
from dtx.verify import verify_written

PALETTE_WARNING = "most pixels use level-specific palette indices 1-127; town.pal is probably wrong"
RECORD_NAMES = {"trn": "trn.json", "tileset": "tileset.json", "layout": "layout.json"}


class VerificationError(ValueError):
    pass


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def record_name(kind: str) -> str | None:
    if kind == "palette":
        return None
    return RECORD_NAMES.get(kind, "meta.json")


def source(archive: str, name: str, data: bytes) -> dict:
    return {"archive": archive, "path": name, "sha1": sha1(data)}


class Context:
    def __init__(self, stack, out: Path, verify: bool, exporter: str | None = None):
        self.stack = stack
        self.out = Path(out)
        self.verify = verify
        self.exporter = exporter
        self._palettes: dict[str, np.ndarray] = {}
        self._tilesets: dict = {}

    def palette(self, name: str | None) -> np.ndarray:
        if name is None:
            raise ValueError("no palette available for this asset")
        if name not in self._palettes:
            found = self.stack.read(name)
            if found is None:
                raise ValueError(f"palette {name} not found in any archive")
            self._palettes[name] = decode_pal(found[1])
        return self._palettes[name]

    def stamp(self) -> dict:
        """Provenance stored in every record: the exporter fingerprint and whether --verify ran."""
        return {"exporter": self.exporter, "verified": self.verify}

    def tileset(self, key: str) -> "TilesetData":
        if key not in self._tilesets:
            self._tilesets[key] = load_tileset(self, key)
        return self._tilesets[key]


def write_checked(ctx: Context, frame: Frame, palette: np.ndarray, directory: Path, stem: str) -> dict:
    record = write_frame_pair(frame, palette, directory, stem)
    if ctx.verify and not record.get("empty"):
        if not verify_written(frame, directory / record["idx"]):
            raise VerificationError(f"{directory / record['idx']} does not round-trip")
    return record


def export_palette(ctx: Context, entry: Entry, archive: str, data: bytes, dest: Path) -> dict:
    palette = decode_pal(data)
    write_swatch(palette, dest.parent / (dest.name + ".png"))
    write_json(dest.parent / (dest.name + ".json"), {
        "source": source(archive, entry.path, data),
        "colors": palette.tolist(),
        "cycling": cycling_for(entry.path),
        **ctx.stamp(),
    })
    return {}


def export_trn(ctx: Context, entry: Entry, archive: str, data: bytes, dest: Path) -> dict:
    write_json(dest / "trn.json", {"source": source(archive, entry.path, data), "map": decode_trn(data).tolist(),
                                   **ctx.stamp()})
    return {}


def export_image(ctx: Context, entry: Entry, archive: str, data: bytes, dest: Path) -> dict:
    frame, palette = decode_pcx(data)
    record = write_checked(ctx, frame, palette, dest, "image")
    write_json(dest / "meta.json", {
        "source": source(archive, entry.path, data),
        "format": "pcx",
        "kind": entry.kind,
        "palette": "embedded",
        "embedded_palette": palette.tolist(),
        "palette_alternatives": [rel_path(p) for p in entry.palette_alternatives],
        "variants": [{"trn": rel_path(t)} for t in entry.variants],
        "width_source": "header",
        "groups": 1,
        "group_label": None,
        "frames": [{"group": 0, "i": 0, **record}],
        **ctx.stamp(),
    })
    return {"frames": 1}


def level_index_share(frames: list[Frame]) -> float:
    """Fraction of opaque pixels whose palette index is 1-127 (the level-specific range)."""
    opaque = level = 0
    for frame in frames:
        values = frame.indices[frame.opaque]
        opaque += values.size
        level += int(np.count_nonzero((values >= 1) & (values <= 127)))
    return level / opaque if opaque else 0.0


def export_sprite(ctx: Context, entry: Entry, archive: str, data: bytes, dest: Path) -> dict:
    fmt = extension(entry.path)
    palette = ctx.palette(entry.palette)
    split = read_sheet(data)
    groups = split.groups
    flat = [(g, i, raw) for g, frames in enumerate(groups) for i, raw in enumerate(frames)]
    scans = [scan_frame(fmt, raw) for _, _, raw in flat]
    widths = resolve_widths(scans, entry.width_hint)

    decoded: list[list[Frame]] = [[] for _ in groups]
    records = []
    for (g, i, _), scan, width in zip(flat, scans, widths.widths):
        frame = scan.to_frame(width)
        decoded[g].append(frame)
        record = write_checked(ctx, frame, palette, dest / f"d{g}", f"f{i:03d}")
        if "png" in record:
            record["png"] = f"d{g}/{record['png']}"
            record["idx"] = f"d{g}/{record['idx']}"
        records.append({"group": g, "i": i, **record})
    has_sheet = write_sheet(decoded, palette, dest / "sheet.png")

    meta = {
        "source": source(archive, entry.path, data),
        "format": fmt,
        "kind": entry.kind,
        "palette": rel_path(entry.palette),
        "palette_alternatives": [rel_path(p) for p in entry.palette_alternatives],
        "variants": [{"trn": rel_path(t)} for t in entry.variants],
        "width_source": widths.source,
        "groups": len(groups),
        "group_label": "direction" if len(groups) == 8 else ("group" if len(groups) > 1 else None),
        "sheet": "sheet.png" if has_sheet else None,
        "frames": records,
        **ctx.stamp(),
    }
    if widths.candidates:
        meta["width_candidates"] = list(widths.candidates)
    if widths.skip_table_mismatch:
        meta["skip_table_mismatch"] = True
    if split.recovery:
        meta["sheet_recovery"] = split.recovery
    if entry.palette == DEFAULT_PALETTE and level_index_share([f for g in decoded for f in g]) > 0.5:
        meta["palette_warning"] = PALETTE_WARNING
    write_json(dest / "meta.json", meta)
    return {"frames": len(records), "width_source": widths.source}


@dataclass
class TilesetData:
    spec: TilesetSpec
    columns: list[list[CellRef]]
    til: list[tuple[int, int, int, int]]
    sol: list[dict[str, bool]]
    cells: dict[int, Frame]
    column_frames: list[Frame]
    unreferenced: list[int]
    sources: dict[str, str]
    archive: str

    @property
    def column_height(self) -> int:
        return self.spec.cells_per_column // 2 * 32


def load_tileset(ctx: Context, key: str) -> TilesetData:
    spec = TILESETS[key]
    parts: dict[str, tuple[str, bytes]] = {}
    for ext in ("cel", "min", "til", "sol"):
        found = ctx.stack.read(f"{key}.{ext}")
        if found is None:
            raise ValueError(f"tileset part {key}.{ext} not found")
        parts[ext] = found
    columns = parse_min(parts["min"][1], spec.cells_per_column)
    types = cell_types(columns)
    raw_cells = split_sheet(parts["cel"][1])[0]
    cells: dict[int, Frame] = {}
    for frame_no, tile_type in sorted(types.items()):
        if frame_no > len(raw_cells):
            raise ValueError(f"MIN references cell {frame_no} but the CEL has {len(raw_cells)} frames")
        cells[frame_no] = decode_level_cell(raw_cells[frame_no - 1], TileType(tile_type))
    return TilesetData(
        spec=spec,
        columns=columns,
        til=parse_til(parts["til"][1]),
        sol=parse_sol(parts["sol"][1]),
        cells=cells,
        column_frames=[compose_column(c, cells) for c in columns],
        unreferenced=[f for f in range(1, len(raw_cells) + 1) if f not in cells],
        sources={ext: f"{key}.{ext}" for ext in parts},
        archive=parts["cel"][0],
    )


def export_tileset(ctx: Context, entry: Entry, archive: str, data: bytes, dest: Path) -> dict:
    ts = ctx.tileset(entry.tileset)
    palette = ctx.palette(entry.palette)
    column_records = []
    for i, frame in enumerate(ts.column_frames):
        record = write_checked(ctx, frame, palette, dest / "columns", f"m{i:04d}")
        column_records.append({
            "id": i,
            "png": f"columns/{record['png']}" if "png" in record else None,
            "idx": f"columns/{record['idx']}" if "idx" in record else None,
            "cells": [{"slot": s, "frame": r.frame, "draw_type": r.tile_type} for s, r in enumerate(ts.columns[i])],
            "sol": ts.sol[i] if i < len(ts.sol) else None,
        })
    for frame_no, frame in ts.cells.items():
        write_checked(ctx, frame, palette, dest / "cells", f"c{frame_no:04d}")

    tile_frames = []
    tile_records = []
    for t in range(len(ts.til)):
        placements, size = place_pieces(tile_pieces(np.array([[t]]), ts.til), ts.column_height)
        image = compose(placements, size, ts.column_frames)
        tile_frames.append(image)
        record = write_checked(ctx, image, palette, dest / "tiles", f"t{t:04d}")
        tile_records.append({"id": t, "columns": list(ts.til[t]),
                             "png": f"tiles/{record['png']}" if "png" in record else None})
    write_sheet([tile_frames[r : r + 16] for r in range(0, len(tile_frames), 16)], palette, dest / "sheet.png")

    write_json(dest / "tileset.json", {
        "source": {**ts.sources, "archive": ts.archive, "path": entry.path, "sha1": sha1(data)},
        "palette": rel_path(entry.palette),
        "palette_alternatives": [rel_path(p) for p in entry.palette_alternatives],
        "cells_per_column": ts.spec.cells_per_column,
        "column_size_px": [64, ts.column_height],
        "columns": column_records,
        "tiles": tile_records,
        "cell_users": {str(k): v for k, v in sorted(cell_users(ts.columns).items())},
        "unreferenced_cells": ts.unreferenced,
        **ctx.stamp(),
    })
    return {"columns": len(column_records), "tiles": len(tile_records)}


def export_layout(ctx: Context, entry: Entry, archive: str, data: bytes, dest: Path) -> dict:
    dun = parse_dun(data)
    ts = ctx.tileset(entry.tileset)
    pieces = tile_pieces(dun.tiles.astype(np.int32) - 1, ts.til)
    placements, size = place_pieces(pieces, ts.column_height)
    image = compose(placements, size, ts.column_frames)
    record = write_checked(ctx, image, ctx.palette(entry.palette), dest, "layout")
    write_json(dest / "layout.json", {
        "source": source(archive, entry.path, data),
        "tileset": rel_path(entry.tileset),
        "palette": rel_path(entry.palette),
        "palette_alternatives": [rel_path(p) for p in entry.palette_alternatives],
        "size_tiles": [dun.width, dun.height],
        "size_px": [size[0], size[1]],
        "column_height_px": ts.column_height,
        "image": record,
        "placements": [{"column": p.column, "x": p.x, "y": p.y} for p in placements],
        **ctx.stamp(),
    })
    return {"placements": len(placements)}
