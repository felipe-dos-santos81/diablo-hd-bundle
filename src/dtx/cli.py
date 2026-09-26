from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dtx", description="Export Diablo and Hellfire graphics for HD regeneration."
    )
    sub = parser.add_subparsers(dest="command")
    parser._dtx_subparsers = sub  # type: ignore[attr-defined]

    refdata = sub.add_parser("refdata", help="reference data (listfile, widths)")
    refdata_sub = refdata.add_subparsers(dest="refdata_command", required=True)
    rb = refdata_sub.add_parser("build", help="regenerate src/dtx/data from a DevilutionX checkout")
    rb.add_argument("--devilutionx", type=Path, required=True)
    rb.add_argument("--game", type=Path, required=True)
    rb.add_argument("--community", type=Path)
    rb.set_defaults(func=_refdata_build)

    ex = sub.add_parser("extract", help="export all graphics")
    ex.add_argument("--game", type=Path, required=True)
    ex.add_argument("--out", type=Path, required=True)
    ex.add_argument("--only", help="comma-separated kinds to export")
    ex.add_argument("--verify", action="store_true", help="reload every index PNG and compare")
    ex.add_argument("--force", action="store_true", help="re-export files that are unchanged")
    ex.add_argument("--jobs", type=int, default=None, help="worker processes (default: CPUs - 1)")
    ex.set_defaults(func=_extract)
    return parser


def _refdata_build(args) -> int:
    from dtx.mpq import ArchiveStack
    from dtx.refdata import build, listfile_path

    with ArchiveStack.open_game(args.game) as stack:
        summary = build(args.devilutionx, stack, community=args.community)
    print(f"{summary['present']} of {summary['candidates']} candidate names exist in the archives")
    with ArchiveStack.open_game(args.game, listfile_path()) as stack:
        named, unnamed = stack.names()
        for archive in stack.archives:
            total = len(archive.names())
            missing = len(unnamed[archive.name])
            print(f"{archive.name}: {total - missing} named, {missing} unnamed")
    return 0


def _extract(args) -> int:
    from dtx.catalog import KINDS
    from dtx.extract import default_jobs, run_extract

    only = None
    if args.only:
        only = {k.strip() for k in args.only.split(",") if k.strip()}
        unknown = only - set(KINDS)
        if unknown:
            print(f"unknown kinds: {', '.join(sorted(unknown))}; valid: {', '.join(KINDS)}")
            return 2
    report = run_extract(args.game, args.out, only=only, verify=args.verify, force=args.force,
                         jobs=args.jobs or default_jobs())
    s = report["summary"]
    print(f"exported {s['exported']}, unchanged {s['unchanged']}, skipped {s['skipped']}, "
          f"failed {s['failed']}, unnamed {s['unnamed']} -> {args.out / 'report.json'}")
    return 1 if s["failed"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return int(args.func(args))
