from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dtx", description="Export Diablo and Hellfire graphics for HD regeneration."
    )
    parser._dtx_subparsers = parser.add_subparsers(dest="command")  # type: ignore[attr-defined]
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return int(args.func(args))
