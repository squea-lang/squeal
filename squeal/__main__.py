"""CLI squeal (в духе gleam): подкоманды; в первой сборке — только build."""

from __future__ import annotations

import argparse
import sys

from .compiler import build
from .errors import SquealError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m squeal")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="compile the src/ tree into build/dev/erlang")
    b.add_argument("dir", nargs="?", default=".", help="project root (default: .)")
    args = parser.parse_args(argv)

    if args.command == "build":
        try:
            build(args.dir)
            return 0
        except SquealError as e:
            print(f"squeal: {e}", file=sys.stderr)
            return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
