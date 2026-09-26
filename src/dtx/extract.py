from __future__ import annotations

import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from dtx import refdata
from dtx.catalog import SPRITE_KINDS, Entry, build_catalog
from dtx.export import write_json
from dtx.handlers import (
    Context, export_image, export_layout, export_palette, export_sprite, export_tileset, export_trn,
    record_name, sha1,
)
from dtx.mpq import ArchiveStack
from dtx.paths import rel_path

HD_CONTRACT = {
    "scale": "integer k >= 1, chosen once per asset",
    "rule": "a replacement for a frame, cell or column must be exactly (w*k, h*k) of the original; "
            "all offsets, anchors and placements scale by the same k",
    "units": ["frame", "cell", "column"],
    "fidelity": "exported *.idx.png files hold the exact original palette indices (L) and opacity (A)",
}
HANDLERS = {
    "palette": export_palette, "trn": export_trn, "ui_image": export_image,
    "tileset": export_tileset, "layout": export_layout,
    **{kind: export_sprite for kind in SPRITE_KINDS},
}
SINGLE_VERSION_KINDS = {"tileset", "layout"}


def destination(out: Path, entry: Entry, archive_prefix: str | None = None) -> Path:
    root = out / ("palettes" if entry.kind == "palette" else "assets")
    if archive_prefix:
        root = root / f"@{archive_prefix}"
    name = entry.tileset if entry.kind == "tileset" else entry.path
    return root / rel_path(name)


def record_path(entry: Entry, dest: Path) -> Path:
    name = record_name(entry.kind)
    return dest.parent / (dest.name + ".json") if name is None else dest / name


def _recorded_sha1(path: Path) -> str | None:
    try:
        return json.loads(path.read_text())["source"]["sha1"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def process_entry(ctx: Context, entry: Entry, force: bool) -> list[dict]:
    versions = ctx.stack.versions(entry.path)
    if not versions:
        return [{"status": "failed", "path": entry.path, "kind": entry.kind, "error": "not found in any archive"}]
    results = []
    seen: set[str] = set()
    for n, (archive, data) in enumerate(versions):
        digest = sha1(data)
        if digest in seen:
            continue
        seen.add(digest)
        base = {"path": entry.path, "archive": archive, "kind": entry.kind}
        if n > 0 and entry.kind in SINGLE_VERSION_KINDS:
            results.append({**base, "status": "skipped",
                            "reason": "overridden tileset/layout versions are not exported"})
            continue
        dest = destination(ctx.out, entry, archive if n > 0 else None)
        record = record_path(entry, dest)
        rel_record = record.relative_to(ctx.out).as_posix()
        if not force and _recorded_sha1(record) == digest:
            results.append({**base, "status": "unchanged", "sha1": digest, "record": rel_record})
            continue
        try:
            info = HANDLERS[entry.kind](ctx, entry, archive, data, dest)
        except Exception as exc:  # per-file isolation: one bad file never stops the export
            results.append({**base, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            continue
        results.append({**base, "status": "exported", "sha1": digest, "record": rel_record, **info})
    return results


def _previous_assets(out: Path) -> list[dict]:
    try:
        assets = json.loads((out / "manifest.json").read_text())["assets"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return assets if isinstance(assets, list) else []


def report_name(only) -> str:
    return "report-only.json" if only else "report.json"


def _finish(out: Path, results: list[dict], skips: list, unnamed: dict, only=None) -> dict:
    """Write the run report and the manifest. An --only run writes report-only.json (keeping the
    full run's report.json) and replaces only its own kinds in the existing manifest."""
    by_status: dict[str, list[dict]] = {"exported": [], "unchanged": [], "skipped": [], "failed": []}
    for r in results:
        by_status[r["status"]].append(r)
    skipped = [asdict(s) for s in skips] + [
        {"path": r["path"], "archive": r["archive"], "reason": r["reason"]} for r in by_status["skipped"]
    ]
    report = {
        "summary": {
            "exported": len(by_status["exported"]),
            "unchanged": len(by_status["unchanged"]),
            "skipped": len(skipped),
            "failed": len(by_status["failed"]),
            "unnamed": sum(len(v) for v in unnamed.values()),
            "by_kind": dict(Counter(r["kind"] for r in by_status["exported"] + by_status["unchanged"])),
        },
        "exported": by_status["exported"],
        "unchanged": by_status["unchanged"],
        "skipped": skipped,
        "failed": by_status["failed"],
        "unnamed": unnamed,
    }
    assets = [{k: r[k] for k in ("path", "kind", "archive", "sha1", "record")}
              for r in by_status["exported"] + by_status["unchanged"]]
    if only:
        assets += [a for a in _previous_assets(out) if a.get("kind") not in only]
    manifest = {
        "version": 1,
        "hd_contract": HD_CONTRACT,
        "devilutionx_reference": refdata.PINNED_DEVILUTIONX,
        "assets": sorted(assets, key=lambda a: (a["path"], a["archive"])),
    }
    write_json(out / report_name(only), report)
    write_json(out / "manifest.json", manifest)
    return report


def _catalog(stack, only, widths, variants, palettes):
    names, unnamed = stack.names()
    entries, skips = build_catalog(names, widths, variants, palettes)
    if only:
        entries = [e for e in entries if e.kind in only]
    return entries, skips, unnamed


def extract_with(stack, out: Path, *, only=None, verify=False, force=False, widths=None, variants=None,
                 palettes=None) -> dict:
    out = Path(out)
    widths = refdata.load_widths() if widths is None else widths
    variants = refdata.load_variants() if variants is None else variants
    palettes = refdata.load_palettes() if palettes is None else palettes
    entries, skips, unnamed = _catalog(stack, only, widths, variants, palettes)
    ctx = Context(stack, out, verify)
    results = [r for e in entries for r in process_entry(ctx, e, force)]
    return _finish(out, results, skips, unnamed, only)


_WORKER: Context | None = None


def _init_worker(game_dir: str, out: str, verify: bool) -> None:
    global _WORKER
    _WORKER = Context(ArchiveStack.open_game(Path(game_dir), refdata.listfile_path()), Path(out), verify)


def _work(entry: Entry, force: bool) -> list[dict]:
    assert _WORKER is not None
    return process_entry(_WORKER, entry, force)


def run_extract(game_dir: Path, out: Path, *, only=None, verify=False, force=False, jobs=1) -> dict:
    out = Path(out)
    with ArchiveStack.open_game(game_dir, refdata.listfile_path()) as stack:
        if jobs <= 1:
            return extract_with(stack, out, only=only, verify=verify, force=force)
        entries, skips, unnamed = _catalog(stack, only, refdata.load_widths(), refdata.load_variants(),
                                           refdata.load_palettes())
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=jobs, initializer=_init_worker,
                             initargs=(str(game_dir), str(out), verify)) as pool:
        futures = [pool.submit(_work, e, force) for e in entries]
        for done, future in enumerate(as_completed(futures), 1):
            results.extend(future.result())
            if done % 250 == 0 or done == len(futures):
                print(f"{done}/{len(futures)} files processed", flush=True)
    return _finish(out, results, skips, unnamed, only)


def default_jobs() -> int:
    return max(1, (os.cpu_count() or 2) - 1)
