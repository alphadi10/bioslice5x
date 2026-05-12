"""RepRapFirmware G-code emitter.

3-axis (XYZ + E) in Phase 2a; the emitter consults `profile.kinematic_chain`
so Phase 2b's TiltSwivelKinematics can drop in by adding A/C tokens to each
G1 line without restructuring this module.

Token order mirrors Open5X's M584 column convention: `X Y Z [A C] E F`. See
`docs/OPEN5X_NOTES.md` §4.

Every header carries:

- Prose block with bioink/cell/needle for human operators.
- `;META: key=value` block for machine consumers (downstream lab automation
  can refuse to run an uncalibrated file without explicit override).
- `========== WARNING: SAFETY_OVERRIDE ==========` banner if the G-code was
  emitted with `force=True` despite cell-viability violations. The banner
  lists every violating segment so a future operator opening the file knows
  exactly what was overridden.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from bioslice5x.errors import ProfileValidationError
from bioslice5x.extruder.syringe import DisplacementSyringe
from bioslice5x.extruder.validate import StressReport
from bioslice5x.kinematics.canonical import JointAngles
from bioslice5x.pathing.types import Move
from bioslice5x.profile.models import MachineProfile, TiltSwivelAxis
from bioslice5x.recipe.models import Recipe


def _fmt(value: float, decimals: int = 4) -> str:
    """Format a float with trailing-zero trim."""
    if value == 0.0:
        return "0"
    formatted = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return formatted if formatted else "0"


def _axis_token(axis_spec: TiltSwivelAxis, canonical_rad: float) -> str:
    """Render a canonical (radian) joint angle as a G-code letter+value token.

    Applies the profile's `invert` flag by negating the canonical angle
    before formatting. The kinematics module never sees this flag — it's a
    pure postprocessor concern (see ARCHITECTURE.md §8.1).

    Mechanical-range handling:

    1. The natural canonical-frame value is computed first.
    2. If it sits outside the axis's mechanical range, the postprocessor
       tries 2π (360°) wraps in either direction — a rotary at +270° is
       mechanically identical in orientation to one at -90°, so a profile
       with range ±200° can satisfy a canonical 270° command by emitting
       -90°. This is purely the postprocessor's job (see ARCHITECTURE.md
       §8.1): kinematics is letter-and-range-free; only the emitter knows
       which physical pose is reachable.
    3. If no 2π-shifted equivalent fits, the slicer refuses loudly with a
       ProfileValidationError — a value outside the axis's range would
       drive the rotary into a hard stop on real hardware.

    The wrap-normalization preserves continuity for in-range values
    (no change), and only kicks in to rescue an out-of-range canonical
    angle whose physically-equivalent in-range pose is reachable.
    """
    deg = math.degrees(canonical_rad)
    if axis_spec.invert:
        deg = -deg
    lo, hi = axis_spec.range_deg
    eps = 1e-6
    if not (lo - eps <= deg <= hi + eps):
        # Try the nearest 2π-wrap that lands inside the range. Bias the
        # candidate toward the centre of the range so a barely-out value
        # snaps to the closest equivalent pose.
        centre = (lo + hi) / 2.0
        n = round((centre - deg) / 360.0)
        if n != 0:
            candidate = deg + 360.0 * n
            if lo - eps <= candidate <= hi + eps:
                deg = candidate
    if not (lo - eps <= deg <= hi + eps):
        raise ProfileValidationError(
            source=f"axis {axis_spec.letter}",
            detail=(
                f"commanded angle {deg:.4f}° (canonical "
                f"{math.degrees(canonical_rad):.4f}°, invert={axis_spec.invert}) "
                f"outside mechanical range {axis_spec.range_deg} and no "
                f"360°-equivalent pose fits either. Re-check the recipe's "
                f"print_orientation / wrap arc — the slicer refuses to emit "
                f"a line that would drive the rotary into a hard stop."
            ),
        )
    return f"{axis_spec.letter}{_fmt(deg, decimals=4)}"


def _calibration_token(calibrated_against: str) -> str:
    """Stable single-token form of a calibrated_against string for META.

    The free-text field stays prose-friendly; this token is what downstream
    machine consumers grep for.
    """
    s = calibrated_against.strip().lower()
    if s.startswith("uncalibrated") or "literature default" in s:
        return "uncalibrated"
    return "calibrated"


@dataclass(frozen=True)
class EmittedGCode:
    """Result of the emitter — text + the metadata that went into the header."""

    text: str
    total_bioink_uL_by_syringe: dict[int, float]
    estimated_seconds: float


def _meta_block(
    profile: MachineProfile,
    recipe: Recipe,
    syringes_by_id: dict[int, DisplacementSyringe],
    force_override: bool,
) -> list[str]:
    """Machine-readable header block. One key=value per line, grep-friendly."""
    # If any syringe carries an uncalibrated bioink or cell, the file-level
    # calibration token is "uncalibrated" — conservative composition.
    bioink_calibration = "calibrated"
    cells_calibration = "calibrated"
    for syr in syringes_by_id.values():
        if _calibration_token(syr.bioink.calibrated_against) == "uncalibrated":
            bioink_calibration = "uncalibrated"
        if _calibration_token(syr.cell_payload.calibrated_against) == "uncalibrated":
            cells_calibration = "uncalibrated"
    if recipe.bath is None:
        bath_calibration = "none"
    else:
        bath_calibration = _calibration_token(recipe.bath.calibrated_against)
    # Kinematic chain config — viewer needs this to apply the inverse
    # transform that turns machine-frame XYZ + A + C back into the part-
    # frame coordinates the print actually lives in. Without these,
    # 5-axis prints render as a degenerate stack of points because the
    # toolhead stays still while the bed rotates.
    tilt = profile.kinematic_chain.tilt
    swivel = profile.kinematic_chain.swivel
    tilt_lines = (
        [
            f";META: tilt_letter={tilt.letter}",
            f";META: tilt_axis={tilt.rotates_about}",
            f";META: tilt_invert={'true' if tilt.invert else 'false'}",
        ]
        if tilt is not None
        else [
            ";META: tilt_letter=none",
            ";META: tilt_axis=none",
            ";META: tilt_invert=false",
        ]
    )
    swivel_lines = (
        [
            f";META: swivel_letter={swivel.letter}",
            f";META: swivel_axis={swivel.rotates_about}",
            f";META: swivel_invert={'true' if swivel.invert else 'false'}",
        ]
        if swivel is not None
        else [
            ";META: swivel_letter=none",
            ";META: swivel_axis=none",
            ";META: swivel_invert=false",
        ]
    )
    return [
        f";META: bioink_calibration={bioink_calibration}",
        f";META: cells_calibration={cells_calibration}",
        f";META: bath_calibration={bath_calibration}",
        ";META: shear_model=newtonian_conservative",
        ";META: extrusion_mode=displacement",
        ";META: feed_token_semantics=cartesian_dominant",
        f";META: kinematic_chain={profile.kinematic_chain.kind}",
        *tilt_lines,
        *swivel_lines,
        f";META: firmware={profile.firmware}",
        f";META: safety_override={'true' if force_override else 'false'}",
        f";META: syringe_count={len(syringes_by_id)}",
    ]


def _safety_override_banner(stress_report: StressReport) -> list[str]:
    """Unmissable warning block listing every violating segment.

    Emitted only when `force=True` overrode at least one CellViabilityError.
    Future operators opening the file will see this before any G1 line.
    """
    lines = [
        ";",
        "; ============================================================",
        "; WARNING: SAFETY_OVERRIDE — cell-viability check was bypassed.",
        "; ============================================================",
        f"; {len(stress_report.violations)} segment(s) exceeded their cell-shear threshold.",
        "; This file MUST NOT be run on a cell-laden print without operator",
        "; review and an explicit acceptance of the override.",
        ";",
        "; Violating segments:",
    ]
    for v in stress_report.violations:
        lines.append(
            f";   {v.segment_id}: syringe={v.syringe_id} "
            f"computed={v.wall_shear_stress_pa:.1f} Pa "
            f"threshold={v.threshold_pa:.1f} Pa "
            f"(over by {v.wall_shear_stress_pa - v.threshold_pa:+.1f} Pa)"
        )
    lines.append("; ============================================================")
    return lines


def _header(
    profile: MachineProfile,
    recipe: Recipe,
    syringes_by_id: dict[int, DisplacementSyringe],
    stress_report: StressReport,
    total_volume_by_syringe: dict[int, float],
    estimated_seconds: float,
    force_override: bool,
) -> list[str]:
    lines: list[str] = []
    # `from datetime import UTC` is 3.11+ — lazy import lets the module load
    # cleanly on 3.10 (sandbox-only) while the actual call site uses the
    # idiomatic 3.11+ form. Production code paths run on 3.11+ per
    # pyproject.toml requires-python.
    try:
        from datetime import UTC
    except ImportError as exc:
        raise RuntimeError(
            "BioSlice5X G-code emission requires Python 3.11+. "
            "You're on Python "
            f"{__import__('sys').version_info[0]}.{__import__('sys').version_info[1]}. "
            "Install Python 3.11 or newer (see CONTRIBUTING.md §Python versions)."
        ) from exc

    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    chain_banner = (
        "5-axis tilt+swivel"
        if profile.kinematic_chain.kind == "tilt_swivel"
        else "3-axis baseline"
    )
    lines.append("; ============================================")
    lines.append(f"; BioSlice5X G-code ({chain_banner})")
    lines.append("; ============================================")
    lines.append(f"; Generated:           {now}")
    lines.append(f"; Profile:             {profile.name} ({profile.firmware})")
    lines.append(f"; Recipe:              {recipe.name}")
    lines.append(f"; Kinematic chain:     {profile.kinematic_chain.kind}")
    lines.append(";")
    lines.append("; ---- Bioink & cell payloads ----")
    for syringe_id in sorted(syringes_by_id):
        syr = syringes_by_id[syringe_id]
        lines.append(f"; Syringe {syringe_id}:")
        lines.append(f";   Bioink:            {syr.bioink.name}")
        lines.append(f";   Bioink calibrated: {syr.bioink.calibrated_against}")
        lines.append(f";   Rheology:          {syr.bioink.rheology.kind}")
        lines.append(f";   Cell type:         {syr.cell_payload.cell_type}")
        lines.append(f";   Cell density:      {syr.cell_payload.cell_density_per_mL:.2e} /mL")
        lines.append(f";   Cell calibrated:   {syr.cell_payload.calibrated_against}")
        lines.append(
            f";   Needle:            ID={syr.needle.inner_diameter_mm} mm, "
            f"L={syr.needle.length_mm} mm"
            + (f" ({syr.needle.gauge_label})" if syr.needle.gauge_label else "")
        )
        lines.append(f";   Barrel ID:         {syr.barrel_inner_diameter_mm} mm")
        lines.append(
            f";   Barrel:needle area ratio: {syr.barrel_to_needle_contraction_ratio():.1f}"
        )
        lines.append(f";   Temperature:       {syr.temperature_setpoint_c} C")
    lines.append(";")
    lines.append("; ---- Computed cell-stress summary ----")
    for syringe_id in sorted(syringes_by_id):
        observed = stress_report.max_by_syringe.get(syringe_id, 0.0)
        threshold = stress_report.threshold_by_syringe.get(syringe_id, 0.0)
        verdict = "OK" if observed <= threshold else "OVER (--force override)"
        lines.append(
            f"; Syringe {syringe_id} max wall shear: {observed:.1f} Pa  "
            f"(threshold: {threshold:.1f} Pa)  [{verdict}]"
        )
        lines.append(
            f"; Syringe {syringe_id} total bioink:    "
            f"{total_volume_by_syringe.get(syringe_id, 0.0):.2f} uL"
        )
    lines.append(f"; Estimated print time: {estimated_seconds:.1f} s")
    lines.append(";")
    lines.append("; ---- Caveats ----")
    lines.append("; - Wall shear stress is the Newtonian estimate with bulk viscosity.")
    lines.append("; - For shear-thinning bioinks, real wall stress may be lower; v2 corrects this.")
    lines.append("; - Single source of truth for axis convention is the machine profile YAML.")
    if profile.kinematic_chain.kind == "tilt_swivel":
        lines.append(
            "; - F tokens are firmware-cartesian (RRF interprets F against the move's"
        )
        lines.append(
            ";   total motion vector). On rotary-dominant conformal moves, deposition"
        )
        lines.append(
            ";   speed at the substrate may differ from F; verify with a one-perimeter"
        )
        lines.append(
            ";   dry-run before committing cells. Hardware-calibrated rotary-aware"
        )
        lines.append(";   F scaling is a v0.2.0 deliverable.")
    lines.append(";")
    lines.extend(_meta_block(profile, recipe, syringes_by_id, force_override))
    if force_override and stress_report.violations:
        lines.extend(_safety_override_banner(stress_report))
    return lines


def _startup_block(
    profile: MachineProfile,
    syringes_by_id: dict[int, DisplacementSyringe],
) -> list[str]:
    lines = [
        "G21       ; mm units",
        "G90       ; absolute positioning",
        "M83       ; relative extrusion",
    ]
    # Syringe-jacket temperature setpoints. RRF tool-mounted heater
    # convention: M104 S<temp> T<tool_id>. M109 (wait) is intentionally not
    # emitted in 2a/2b — operational wait/heating-resume is a 2d concern when
    # multi-syringe purge sequences land.
    for syringe_id in sorted(syringes_by_id):
        syr = syringes_by_id[syringe_id]
        lines.append(
            f"M104 S{_fmt(syr.temperature_setpoint_c, decimals=1)} T{syringe_id}  "
            f"; syringe {syringe_id} bioink temperature"
        )
    if profile.kinematic_chain.kind == "tilt_swivel":
        # 2b will populate this with operator confirmation; left as a TODO marker.
        lines.append(
            "; (Phase 2b) before printing, manually centre rotaries and confirm with G92 <letter>0"
        )
    return lines


def emit_rrf(
    moves: list[Move],
    profile: MachineProfile,
    recipe: Recipe,
    syringes_by_id: dict[int, DisplacementSyringe],
    stress_report: StressReport,
    *,
    force_override: bool = False,
) -> EmittedGCode:
    """Render moves + metadata into RRF G-code text."""
    # Tally extrusion totals & time estimate from moves.
    total_volume_by_syringe: dict[int, float] = dict.fromkeys(syringes_by_id, 0.0)
    estimated_seconds = 0.0
    for move in moves:
        if move.feed_mm_per_min > 0:
            estimated_seconds += (move.length_mm / move.feed_mm_per_min) * 60.0
        if not move.is_travel:
            total_volume_by_syringe[move.syringe_id] = (
                total_volume_by_syringe.get(move.syringe_id, 0.0) + move.extrusion_volume_uL
            )

    lines = _header(
        profile=profile,
        recipe=recipe,
        syringes_by_id=syringes_by_id,
        stress_report=stress_report,
        total_volume_by_syringe=total_volume_by_syringe,
        estimated_seconds=estimated_seconds,
        force_override=force_override,
    )
    lines.append("")
    lines.extend(_startup_block(profile, syringes_by_id))
    lines.append("; ---- start of print ----")
    tilt_spec = profile.kinematic_chain.tilt
    swivel_spec = profile.kinematic_chain.swivel
    # Per-segment shear lookup. Keyed by Move.segment_id; only extrusion
    # moves carry entries (travel/zero-flow moves are skipped by
    # validate_path). The viewer reads these back via the `;STRESS:`
    # token in the trailing comment — see visualization/preview.py.
    stress_by_segment: dict[str, float] = {
        s.segment_id: s.wall_shear_stress_pa for s in stress_report.per_segment
    }
    active_syringe_id: int | None = None
    retracted = False  # True between a retract and its un-retract pair

    def _emit_retract(syringe_id: int, travel_feed: float) -> None:
        """Volumetric retract before a travel — see Syringe.retract_volume_uL."""
        nonlocal retracted
        syr = syringes_by_id[syringe_id]
        if syr.retract_volume_uL <= 0.0 or retracted:
            return
        retract_mm = syr.volume_to_plunger_mm(syr.retract_volume_uL)
        lines.append(
            f"G1 E-{_fmt(retract_mm, decimals=5)} F{_fmt(travel_feed, decimals=1)}"
            f"  ; retract {syr.retract_volume_uL} uL"
        )
        retracted = True

    def _emit_unretract(syringe_id: int, travel_feed: float) -> None:
        """Match every retract with the inverse plunger advance."""
        nonlocal retracted
        syr = syringes_by_id[syringe_id]
        if syr.retract_volume_uL <= 0.0 or not retracted:
            return
        retract_mm = syr.volume_to_plunger_mm(syr.retract_volume_uL)
        lines.append(
            f"G1 E{_fmt(retract_mm, decimals=5)} F{_fmt(travel_feed, decimals=1)}"
            f"  ; un-retract {syr.retract_volume_uL} uL"
        )
        retracted = False

    last_extrusion_z: float | None = None
    for idx, move in enumerate(moves):
        # Tool-change: emit T<n> when switching syringes. Retract the
        # outgoing syringe before the change and un-retract the incoming
        # one after, so a multi-syringe bath print can't drag pressurized
        # bioink across the kerf.
        if move.syringe_id != active_syringe_id:
            if active_syringe_id is not None:
                _emit_retract(active_syringe_id, move.feed_mm_per_min)
            lines.append(f"T{move.syringe_id}  ; switch to syringe {move.syringe_id}")
            # Defensive: reset relative-E origin per tool so a misconfigured
            # M563/M584 mapping (both syringes on one stepper) cannot drift
            # accumulated displacement across tools.
            lines.append("G92 E0    ; reset relative-E origin for the active tool")
            active_syringe_id = move.syringe_id
            retracted = False  # un-retract handled implicitly by post-travel logic below
        plunger_mm = (
            syringes_by_id[move.syringe_id].volume_to_plunger_mm(move.extrusion_volume_uL)
            if not move.is_travel
            else 0.0
        )
        if move.is_travel:
            _emit_retract(move.syringe_id, move.feed_mm_per_min)
        tokens = [
            "G1",
            f"X{_fmt(move.end.x)}",
            f"Y{_fmt(move.end.y)}",
            f"Z{_fmt(move.end.z)}",
        ]
        # Insert A/C (or B/C, …) tokens after Z when the chain is 5-axis and
        # the move carries joint metadata. The letter and sign come from the
        # profile; the kinematics module produced canonical (tilt, swivel)
        # without knowing the letters.
        if move.joints is not None and tilt_spec is not None and swivel_spec is not None:
            joints: JointAngles = move.joints
            tokens.append(_axis_token(tilt_spec, joints.tilt_rad))
            tokens.append(_axis_token(swivel_spec, joints.swivel_rad))
        if not move.is_travel:
            tokens.append(f"E{_fmt(plunger_mm, decimals=5)}")
        tokens.append(f"F{_fmt(move.feed_mm_per_min, decimals=1)}")
        if move.is_travel:
            comment = (
                "  ; travel (sub-arc start)"
                if move.is_sub_arc_start
                else "  ; travel"
            )
        else:
            stress_pa = stress_by_segment.get(move.segment_id)
            comment = f"  ;STRESS:{_fmt(stress_pa, decimals=2)}" if stress_pa is not None else ""
            last_extrusion_z = move.end.z
        lines.append(" ".join(tokens) + comment)
        # Un-retract once we've arrived at the destination of a travel and
        # the next move is an extrusion — keeps the bioink column primed
        # against the meniscus before the print resumes.
        if move.is_travel:
            next_is_extrusion = (idx + 1) < len(moves) and not moves[idx + 1].is_travel
            if next_is_extrusion:
                _emit_unretract(move.syringe_id, move.feed_mm_per_min)
    # Final retract — leave the column unpressurized at end-of-print so the
    # bath does not back-pull bioink while the operator unloads.
    if active_syringe_id is not None:
        _emit_retract(active_syringe_id, recipe.slicing.travel_speed_mm_per_min)
    lines.append("; ---- end of print ----")
    # Safe park: clear the bath, return rotaries to home, drop heaters.
    # Operators routinely hit M84 mid-print to free a stuck plunger; doing
    # the park *before* M84 means the rotaries are at a known pose
    # regardless of where the print ended.
    park_z = (last_extrusion_z if last_extrusion_z is not None else 0.0) + (
        recipe.slicing.safe_park_clearance_mm
    )
    lines.append(
        f"G1 Z{_fmt(park_z, decimals=4)} F{_fmt(recipe.slicing.travel_speed_mm_per_min, decimals=1)}"
        "  ; safe-park Z (clear the bath before homing rotaries)"
    )
    if profile.kinematic_chain.kind == "tilt_swivel":
        tilt = profile.kinematic_chain.tilt
        swivel = profile.kinematic_chain.swivel
        # tilt+swivel == both present per KinematicChain validation.
        assert tilt is not None and swivel is not None
        home_tokens = ["G1"]
        home_tokens.append(f"{tilt.letter}0")
        home_tokens.append(f"{swivel.letter}0")
        home_tokens.append(f"F{_fmt(min(tilt.max_feed_deg_per_min, swivel.max_feed_deg_per_min), decimals=1)}")
        lines.append(" ".join(home_tokens) + "  ; rotaries home")
    for syringe_id in sorted(syringes_by_id):
        lines.append(
            f"M104 S0 T{syringe_id}  ; release syringe {syringe_id} thermal setpoint"
        )
    lines.append("M400      ; wait for moves to finish")
    lines.append("M84       ; disable motors")

    return EmittedGCode(
        text="\n".join(lines) + "\n",
        total_bioink_uL_by_syringe=total_volume_by_syringe,
        estimated_seconds=estimated_seconds,
    )


__all__ = ["EmittedGCode", "emit_rrf"]
