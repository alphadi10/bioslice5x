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

    prev_p = sub.add_parser(
        "preview",
        help="Open a 3D toolpath viewer for a G-code file (ADR-004 / Phase 4).",
    )
    prev_p.add_argument("gcode", help="Input G-code file (typically produced by `slice`).")
    prev_p.add_argument(
        "--profile",
        default=None,
        help="Optional machine profile (name or YAML path) — adds the build-volume wireframe.",
    )
    prev_p.add_argument(
        "--arrow-every",
        type=int,
        default=50,
        help="Draw a tool-orientation arrow every N extrusion moves (default: 50).",
    )
    prev_p.add_argument(
        "--screenshot",
        default=None,
        help="Render to a PNG file without opening a window (headless mode).",
    )
    prev_p.add_argument(
        "--no-show",
        action="store_true",
        help="Don't open the interactive window (use with --screenshot).",
    )
    prev_p.add_argument(
        "--color-by",
        choices=("z", "shear"),
        default="z",
        help=(
            "Extrusion color scalar: 'z' colors by layer height (PrusaSlicer-style); "
            "'shear' colors by per-move wall shear stress read from the `;STRESS:` "
            "tokens the slicer emits. Falls back to 'z' if those tokens are absent."
        ),
    )
    prev_p.add_argument(
        "--stress-threshold-pa",
        type=float,
        default=None,
        help=(
            "Cell-viability stress threshold (Pa). When --color-by=shear, clamps "
            "the colormap to [0, threshold] so red marks the safety limit. "
            "If unset, the colormap auto-fits to the data range."
        ),
    )
    prev_p.add_argument(
        "--mesh",
        default=None,
        help=(
            "Optional source mesh (STL/OBJ) to render semi-transparent behind "
            "the toolpath, so the operator can compare what was printed against "
            "what was asked for. Best alignment in flat-orientation prints; "
            "5-axis tilt-prints show the mesh in part frame, offset from the "
            "machine-frame toolpath (known limitation)."
        ),
    )
    prev_p.add_argument(
        "--mesh-opacity",
        type=float,
        default=0.15,
        help="Source-mesh overlay opacity in [0, 1] (default: 0.15).",
    )

    demo_p = sub.add_parser(
        "demo",
        help=(
            "Zero-config end-to-end run: slice a bundled cube with the "
            "hypothetical_3axis profile and open the viewer with shear "
            "coloring + mesh overlay. Useful for first-run validation "
            "and for sharing screenshots with collaborators."
        ),
    )
    demo_p.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Where to put the generated mesh, recipe, and G-code "
            "(default: a temp directory). The directory is printed on "
            "completion so you can open the files manually."
        ),
    )
    demo_p.add_argument(
        "--no-viewer",
        action="store_true",
        help="Skip opening the viewer (useful for headless CI runs).",
    )
    demo_p.add_argument(
        "--screenshot",
        default=None,
        help="Render to a PNG instead of opening a window. Implies --no-viewer.",
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


def _run_preview(args: argparse.Namespace) -> int:
    from bioslice5x.visualization.preview import preview_gcode

    build_volume = None
    if args.profile is not None:
        profile = load_profile(args.profile)
        bv = profile.build_volume
        build_volume = (bv.x_mm, bv.y_mm, bv.z_mm)
    preview_gcode(
        args.gcode,
        build_volume=build_volume,
        arrow_sample_every=args.arrow_every,
        show=not args.no_show,
        screenshot=args.screenshot,
        color_by=args.color_by,
        cell_stress_threshold_pa=args.stress_threshold_pa,
        source_mesh_path=args.mesh,
        source_mesh_opacity=args.mesh_opacity,
    )
    return 0


def _run_demo(args: argparse.Namespace) -> int:
    """Zero-config end-to-end run.

    Generates a 10mm cube mesh in memory, builds a single-syringe
    collagen recipe, slices on the hypothetical_3axis profile, writes
    the result to a temp directory (or `--output-dir`), and opens the
    viewer with shear coloring + mesh overlay.

    Used for:
    - First-run validation after install: `pip install bioslice5x[viz]
      && bioslice5x demo` should produce a window in under 10 seconds.
    - Generating screenshots for sharing: `bioslice5x demo
      --screenshot demo.png` produces a single PNG.
    - Headless smoke testing in CI: `bioslice5x demo --no-viewer`.
    """
    import tempfile
    from typing import Any, cast

    import trimesh

    from bioslice5x.recipe.models import Needle, Recipe, SlicingParams, Syringe
    from bioslice5x.slicer import Slicer

    out_dir = (
        Path(args.output_dir)
        if args.output_dir
        else Path(tempfile.mkdtemp(prefix="bioslice5x_demo_"))
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Mesh in memory (matches samples/cube_10mm.stl).
    cube: Any = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    cube.apply_translation([0.0, 0.0, 5.0])
    mesh = cast(trimesh.Trimesh, cube)
    stl_path = out_dir / "demo_cube_10mm.stl"
    mesh.export(stl_path)

    # 2. Single-syringe collagen recipe (matches the quickstart).
    recipe = Recipe(
        name="bioslice5x_demo",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7, gauge_label="18G"),
            )
        ],
        slicing=SlicingParams(
            layer_height_mm=0.4,
            line_width_mm=0.5,
            print_speed_mm_per_min=60.0,
            infill_density=0.2,
        ),
    )

    # 3. Slice.
    print("bioslice5x demo: slicing 10mm cube on hypothetical_3axis…")
    profile = load_profile("hypothetical_3axis")
    result = Slicer(profile=profile, recipe=recipe).slice(mesh)
    gcode_path = out_dir / "demo.gcode"
    result.write_gcode(gcode_path)
    print(
        f"  wrote {gcode_path}\n"
        f"  {len(result.moves)} moves, "
        f"max wall shear {result.stress_report.max_observed_pa():.1f} Pa, "
        f"estimated time {result.estimated_seconds:.0f} s"
    )

    # 4. Preview (unless suppressed).
    if args.no_viewer and not args.screenshot:
        print(f"  demo files in: {out_dir}")
        return 0
    from bioslice5x.visualization.preview import preview_gcode

    bv = (profile.build_volume.x_mm, profile.build_volume.y_mm, profile.build_volume.z_mm)
    threshold = next(iter(result.stress_report.threshold_by_syringe.values()), None)
    try:
        preview_gcode(
            gcode_path,
            build_volume=bv,
            show=not (args.no_viewer or args.screenshot),
            screenshot=args.screenshot,
            color_by="shear",
            cell_stress_threshold_pa=threshold,
            source_mesh_path=stl_path,
        )
    except Exception as exc:
        print(f"bioslice5x demo: viewer unavailable ({exc})", file=sys.stderr)
        print(f"  G-code is still at: {gcode_path}", file=sys.stderr)
        return 4
    if args.screenshot:
        print(f"  wrote screenshot: {args.screenshot}")
    print(f"  demo files in: {out_dir}")
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
        if args.command == "preview":
            return _run_preview(args)
        if args.command == "demo":
            return _run_demo(args)
    except BioSlice5XError as exc:
        print(f"bioslice5x: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
