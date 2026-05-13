#!/usr/bin/env python3
"""Feature-gauntlet integration test for BioSlice5X.

Generates a single test mesh that exercises every slicing path the
slicer supports, then runs a battery of slice configurations against
it and reports per-case PASS / FAIL with structured error info.

Mesh choice: a thin-walled cylinder at radius 5 mm, height 15 mm,
centered on the build plate. This shape is the FRESH bioprinting
test workhorse because it is:

  - A valid input for flat slicing (the cylinder cross-section is
    a circle; flat slicer pulls 38 layers at 0.4 mm).
  - A valid input for `wrap_axis="z"` conformal (swivel sweeps θ
    while tilt sits at 0). Works on both Prusa (A+C) and Voron
    (B+C) profiles.
  - A valid input for `wrap_axis="x"` conformal on Prusa (tilt
    sweeps θ on A).
  - A valid input for `wrap_axis="y"` conformal on Voron with
    arc-split (tilt sweeps θ on B).
  - A reasonable bbox-clipping target for multi-syringe testing
    (carve out a top "shell" syringe + bottom "core" syringe).
  - Small enough that every test runs in under a second.

Test cases cover, in order: shipped library load, three profile
loads, flat 3-axis, flat 3-axis with infill, flat 3-axis multi-
syringe with bbox regions, flat 5-axis fixed orientation on both
Prusa and Voron, conformal wrap on all three axes against the
appropriate profile, retract enabled / disabled, cell-viability
refusal with --force override, and the axis-range mechanical clamp
on an out-of-range orientation.

Each test reports a structured result. The final summary is the
PASS / FAIL count and an exit code (0 on green, 1 on red).

Run from the repo root:

    uv run python scripts/test_slicer_gauntlet.py

To also smoke the live production API, pass `--remote`:

    uv run python scripts/test_slicer_gauntlet.py --remote
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import trimesh

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from bioslice5x import Slicer, load_profile  # noqa: E402
from bioslice5x.errors import (  # noqa: E402
    CellViabilityError,
    ClampingExceededError,
    ProfileValidationError,
)
from bioslice5x.recipe.models import (  # noqa: E402
    FixedOrientation,
    Needle,
    Recipe,
    RegionBBox,
    SlicingParams,
    Syringe,
    WrapAroundAxisSlicing,
)

# ---------------------------------------------------------------------------
# Test mesh
# ---------------------------------------------------------------------------


def make_gauntlet_mesh(
    radius_mm: float = 5.0,
    height_mm: float = 15.0,
    sections: int = 96,
) -> trimesh.Trimesh:
    """Cylinder centered on the build plate.

    `sections=96` matches the bundled `vascular_scaffold.stl`; the
    conformal-slicer arc-sample default (1 sample per line_width)
    is finer, so the mesh tessellation is not the bottleneck.
    """
    cyl: Any = trimesh.creation.cylinder(radius=radius_mm, height=height_mm, sections=sections)
    cyl.apply_translation([0.0, 0.0, height_mm / 2.0])
    return cast(trimesh.Trimesh, cyl)


# ---------------------------------------------------------------------------
# Recipe builders
# ---------------------------------------------------------------------------

_DEFAULT_NEEDLE = Needle(inner_diameter_mm=0.84, length_mm=12.7, gauge_label="18G")


def _basic_syringe(
    sid: int = 0,
    bioink: str = "collagen_i_8mg_per_mL",
    cell: str = "general_mammalian",
    *,
    region: Any | None = None,
    retract: float = 0.5,
) -> Syringe:
    kwargs: dict[str, Any] = {
        "id": sid,
        "bioink": bioink,
        "cell_payload": cell,
        "needle": _DEFAULT_NEEDLE,
        "retract_volume_uL": retract,
    }
    if region is not None:
        kwargs["region"] = region
    return Syringe(**kwargs)


def flat_recipe(
    *,
    syringes: list[Syringe] | None = None,
    infill_density: float = 0.0,
    print_speed: float = 60.0,
    orientation: Any | None = None,
) -> Recipe:
    """Flat slicing recipe (default print_orientation = no tilt)."""
    return Recipe(
        name="gauntlet_flat",
        syringes=syringes or [_basic_syringe()],
        slicing=SlicingParams(
            layer_height_mm=0.4,
            line_width_mm=0.5,
            print_speed_mm_per_min=print_speed,
            infill_density=infill_density,
        ),
        print_orientation=orientation or FixedOrientation(),
    )


def conformal_recipe(
    *,
    wrap_axis: str,
    line_width: float = 0.4,
    arc_start: float = -180.0,
    arc_end: float = 180.0,
    allow_split: bool = False,
    split_count: int = 1,
    retract: float = 0.5,
) -> Recipe:
    return Recipe(
        name=f"gauntlet_conformal_{wrap_axis}",
        syringes=[_basic_syringe(retract=retract)],
        slicing=SlicingParams(
            layer_height_mm=0.4,
            line_width_mm=line_width,
            print_speed_mm_per_min=60.0,
            mode=WrapAroundAxisSlicing(
                wrap_axis=cast(Any, wrap_axis),
                cylinder_radius_mm=5.0,
                arc_start_deg=arc_start,
                arc_end_deg=arc_end,
                allow_tilt_arc_split=allow_split,
                arc_split_count=split_count,
            ),
        ),
        print_orientation=FixedOrientation(),
    )


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    name: str
    status: str  # "PASS" | "FAIL" | "EXPECTED_RAISE_PASS"
    detail: str = ""
    duration_ms: float = 0.0
    gcode_size: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def _check_emitted(gcode: str, expectations: dict[str, bool]) -> list[str]:
    """Return a list of missing-or-misplaced features in `gcode`."""
    out: list[str] = []
    for fragment, should_be_present in expectations.items():
        present = fragment in gcode
        if present != should_be_present:
            out.append(
                f"feature {fragment!r}: expected present={should_be_present}, got present={present}"
            )
    return out


def run_case(
    name: str,
    fn: Callable[[trimesh.Trimesh], dict[str, Any]],
    mesh: trimesh.Trimesh,
    *,
    expect_raise: type[Exception] | None = None,
) -> CaseResult:
    t0 = time.perf_counter()
    try:
        info = fn(mesh)
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if expect_raise is not None and isinstance(exc, expect_raise):
            return CaseResult(
                name=name,
                status="EXPECTED_RAISE_PASS",
                detail=f"raised expected {type(exc).__name__}: {exc}",
                duration_ms=elapsed_ms,
            )
        return CaseResult(
            name=name,
            status="FAIL",
            detail=f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}",
            duration_ms=elapsed_ms,
        )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if expect_raise is not None:
        return CaseResult(
            name=name,
            status="FAIL",
            detail=f"expected {expect_raise.__name__} but slice succeeded",
            duration_ms=elapsed_ms,
        )
    issues = info.pop("issues", [])
    if issues:
        return CaseResult(
            name=name,
            status="FAIL",
            detail="\n".join(issues),
            duration_ms=elapsed_ms,
            gcode_size=info.get("gcode_size", 0),
            extra=info,
        )
    return CaseResult(
        name=name,
        status="PASS",
        duration_ms=elapsed_ms,
        gcode_size=info.get("gcode_size", 0),
        extra=info,
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def _slice_local(profile_name: str, recipe: Recipe, mesh: trimesh.Trimesh, *, force: bool = False):
    profile = load_profile(profile_name)
    slicer = Slicer(profile=profile, recipe=recipe)
    return slicer.slice(mesh, force=force)


def case_flat_3axis_perimeter(mesh: trimesh.Trimesh) -> dict[str, Any]:
    result = _slice_local("hypothetical_3axis", flat_recipe(), mesh)
    g = result.gcode
    return {
        "gcode_size": len(g),
        "moves": len(result.moves),
        "issues": _check_emitted(
            g,
            {
                "; BioSlice5X G-code (3-axis baseline)": True,
                "; retract 0.5 uL": True,
                "; un-retract 0.5 uL": True,
                "safe-park Z": True,
                "M104 S0 T0": True,
                "G92 E0": True,
                "rotaries home": False,  # 3-axis: no rotaries
            },
        ),
    }


def case_flat_3axis_infill(mesh: trimesh.Trimesh) -> dict[str, Any]:
    result = _slice_local("hypothetical_3axis", flat_recipe(infill_density=0.2), mesh)
    g = result.gcode
    moves_with_infill_id = [m for m in result.moves if "_I" in m.segment_id and not m.is_travel]
    return {
        "gcode_size": len(g),
        "moves": len(result.moves),
        "infill_moves": len(moves_with_infill_id),
        "issues": [] if moves_with_infill_id else ["no infill moves emitted at density=0.2"],
    }


def case_flat_3axis_multi_syringe(mesh: trimesh.Trimesh) -> dict[str, Any]:
    inner = RegionBBox(min=(-3.0, -3.0, 0.0), max=(3.0, 3.0, 5.0))
    outer = RegionBBox(min=(-10.0, -10.0, 5.0), max=(10.0, 10.0, 15.0))
    recipe = flat_recipe(
        syringes=[
            _basic_syringe(0, region=inner),
            _basic_syringe(
                1, bioink="collagen_i_8mg_per_mL", cell="hUVEC_endothelial", region=outer
            ),
        ]
    )
    result = _slice_local("hypothetical_3axis", recipe, mesh)
    g = result.gcode
    return {
        "gcode_size": len(g),
        "moves": len(result.moves),
        "syringes": len(result.total_bioink_uL_by_syringe),
        "issues": _check_emitted(
            g,
            {
                "T0  ; switch to syringe 0": True,
                "T1  ; switch to syringe 1": True,
                "; retract 0.5 uL": True,
                "G92 E0": True,
            },
        ),
    }


def case_flat_5axis_prusa_fixed(mesh: trimesh.Trimesh) -> dict[str, Any]:
    recipe = flat_recipe(orientation=FixedOrientation(tilt_deg=15.0, swivel_deg=10.0))
    result = _slice_local("open5x_prusa", recipe, mesh)
    g = result.gcode
    return {
        "gcode_size": len(g),
        "moves": len(result.moves),
        "issues": _check_emitted(
            g,
            {
                "; BioSlice5X G-code (5-axis tilt+swivel)": True,
                "A15": True,  # tilt token on A axis
                "C10": True,  # swivel token on C axis
                "rotaries home": True,
            },
        ),
    }


def case_flat_5axis_voron_fixed(mesh: trimesh.Trimesh) -> dict[str, Any]:
    recipe = flat_recipe(orientation=FixedOrientation(tilt_deg=-20.0, swivel_deg=45.0))
    result = _slice_local("open5x_voron", recipe, mesh)
    g = result.gcode
    return {
        "gcode_size": len(g),
        "moves": len(result.moves),
        "issues": _check_emitted(
            g,
            {
                "B-20": True,  # tilt token on B axis (Voron convention)
                "C45": True,  # swivel token on C axis
                "rotaries home": True,
            },
        ),
    }


def case_conformal_wrap_z_prusa(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """`wrap_axis=z`: swivel sweeps, tilt stays at 0. Tests the C-axis path."""
    result = _slice_local("open5x_prusa", conformal_recipe(wrap_axis="z"), mesh)
    g = result.gcode
    g1_lines = [ln for ln in g.splitlines() if ln.startswith("G1 ")]
    # Count distinct C values across the sweep.
    distinct_c: set[str] = set()
    for line in g1_lines:
        for tok in line.split():
            if tok.startswith("C") and len(tok) > 1 and tok[1] in "-0123456789.":
                distinct_c.add(tok)
                break
    return {
        "gcode_size": len(g),
        "moves": len(result.moves),
        "distinct_C": len(distinct_c),
        "issues": []
        if len(distinct_c) >= 30
        else [f"expected ≥30 distinct C values across full 360° sweep; got {len(distinct_c)}"],
    }


def case_conformal_wrap_z_voron(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """`wrap_axis=z` on Voron — same swivel axis, different tilt letter (B)."""
    result = _slice_local("open5x_voron", conformal_recipe(wrap_axis="z"), mesh)
    g = result.gcode
    # On wrap_axis=z, tilt is 0 → B0 emitted on every line.
    g1_lines = [ln for ln in g.splitlines() if ln.startswith("G1 ")]
    b_zero_count = sum(1 for ln in g1_lines for tok in ln.split() if tok == "B0")
    return {
        "gcode_size": len(g),
        "moves": len(result.moves),
        "B0_tokens": b_zero_count,
        "issues": []
        if b_zero_count > 100
        else [f"expected many B0 tokens on wrap_z (tilt fixed at 0); got {b_zero_count}"],
    }


def case_conformal_wrap_x_prusa(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """`wrap_axis=x` on Prusa: tilt sweeps on A axis (rotates about X)."""
    result = _slice_local(
        "open5x_prusa",
        conformal_recipe(wrap_axis="x", arc_start=-90.0, arc_end=90.0),
        mesh,
    )
    g = result.gcode
    distinct_a: set[str] = set()
    for line in g.splitlines():
        if not line.startswith("G1 "):
            continue
        for tok in line.split():
            if tok.startswith("A") and len(tok) > 1 and tok[1] in "-0123456789.":
                distinct_a.add(tok)
                break
    return {
        "gcode_size": len(g),
        "moves": len(result.moves),
        "distinct_A": len(distinct_a),
        "issues": []
        if len(distinct_a) >= 5
        else [f"expected wide A sweep on wrap_x; got {len(distinct_a)} distinct values"],
    }


def case_conformal_wrap_y_voron(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """`wrap_axis=y` on Voron: tilt sweeps on B axis (rotates about Y)."""
    result = _slice_local(
        "open5x_voron",
        conformal_recipe(wrap_axis="y", arc_start=-90.0, arc_end=90.0),
        mesh,
    )
    g = result.gcode
    distinct_b: set[str] = set()
    for line in g.splitlines():
        if not line.startswith("G1 "):
            continue
        for tok in line.split():
            if tok.startswith("B") and len(tok) > 1 and tok[1] in "-0123456789.":
                distinct_b.add(tok)
                break
    return {
        "gcode_size": len(g),
        "moves": len(result.moves),
        "distinct_B": len(distinct_b),
        "issues": []
        if len(distinct_b) >= 5
        else [f"expected wide B sweep on wrap_y; got {len(distinct_b)} distinct values"],
    }


def case_retract_off(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """retract_volume_uL=0 → no retract lines."""
    recipe = flat_recipe(syringes=[_basic_syringe(retract=0.0)])
    result = _slice_local("hypothetical_3axis", recipe, mesh)
    g = result.gcode
    retracts = [ln for ln in g.splitlines() if ln.startswith("G1 E-")]
    return {
        "gcode_size": len(g),
        "moves": len(result.moves),
        "retract_lines": len(retracts),
        "issues": [] if not retracts else [f"expected zero retracts; got {len(retracts)}"],
    }


def case_cell_viability_refusal(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """A high-speed print with MIN6 β-cells should refuse on shear violation."""
    recipe = Recipe(
        name="gauntlet_viability",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="MIN6_beta_cell",  # 1500 Pa threshold — strictest
                needle=Needle(inner_diameter_mm=0.21, length_mm=12.7, gauge_label="27G"),
            )
        ],
        slicing=SlicingParams(
            layer_height_mm=0.4,
            line_width_mm=0.5,
            print_speed_mm_per_min=600.0,  # 10x — high shear at 27G
        ),
    )
    _slice_local("hypothetical_3axis", recipe, mesh)
    return {"issues": []}


def case_cell_viability_force_override(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """force=True bypasses the refusal and emits the SAFETY_OVERRIDE banner."""
    recipe = Recipe(
        name="gauntlet_viability_force",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="MIN6_beta_cell",
                needle=Needle(inner_diameter_mm=0.21, length_mm=12.7),
            )
        ],
        slicing=SlicingParams(
            layer_height_mm=0.4,
            line_width_mm=0.5,
            print_speed_mm_per_min=600.0,
        ),
    )
    result = _slice_local("hypothetical_3axis", recipe, mesh, force=True)
    g = result.gcode
    return {
        "gcode_size": len(g),
        "moves": len(result.moves),
        "issues": _check_emitted(
            g,
            {
                "WARNING: SAFETY_OVERRIDE": True,
                ";META: safety_override=true": True,
            },
        ),
    }


def case_axis_range_clamp(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """FixedOrientation tilt=150° on Voron (±110° range) must refuse."""
    recipe = flat_recipe(
        orientation=FixedOrientation(tilt_deg=150.0, swivel_deg=0.0),
    )
    _slice_local("open5x_voron", recipe, mesh)
    return {"issues": []}


def case_clamping_exceeded_refusal(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """360° wrap_y on Voron (±110° tilt) must refuse without arc-split."""
    recipe = conformal_recipe(wrap_axis="y")
    _slice_local("open5x_voron", recipe, mesh)
    return {"issues": []}


def case_flat_5axis_jubilee(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """Jubilee chassis: tilt is letter B (rotates about Y), swivel is letter C."""
    recipe = flat_recipe(orientation=FixedOrientation(tilt_deg=12.0, swivel_deg=-20.0))
    result = _slice_local("open5x_jubilee", recipe, mesh)
    g = result.gcode
    return {
        "gcode_size": len(g),
        "moves": len(result.moves),
        "issues": _check_emitted(
            g,
            {
                "; BioSlice5X G-code (5-axis tilt+swivel)": True,
                ";META: tilt_letter=B": True,
                ";META: tilt_axis=y": True,
                ";META: swivel_letter=C": True,
                ";META: swivel_axis=z": True,
                "B12": True,  # tilt token on B
                "C-20": True,  # swivel token on C
                "rotaries home": True,
                # Must NOT emit A or U/V tokens on this chassis.
                "A12": False,
                "U12": False,
            },
        ),
    }


def case_flat_5axis_prusa_uv(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """Current-upstream Open5X Prusa firmware: rotaries emit as U + V."""
    recipe = flat_recipe(orientation=FixedOrientation(tilt_deg=15.0, swivel_deg=30.0))
    result = _slice_local("open5x_prusa_uv", recipe, mesh)
    g = result.gcode
    return {
        "gcode_size": len(g),
        "moves": len(result.moves),
        "issues": _check_emitted(
            g,
            {
                ";META: tilt_letter=U": True,
                ";META: swivel_letter=V": True,
                "U15": True,
                "V30": True,
                "rotaries home": True,
                # Must NOT emit A or C tokens on this firmware variant.
                "A15": False,
                "C30": False,
            },
        ),
    }


def case_conformal_wrap_z_jubilee(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """Jubilee swivel sweep via wrap_axis=z. Tilt B stays at 0."""
    result = _slice_local("open5x_jubilee", conformal_recipe(wrap_axis="z"), mesh)
    g = result.gcode
    g1_lines = [ln for ln in g.splitlines() if ln.startswith("G1 ")]
    distinct_c: set[str] = set()
    for line in g1_lines:
        for tok in line.split():
            if tok.startswith("C") and len(tok) > 1 and tok[1] in "-0123456789.":
                distinct_c.add(tok)
                break
    b_zero_count = sum(1 for ln in g1_lines for tok in ln.split() if tok == "B0")
    return {
        "gcode_size": len(g),
        "moves": len(result.moves),
        "distinct_C": len(distinct_c),
        "B0_tokens": b_zero_count,
        "issues": []
        if len(distinct_c) >= 30 and b_zero_count > 100
        else [
            f"expected wide C sweep + many B0 tokens on Jubilee wrap_z; got C={len(distinct_c)}, B0={b_zero_count}"
        ],
    }


# ---------------------------------------------------------------------------
# Remote (production API) smoke
# ---------------------------------------------------------------------------


_REMOTE_URL = "https://bioslice5x-web.vercel.app/api/slice"


def _recipe_to_dict(recipe: Recipe) -> dict[str, Any]:
    return json.loads(recipe.model_dump_json())


def _slice_remote(
    profile: str, recipe: Recipe, mesh_bytes: bytes, *, timeout: float = 120.0
) -> dict[str, Any]:
    payload = {
        "mesh": {
            "format": "stl",
            "data_base64": base64.b64encode(mesh_bytes).decode("ascii"),
        },
        "profile": profile,
        "recipe": _recipe_to_dict(recipe),
    }
    req = urllib.request.Request(
        _REMOTE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return cast(dict[str, Any], json.load(resp))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:500]}") from exc


def remote_smoke(mesh_bytes: bytes) -> list[CaseResult]:
    """One canonical 3-axis flat + one 5-axis conformal against the live API."""
    out: list[CaseResult] = []
    # 3-axis flat.
    t0 = time.perf_counter()
    try:
        body = _slice_remote("hypothetical_3axis", flat_recipe(), mesh_bytes)
        elapsed = (time.perf_counter() - t0) * 1000.0
        g = body["gcode"]
        issues = _check_emitted(
            g,
            {
                "; BioSlice5X G-code (3-axis baseline)": True,
                "; retract 0.5 uL": True,
                "safe-park Z": True,
            },
        )
        out.append(
            CaseResult(
                name="remote_flat_3axis",
                status="PASS" if not issues else "FAIL",
                detail="\n".join(issues),
                duration_ms=elapsed,
                gcode_size=len(g),
                extra={"moves": body["stats"]["total_moves"]},
            )
        )
    except Exception as exc:
        out.append(
            CaseResult(
                name="remote_flat_3axis",
                status="FAIL",
                detail=f"{type(exc).__name__}: {exc}",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )
        )
    # 5-axis Prusa conformal wrap_z.
    t0 = time.perf_counter()
    try:
        body = _slice_remote("open5x_prusa", conformal_recipe(wrap_axis="z"), mesh_bytes)
        elapsed = (time.perf_counter() - t0) * 1000.0
        g = body["gcode"]
        issues = _check_emitted(
            g,
            {
                "; BioSlice5X G-code (5-axis tilt+swivel)": True,
                "rotaries home": True,
            },
        )
        out.append(
            CaseResult(
                name="remote_conformal_wrap_z_prusa",
                status="PASS" if not issues else "FAIL",
                detail="\n".join(issues),
                duration_ms=elapsed,
                gcode_size=len(g),
                extra={"moves": body["stats"]["total_moves"]},
            )
        )
    except Exception as exc:
        out.append(
            CaseResult(
                name="remote_conformal_wrap_z_prusa",
                status="FAIL",
                detail=f"{type(exc).__name__}: {exc}",
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


CASES: list[tuple[str, Callable[[trimesh.Trimesh], dict[str, Any]], type[Exception] | None]] = [
    ("flat_3axis_perimeter", case_flat_3axis_perimeter, None),
    ("flat_3axis_infill", case_flat_3axis_infill, None),
    ("flat_3axis_multi_syringe_bbox", case_flat_3axis_multi_syringe, None),
    ("flat_5axis_prusa_fixed_15_10", case_flat_5axis_prusa_fixed, None),
    ("flat_5axis_voron_fixed_-20_45", case_flat_5axis_voron_fixed, None),
    ("conformal_wrap_z_prusa", case_conformal_wrap_z_prusa, None),
    ("conformal_wrap_z_voron", case_conformal_wrap_z_voron, None),
    ("conformal_wrap_x_prusa_180", case_conformal_wrap_x_prusa, None),
    ("conformal_wrap_y_voron_180", case_conformal_wrap_y_voron, None),
    ("retract_disabled_when_uL_zero", case_retract_off, None),
    ("cell_viability_refusal_raises", case_cell_viability_refusal, CellViabilityError),
    ("cell_viability_force_override", case_cell_viability_force_override, None),
    ("axis_range_clamp_raises", case_axis_range_clamp, ProfileValidationError),
    ("clamping_exceeded_360_voron", case_clamping_exceeded_refusal, ClampingExceededError),
    ("flat_5axis_jubilee_12_-20", case_flat_5axis_jubilee, None),
    ("flat_5axis_prusa_uv_15_30", case_flat_5axis_prusa_uv, None),
    ("conformal_wrap_z_jubilee", case_conformal_wrap_z_jubilee, None),
]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    p.add_argument(
        "--remote",
        action="store_true",
        help="Also smoke the production API at " + _REMOTE_URL,
    )
    p.add_argument(
        "--write-mesh",
        type=Path,
        default=None,
        help="Optional path to write the generated test STL.",
    )
    p.add_argument(
        "--write-gcode-dir",
        type=Path,
        default=None,
        help="Optional directory to write each successful slice as <case_name>.gcode.",
    )
    args = p.parse_args()

    mesh = make_gauntlet_mesh()
    if args.write_mesh:
        args.write_mesh.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(str(args.write_mesh))
        print(f"wrote test mesh: {args.write_mesh}")

    if args.write_gcode_dir:
        args.write_gcode_dir.mkdir(parents=True, exist_ok=True)

    results: list[CaseResult] = []
    print(f"running {len(CASES)} feature cases against the local slicer library...")
    print()
    for name, fn, expect_raise in CASES:
        res = run_case(name, fn, mesh, expect_raise=expect_raise)
        results.append(res)
        status_glyph = {
            "PASS": "PASS",
            "EXPECTED_RAISE_PASS": "PASS",
            "FAIL": "FAIL",
        }[res.status]
        suffix_bits = [f"{res.duration_ms:6.1f} ms"]
        if res.gcode_size:
            suffix_bits.append(f"{res.gcode_size // 1024} kB")
        suffix = "  ".join(suffix_bits)
        print(f"  [{status_glyph}]  {name:42s}  {suffix}")
        if res.status == "FAIL":
            for line in res.detail.splitlines():
                print(f"           {line}")
        if args.write_gcode_dir and res.status == "PASS" and res.extra.get("moves"):
            # Re-slice to capture gcode text. (Cheap; cases are <1s each.)
            try:
                if name.startswith("flat_3axis"):
                    if "infill" in name:
                        recipe = flat_recipe(infill_density=0.2)
                        profile = "hypothetical_3axis"
                    elif "multi_syringe" in name:
                        inner = RegionBBox(min=(-3.0, -3.0, 0.0), max=(3.0, 3.0, 5.0))
                        outer = RegionBBox(min=(-10.0, -10.0, 5.0), max=(10.0, 10.0, 15.0))
                        recipe = flat_recipe(
                            syringes=[
                                _basic_syringe(0, region=inner),
                                _basic_syringe(
                                    1,
                                    bioink="collagen_i_8mg_per_mL",
                                    cell="hUVEC_endothelial",
                                    region=outer,
                                ),
                            ]
                        )
                        profile = "hypothetical_3axis"
                    else:
                        recipe = flat_recipe()
                        profile = "hypothetical_3axis"
                elif "prusa_fixed" in name:
                    recipe = flat_recipe(
                        orientation=FixedOrientation(tilt_deg=15.0, swivel_deg=10.0)
                    )
                    profile = "open5x_prusa"
                elif "voron_fixed" in name:
                    recipe = flat_recipe(
                        orientation=FixedOrientation(tilt_deg=-20.0, swivel_deg=45.0)
                    )
                    profile = "open5x_voron"
                elif name == "conformal_wrap_z_prusa":
                    recipe = conformal_recipe(wrap_axis="z")
                    profile = "open5x_prusa"
                elif name == "conformal_wrap_z_voron":
                    recipe = conformal_recipe(wrap_axis="z")
                    profile = "open5x_voron"
                elif name == "conformal_wrap_x_prusa_180":
                    recipe = conformal_recipe(wrap_axis="x", arc_start=-90.0, arc_end=90.0)
                    profile = "open5x_prusa"
                elif name == "conformal_wrap_y_voron_180":
                    recipe = conformal_recipe(wrap_axis="y", arc_start=-90.0, arc_end=90.0)
                    profile = "open5x_voron"
                elif name == "retract_disabled_when_uL_zero":
                    recipe = flat_recipe(syringes=[_basic_syringe(retract=0.0)])
                    profile = "hypothetical_3axis"
                else:
                    continue
                gout = _slice_local(profile, recipe, mesh).gcode
                (args.write_gcode_dir / f"{name}.gcode").write_text(gout)
            except Exception:
                pass

    if args.remote:
        print()
        print(f"smoke-testing live API at {_REMOTE_URL}...")
        mesh_bytes = trimesh.exchange.stl.export_stl(mesh)
        remote_results = remote_smoke(mesh_bytes)
        for res in remote_results:
            status_glyph = "PASS" if res.status == "PASS" else "FAIL"
            print(f"  [{status_glyph}]  {res.name:42s}  {res.duration_ms:6.1f} ms")
            if res.status != "PASS":
                for line in res.detail.splitlines():
                    print(f"           {line}")
            results.append(res)

    print()
    passed = sum(1 for r in results if r.status in ("PASS", "EXPECTED_RAISE_PASS"))
    failed = sum(1 for r in results if r.status == "FAIL")
    print(f"summary: {passed} passed / {failed} failed / {len(results)} total")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
