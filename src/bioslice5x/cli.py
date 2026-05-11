"""Command-line entry point — thin shim over the library API.

Every verb maps 1:1 to a public Slicer method or library function. See
ARCHITECTURE.md §8.2. The CLI exists for reproducibility and non-Python
users; the library is the product.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from bioslice5x import __version__, load_mesh, load_profile, load_recipe
from bioslice5x.errors import BioSlice5XError, CellViabilityError
from bioslice5x.slicer import Slicer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bioslice5x",
        description="Open-source 5-axis slicer for syringe-based bioprinting.",
    )
    parser.add_argument("--version", action="version", version=f"bioslice5x {__version__}")
    sub = parser.add_subparsers(dest="command")

    slice_p = sub.add_parser("slice", help="Slice a mesh into G-code.")
    slice_p.add_argument("mesh", help="Input mesh (STL/OBJ).")
    slice_p.add_argument("--profile", required=True, help="Machine profile name or YAML path.")
    slice_p.add_argument("--recipe", required=True, help="Recipe YAML path.")
    slice_p.add_argument("-o", "--output", required=True, help="Output G-code path.")
    slice_p.add_argument(
        "--force",
        action="store_true",
        help="Emit G-code even on cell-viability violation (tagged in header).",
    )

    dry_p = sub.add_parser(
        "dry-run",
        help="Emit only the first N moves for hardware commissioning (sign verification).",
    )
    dry_p.add_argument("mesh", help="Input mesh (STL/OBJ).")
    dry_p.add_argument("--profile", required=True, help="Machine profile name or YAML path.")
    dry_p.add_argument("--recipe", required=True, help="Recipe YAML path.")
    dry_p.add_argument("-o", "--output", required=True, help="Output G-code path.")
    dry_p.add_argument(
        "--moves",
        type=int,
        default=20,
        help="Number of moves to emit (default: 20).",
    )

    return parser


def _run_slice(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    recipe = load_recipe(args.recipe)
    mesh = load_mesh(args.mesh)
    try:
        result = Slicer(profile=profile, recipe=recipe).slice(mesh, force=args.force)
    except CellViabilityError as exc:
        print(f"bioslice5x: cell-viability violation — {exc}", file=sys.stderr)
        print(
            "bioslice5x: re-run with --force to emit a tagged G-code anyway (development only).",
            file=sys.stderr,
        )
        return 3
    result.write_gcode(args.output)
    print(
        f"bioslice5x: wrote {args.output} ({len(result.moves)} moves, "
        f"max wall shear {result.stress_report.max_observed_pa():.1f} Pa)"
    )
    return 0


def _run_dry_run(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    recipe = load_recipe(args.recipe)
    mesh = load_mesh(args.mesh)
    try:
        result = Slicer(profile=profile, recipe=recipe).slice(mesh)
    except CellViabilityError as exc:
        print(f"bioslice5x: cell-viability violation — {exc}", file=sys.stderr)
        return 3
    dry_gcode = result.dry_run(n_moves=args.moves)
    Path(args.output).write_text(dry_gcode, encoding="utf-8")
    print(f"bioslice5x: wrote dry-run file {args.output} ({args.moves} moves)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "slice":
            return _run_slice(args)
        if args.command == "dry-run":
            return _run_dry_run(args)
    except BioSlice5XError as exc:
        print(f"bioslice5x: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
