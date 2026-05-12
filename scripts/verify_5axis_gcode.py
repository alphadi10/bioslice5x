#!/usr/bin/env python3
"""Verify the precision and correctness of 5-axis G-code emitted by
the conformal wrap-around-axis slicer.

Checks performed (in order):

  1. Every extrusion G1 line carries both an A token and a C token
     (the 5-axis emission contract per docs/OPEN5X_NOTES.md §4).
  2. All numeric tokens are finite (no NaN / Inf leaked through).
  3. A values stay constant within a single axial layer when
     wrap_axis="z" (tilt is fixed; only swivel sweeps). A check that
     catches kinematic-chain bugs that would otherwise produce
     "twitch" motion.
  4. C values sweep smoothly within each axial layer — the rotation
     covers the requested arc, with no large gaps (default tolerance:
     ≥ 300° of span for a 360° arc, given some boundary discretization).
  5. Distinct axial Z values correspond to layers separated by
     `--layer-height-mm` ± 5%.
  6. The layer count matches the mesh's axial extent / layer-height
     within ±1 (boundary rounding).
  7. The C token rounds to at most `--max-decimals` (default 4) decimal
     places. The postprocessor truncates trailing zeros, so 4 is the
     ceiling the emitter targets.

Exits 0 on PASS, 1 on FAIL. Prints a structured report to stdout in
either case so CI logs are useful even when something is wrong.

Usage:
    scripts/verify_5axis_gcode.py out.gcode \\
        --wrap-axis z \\
        --expected-radius-mm 5 \\
        --expected-axial-extent-mm 20 \\
        --layer-height-mm 0.4

Run from the repo root via `uv run`:
    uv run python scripts/verify_5axis_gcode.py ...
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Literal

# Allow running from anywhere via `uv run python scripts/verify_5axis_gcode.py`
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from bioslice5x.visualization.preview import ParsedMove, parse_gcode  # noqa: E402


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class VerificationReport:
    checks: list[CheckResult] = field(default_factory=list)
    summary: dict[str, object] = field(default_factory=dict)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(CheckResult(name=name, passed=passed, detail=detail))

    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def render(self) -> str:
        lines = []
        for c in self.checks:
            status = "PASS" if c.passed else "FAIL"
            lines.append(f"  [{status}] {c.name}")
            if c.detail:
                lines.append(f"           {c.detail}")
        lines.append("")
        lines.append("Summary:")
        for k, v in self.summary.items():
            lines.append(f"  {k}: {v}")
        verdict = "PASS" if self.all_passed() else "FAIL"
        lines.append("")
        lines.append(f"Overall: {verdict}")
        return "\n".join(lines)


def _group_by_z(moves: list[ParsedMove]) -> dict[float, list[ParsedMove]]:
    """Bin extrusion moves by rounded-Z (10 µm precision)."""
    out: dict[float, list[ParsedMove]] = defaultdict(list)
    for m in moves:
        z_key = round(m.end_xyz[2], 2)
        out[z_key].append(m)
    return dict(sorted(out.items()))


def verify(
    gcode_text: str,
    *,
    wrap_axis: Literal["x", "y", "z"],
    expected_radius_mm: float,
    expected_axial_extent_mm: float,
    layer_height_mm: float,
    arc_span_deg: float = 360.0,
    arc_span_tolerance_deg: float = 60.0,
    layer_height_tolerance_ratio: float = 0.05,
    max_decimals: int = 4,
) -> VerificationReport:
    """Run all 5-axis precision checks against `gcode_text`."""
    report = VerificationReport()
    moves, header = parse_gcode_from_text(gcode_text)
    extrusions = [m for m in moves if not m.is_travel]

    report.summary["total_moves"] = len(moves)
    report.summary["extrusion_moves"] = len(extrusions)
    report.summary["travel_moves"] = len(moves) - len(extrusions)
    report.summary["kinematic_chain"] = header.get("meta.kinematic_chain", "(missing)")
    report.summary["profile"] = header.get("Profile", "(missing)")

    # ------------------------------------------------------------
    # Check 1: every extrusion move has A and C tokens.
    # ------------------------------------------------------------
    missing_axes: list[str] = []
    for m in extrusions:
        if m.a_deg is None:
            missing_axes.append(f"  A missing on extrusion ending at {m.end_xyz}")
        if m.c_deg is None:
            missing_axes.append(f"  C missing on extrusion ending at {m.end_xyz}")
        if len(missing_axes) > 5:
            missing_axes.append(f"  ... ({len(extrusions)} more checks elided)")
            break
    report.add(
        "Every extrusion G1 carries A and C tokens",
        passed=not missing_axes,
        detail="" if not missing_axes else "\n".join(missing_axes[:5]),
    )

    # ------------------------------------------------------------
    # Check 2: all numeric tokens finite.
    # ------------------------------------------------------------
    bad_finite: list[str] = []
    for m in extrusions:
        for axis_name, v in (
            ("X", m.end_xyz[0]),
            ("Y", m.end_xyz[1]),
            ("Z", m.end_xyz[2]),
            ("A", m.a_deg),
            ("C", m.c_deg),
            ("E", m.extrusion_uL),
        ):
            if v is not None and not math.isfinite(v):
                bad_finite.append(f"  {axis_name}={v} on move ending {m.end_xyz}")
    report.add(
        "All numeric tokens are finite (no NaN / Inf)",
        passed=not bad_finite,
        detail="" if not bad_finite else "\n".join(bad_finite[:5]),
    )

    # Stop early if axes missing — the rest of the checks assume both.
    if missing_axes:
        return report

    # ------------------------------------------------------------
    # Group by Z layer for the per-layer checks.
    # ------------------------------------------------------------
    layers = _group_by_z(extrusions)
    layer_count = len(layers)
    report.summary["axial_layers"] = layer_count

    # ------------------------------------------------------------
    # Check 3: A constant within each layer when wrap_axis="z".
    # For wrap_axis="x" or "y", swivel stays constant and tilt sweeps;
    # the symmetric check applies to C instead.
    # ------------------------------------------------------------
    fixed_axis = "a_deg" if wrap_axis == "z" else "c_deg"
    fixed_axis_label = "A" if wrap_axis == "z" else "C"
    sweeping_axis = "c_deg" if wrap_axis == "z" else "a_deg"
    sweeping_axis_label = "C" if wrap_axis == "z" else "A"

    fixed_axis_violations: list[str] = []
    for z, layer in layers.items():
        fixed_values = {
            round(getattr(m, fixed_axis), 4) for m in layer if getattr(m, fixed_axis) is not None
        }
        if len(fixed_values) > 1:
            fixed_axis_violations.append(
                f"  z={z:.3f}: {fixed_axis_label} varied across {len(fixed_values)} values "
                f"({sorted(fixed_values)[:5]}…)"
            )
    report.add(
        f"{fixed_axis_label} stays constant within each axial layer (wrap_axis={wrap_axis})",
        passed=not fixed_axis_violations,
        detail="" if not fixed_axis_violations else "\n".join(fixed_axis_violations[:5]),
    )

    # ------------------------------------------------------------
    # Check 4: sweeping axis covers ≈ the requested arc within each layer.
    # ------------------------------------------------------------
    arc_violations: list[str] = []
    layer_arc_spans: list[float] = []
    for z, layer in layers.items():
        vals = [getattr(m, sweeping_axis) for m in layer if getattr(m, sweeping_axis) is not None]
        if not vals:
            continue
        span = max(vals) - min(vals)
        layer_arc_spans.append(span)
        if span < arc_span_deg - arc_span_tolerance_deg:
            arc_violations.append(
                f"  z={z:.3f}: {sweeping_axis_label} span {span:.1f}° < "
                f"{arc_span_deg - arc_span_tolerance_deg:.0f}° expected"
            )
    if layer_arc_spans:
        report.summary[f"{sweeping_axis_label}_span_mean_deg"] = (
            f"{sum(layer_arc_spans) / len(layer_arc_spans):.2f}"
        )
        report.summary[f"{sweeping_axis_label}_span_min_deg"] = f"{min(layer_arc_spans):.2f}"
    report.add(
        f"{sweeping_axis_label} sweeps the requested arc "
        f"({arc_span_deg:.0f}° ± {arc_span_tolerance_deg:.0f}°) per layer",
        passed=not arc_violations,
        detail="" if not arc_violations else "\n".join(arc_violations[:5]),
    )

    # ------------------------------------------------------------
    # Check 5: axial Z spacing matches layer_height_mm.
    # ------------------------------------------------------------
    zs = sorted(layers.keys())
    dz_violations: list[str] = []
    if len(zs) >= 2:
        tol = layer_height_mm * layer_height_tolerance_ratio
        for prev, nxt in pairwise(zs):
            dz = nxt - prev
            if not (layer_height_mm - tol <= dz <= layer_height_mm + tol):
                dz_violations.append(
                    f"  {prev:.3f} -> {nxt:.3f}: Δz={dz:.4f} mm vs "
                    f"expected {layer_height_mm:.4f} ± {tol:.4f}"
                )
    report.add(
        f"Axial Z spacing matches layer_height_mm ({layer_height_mm} ± "
        f"{layer_height_tolerance_ratio:.0%}) between adjacent layers",
        passed=not dz_violations,
        detail="" if not dz_violations else "\n".join(dz_violations[:5]),
    )

    # ------------------------------------------------------------
    # Check 6: layer count vs expected from axial extent / layer height.
    # ------------------------------------------------------------
    expected_layer_count = max(1, round(expected_axial_extent_mm / layer_height_mm))
    layer_count_delta = abs(layer_count - expected_layer_count)
    report.summary["expected_layer_count"] = expected_layer_count
    report.add(
        f"Layer count ({layer_count}) within ±1 of "
        f"{expected_layer_count} = ceil({expected_axial_extent_mm} / {layer_height_mm})",
        passed=layer_count_delta <= 1,
        detail="" if layer_count_delta <= 1 else f"  delta = {layer_count_delta}",
    )

    # ------------------------------------------------------------
    # Check 7: sweep-axis values are written to ≤ max_decimals decimals.
    # ------------------------------------------------------------
    precision_violations: list[str] = []
    for line in gcode_text.splitlines():
        if not line.startswith("G1"):
            continue
        for tok in line.split():
            if not (tok.startswith("A") or tok.startswith("C")):
                continue
            if len(tok) < 2 or tok[1] not in "-0123456789.":
                continue
            value_part = tok[1:]
            if "." in value_part:
                frac = value_part.split(".", 1)[1]
                if len(frac) > max_decimals:
                    precision_violations.append(f"  {tok} on line: {line.strip()[:80]}…")
                    if len(precision_violations) > 5:
                        break
        if len(precision_violations) > 5:
            break
    report.add(
        f"A/C tokens have at most {max_decimals} decimal digits",
        passed=not precision_violations,
        detail="" if not precision_violations else "\n".join(precision_violations[:5]),
    )

    # ------------------------------------------------------------
    # Check 8: cylinder radius — extrusion endpoints sit on the cylinder.
    # For wrap_axis="z": every extrusion (x, y) should be at distance
    # ≈ expected_radius_mm from origin, since the slicer places vertices
    # at (r·cos θ, r·sin θ, s) in part frame.
    # ------------------------------------------------------------
    if wrap_axis == "z":
        r_violations: list[str] = []
        tol = max(0.05, layer_height_mm)  # 50 µm or one layer worth
        rs = []
        for m in extrusions:
            x, y, _ = m.end_xyz
            r = math.hypot(x, y)
            rs.append(r)
            if abs(r - expected_radius_mm) > tol:
                r_violations.append(
                    f"  endpoint at ({x:.3f}, {y:.3f}) — r={r:.3f} vs "
                    f"expected {expected_radius_mm} ± {tol}"
                )
                if len(r_violations) > 5:
                    break
        if rs:
            report.summary["radius_mean_mm"] = f"{sum(rs) / len(rs):.4f}"
            report.summary["radius_max_dev_mm"] = (
                f"{max(abs(r - expected_radius_mm) for r in rs):.4f}"
            )
        report.add(
            f"Extrusion endpoints lie on cylinder of radius {expected_radius_mm} ± {tol} mm",
            passed=not r_violations,
            detail="" if not r_violations else "\n".join(r_violations[:5]),
        )

    return report


def parse_gcode_from_text(text: str) -> tuple[list[ParsedMove], dict[str, str]]:
    """Wrapper that lets `parse_gcode` consume an in-memory string."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".gcode", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        return parse_gcode(path)
    finally:
        Path(path).unlink(missing_ok=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("gcode", help="Path to the G-code file to verify.")
    p.add_argument("--wrap-axis", choices=("x", "y", "z"), default="z")
    p.add_argument("--expected-radius-mm", type=float, required=True)
    p.add_argument("--expected-axial-extent-mm", type=float, required=True)
    p.add_argument("--layer-height-mm", type=float, required=True)
    p.add_argument("--arc-span-deg", type=float, default=360.0)
    p.add_argument("--arc-span-tolerance-deg", type=float, default=60.0)
    p.add_argument("--max-decimals", type=int, default=4)
    args = p.parse_args()

    text = Path(args.gcode).read_text(encoding="utf-8")
    report = verify(
        text,
        wrap_axis=args.wrap_axis,
        expected_radius_mm=args.expected_radius_mm,
        expected_axial_extent_mm=args.expected_axial_extent_mm,
        layer_height_mm=args.layer_height_mm,
        arc_span_deg=args.arc_span_deg,
        arc_span_tolerance_deg=args.arc_span_tolerance_deg,
        max_decimals=args.max_decimals,
    )
    print(report.render())
    return 0 if report.all_passed() else 1


if __name__ == "__main__":
    raise SystemExit(main())
