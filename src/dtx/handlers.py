from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from dtx.catalog import Entry
from dtx.export import write_frame_pair, write_json, write_sheet, write_swatch
from dtx.formats.frame import Frame
from dtx.formats.pal import cycling_for, decode_pal
from dtx.formats.pcx import decode_pcx
from dtx.formats.sheet import split_sheet
from dtx.formats.trn import decode_trn
from dtx.formats.width import resolve_widths, scan_frame
from dtx.paths import extension, rel_path
from dtx.verify import verify_written

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
    def __init__(self, stack, out: Path, verify: bool):
        self.stack = stack
        self.out = Path(out)
        self.verify = verify
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
    })
    return {}


def export_trn(ctx: Context, entry: Entry, archive: str, data: bytes, dest: Path) -> dict:
    write_json(dest / "trn.json", {"source": source(archive, entry.path, data), "map": decode_trn(data).tolist()})
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
    })
    return {"frames": 1}


def export_sprite(ctx: Context, entry: Entry, archive: str, data: bytes, dest: Path) -> dict:
    fmt = extension(entry.path)
    palette = ctx.palette(entry.palette)
    groups = split_sheet(data)
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
    }
    if widths.candidates:
        meta["width_candidates"] = list(widths.candidates)
    write_json(dest / "meta.json", meta)
    return {"frames": len(records), "width_source": widths.source}
