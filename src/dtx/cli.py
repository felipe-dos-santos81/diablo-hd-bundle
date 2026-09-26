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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return int(args.func(args))
