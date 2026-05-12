"""Phase 2b kinematic correctness tests.

Three property buckets exercised:

1. **Forward/inverse round-trip.** Sobol-grid coverage of valid
   (x, y, z, tilt, swivel) configurations: `inverse(forward(p)) == p` to
   numerical tolerance. If any one of the rotation conventions silently
   flips, this catches it.

2. **A = 0 singular pose.** Smooth-through interpolation across the
   degenerate band is the most-traveled code path in any real 5-axis
   print. Tests cover entry, mid-band, exit, all-in-band, and a sequence
   that never enters the band (no-op).

3. **`TiltSwivelAxis.invert` flag.** Same geometry, same canonical joints,
   one G-code with `invert=False` and one with `invert=True`. Verify only
   the A/C numeric signs flip — every other byte stays identical.
"""

from __future__ import annotations

import math
import sys
import warnings
from typing import Any, cast

import numpy as np
import pytest
import trimesh

from bioslice5x.kinematics.canonical import (
    JointAngles,
    machine_to_part_xyz,
    part_to_machine_xyz,
    rotation_matrix,
)
from bioslice5x.kinematics.chain import (
    ThreeAxisKinematics,
    TiltSwivelKinematics,
    kinematic_chain_from_profile,
)
from bioslice5x.kinematics.singularity import (
    find_singularity_spans,
    is_in_singular_band,
    smooth_through_singularity,
)
from bioslice5x.profile.loader import load_profile

# Tests that invoke `emit_rrf` (the invert-flag and B-letter integration
# tests at the bottom of this file) need Python 3.11+ for `datetime.UTC`.
# Mark per-function with `@_NEEDS_PY311` so the bulk of the kinematic
# tests (math + singularity, no rrf) still run on 3.10.
_NEEDS_PY311 = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="emit_rrf uses `from datetime import UTC` (Python 3.11+)",
)


# ---------------------------------------------------------------------------
# 1. Forward/inverse round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("axis", ["x", "y", "z"])
def test_zero_angle_rotation_is_identity(axis: str) -> None:
    m = rotation_matrix(cast(Any, axis), 0.0)
    assert np.allclose(m, np.eye(3))


def test_rotation_about_x_known_90_degrees() -> None:
    """Rotation by π/2 about X takes +Y to +Z, and +Z to -Y."""
    m = rotation_matrix("x", math.pi / 2)
    assert np.allclose(m @ np.array([0.0, 1.0, 0.0]), [0.0, 0.0, 1.0], atol=1e-12)
    assert np.allclose(m @ np.array([0.0, 0.0, 1.0]), [0.0, -1.0, 0.0], atol=1e-12)


def test_rotation_about_z_known_90_degrees() -> None:
    """Rotation by π/2 about Z takes +X to +Y, and +Y to -X."""
    m = rotation_matrix("z", math.pi / 2)
    assert np.allclose(m @ np.array([1.0, 0.0, 0.0]), [0.0, 1.0, 0.0], atol=1e-12)
    assert np.allclose(m @ np.array([0.0, 1.0, 0.0]), [-1.0, 0.0, 0.0], atol=1e-12)


@pytest.mark.parametrize(
    ("tilt_about", "swivel_about"),
    [
        ("x", "z"),  # Open5X Prusa
        ("y", "z"),  # Voron / Jubilee
        ("x", "y"),  # exotic but valid
        ("y", "x"),  # symmetry partner of (x, y)
        ("z", "x"),  # reversed roles
        ("z", "y"),  # reversed roles
    ],
)
def test_forward_inverse_round_trip_grid(tilt_about: str, swivel_about: str) -> None:
    """Inverse(Forward(p)) == p across a sampled grid of poses and joints.

    Sample size 2048 per config — sufficient to cover the kinematic space
    densely enough to catch sign-flip regressions that 64-sample tests would
    miss in the tails. Six (tilt_about, swivel_about) combinations exercise
    every pair of orthogonal world axes; the constraint `tilt_about !=
    swivel_about` is the only one TiltSwivelKinematics rejects.
    """
    rng = np.random.default_rng(42)
    n = 2048
    pts = rng.uniform(-50.0, 50.0, size=(n, 3))
    tilts = rng.uniform(-math.pi, math.pi, size=n)
    swivels = rng.uniform(-math.pi, math.pi, size=n)
    for p, a, c in zip(pts, tilts, swivels, strict=True):
        joints = JointAngles(tilt_rad=float(a), swivel_rad=float(c))
        machine = part_to_machine_xyz(
            (float(p[0]), float(p[1]), float(p[2])),
            joints,
            tilt_about=cast(Any, tilt_about),
            swivel_about=cast(Any, swivel_about),
        )
        back = machine_to_part_xyz(
            machine,
            joints,
            tilt_about=cast(Any, tilt_about),
            swivel_about=cast(Any, swivel_about),
        )
        assert np.allclose(back, p, atol=1e-9)


def test_three_axis_chain_is_identity() -> None:
    chain = ThreeAxisKinematics()
    joints = JointAngles(tilt_rad=0.5, swivel_rad=1.2)  # ignored
    assert chain.part_to_machine((1.0, 2.0, 3.0), joints) == (1.0, 2.0, 3.0)
    assert chain.machine_to_part((4.0, 5.0, 6.0), joints) == (4.0, 5.0, 6.0)


def test_tilt_swivel_chain_round_trip() -> None:
    chain = TiltSwivelKinematics(tilt_about="x", swivel_about="z")
    joints = JointAngles(tilt_rad=math.radians(30.0), swivel_rad=math.radians(45.0))
    part = (10.0, -5.0, 3.0)
    machine = chain.part_to_machine(part, joints)
    back = chain.machine_to_part(machine, joints)
    assert np.allclose(back, part, atol=1e-9)


def test_tilt_swivel_rejects_same_axis_for_both() -> None:
    with pytest.raises(ValueError, match="same axis"):
        TiltSwivelKinematics(tilt_about="z", swivel_about="z")


def test_chain_from_profile_constructs_right_kind() -> None:
    prusa = load_profile("open5x_prusa")
    voron = load_profile("open5x_voron")
    three_ax = load_profile("hypothetical_3axis")

    prusa_chain = kinematic_chain_from_profile(prusa)
    voron_chain = kinematic_chain_from_profile(voron)
    three_chain = kinematic_chain_from_profile(three_ax)

    assert isinstance(prusa_chain, TiltSwivelKinematics)
    assert prusa_chain.tilt_about == "x"
    assert prusa_chain.swivel_about == "z"

    assert isinstance(voron_chain, TiltSwivelKinematics)
    assert voron_chain.tilt_about == "y"
    assert voron_chain.swivel_about == "z"

    assert isinstance(three_chain, ThreeAxisKinematics)


# ---------------------------------------------------------------------------
# 2. A = 0 singularity smooth-through
# ---------------------------------------------------------------------------


def test_singular_band_detection_at_zero() -> None:
    assert is_in_singular_band(JointAngles(0.0, 0.0))
    assert is_in_singular_band(JointAngles(math.radians(1.0), 0.0))
    assert not is_in_singular_band(JointAngles(math.radians(3.0), 0.0))


def test_find_spans_isolated_band_in_middle() -> None:
    """Sequence: out, in, in, out → one span at [1:3]."""
    seq = [
        JointAngles(math.radians(10.0), math.radians(5.0)),
        JointAngles(math.radians(0.5), math.radians(20.0)),
        JointAngles(math.radians(-0.5), math.radians(40.0)),
        JointAngles(math.radians(10.0), math.radians(60.0)),
    ]
    spans = find_singularity_spans(seq)
    assert len(spans) == 1
    span = spans[0]
    assert (span.start_index, span.end_index) == (1, 3)
    # Entry swivel is sample[0].swivel; exit is sample[3].swivel.
    assert span.entry_swivel_rad == math.radians(5.0)
    assert span.exit_swivel_rad == math.radians(60.0)


def test_smooth_through_interpolates_swivel_linearly() -> None:
    """A=0 mid-print: swivel should ramp linearly across the singular band.

    Pre-smooth: swivel jumps 5° → 40° (out-of-band sample) but in the two
    in-band samples it's noisy. Post-smooth: those two in-band samples
    receive linearly interpolated swivel values 5° → 60°.
    """
    seq = [
        JointAngles(math.radians(10.0), math.radians(5.0)),  # out, before band
        JointAngles(math.radians(0.5), math.radians(20.0)),  # in band, noisy swivel
        JointAngles(math.radians(-0.5), math.radians(40.0)),  # in band, noisy swivel
        JointAngles(math.radians(10.0), math.radians(60.0)),  # out, after band
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        smoothed = smooth_through_singularity(seq)
    assert len(smoothed) == 4
    # Out-of-band samples are unchanged.
    assert smoothed[0] == seq[0]
    assert smoothed[3] == seq[3]
    # In-band tilts are preserved; swivels are interpolated.
    assert smoothed[1].tilt_rad == seq[1].tilt_rad
    assert smoothed[2].tilt_rad == seq[2].tilt_rad
    # Linear ramp 5° → 60° at t = 1/3 and 2/3.
    expected_1 = math.radians(5.0) + (math.radians(60.0) - math.radians(5.0)) * (1 / 3)
    expected_2 = math.radians(5.0) + (math.radians(60.0) - math.radians(5.0)) * (2 / 3)
    assert smoothed[1].swivel_rad == pytest.approx(expected_1, rel=1e-9)
    assert smoothed[2].swivel_rad == pytest.approx(expected_2, rel=1e-9)


def test_smooth_through_emits_warning() -> None:
    seq = [
        JointAngles(math.radians(10.0), math.radians(5.0)),
        JointAngles(math.radians(0.0), math.radians(20.0)),
        JointAngles(math.radians(10.0), math.radians(60.0)),
    ]
    with pytest.warns(RuntimeWarning, match="smooth-through"):
        smooth_through_singularity(seq)


def test_smooth_through_no_singularity_is_noop() -> None:
    seq = [
        JointAngles(math.radians(10.0), math.radians(5.0)),
        JointAngles(math.radians(20.0), math.radians(15.0)),
        JointAngles(math.radians(30.0), math.radians(25.0)),
    ]
    smoothed = smooth_through_singularity(seq)
    assert smoothed == seq


def test_smooth_through_length_one_interior_span_no_division_by_zero() -> None:
    """Single in-band sample sandwiched between two out-of-band neighbours.

    entry_index = 0, exit_index = 2, denominator = 2. The single in-band
    sample at index 1 is interpolated at t = 1/2 — the midpoint of the
    entry and exit swivels.
    """
    seq = [
        JointAngles(math.radians(10.0), math.radians(10.0)),
        JointAngles(math.radians(0.0), math.radians(99.0)),  # length-one band
        JointAngles(math.radians(10.0), math.radians(50.0)),
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        smoothed = smooth_through_singularity(seq)
    assert smoothed[0] == seq[0]
    assert smoothed[2] == seq[2]
    assert smoothed[1].tilt_rad == seq[1].tilt_rad
    assert smoothed[1].swivel_rad == pytest.approx(math.radians(30.0), rel=1e-9)


def test_smooth_through_length_one_at_start_preserves_sample() -> None:
    """In-band sample at index 0 only.

    entry_index = 0 (sample is its own entry), exit_index = 1, denominator = 1.
    The sample at index 0 is skipped (k == entry_index). No change.
    """
    seq = [
        JointAngles(math.radians(0.0), math.radians(42.0)),
        JointAngles(math.radians(10.0), math.radians(99.0)),
    ]
    smoothed = smooth_through_singularity(seq, warn=False)
    assert smoothed == seq


def test_smooth_through_length_one_at_end_preserves_sample() -> None:
    """In-band sample at the last index only — symmetric to at-start."""
    seq = [
        JointAngles(math.radians(10.0), math.radians(42.0)),
        JointAngles(math.radians(0.0), math.radians(99.0)),
    ]
    smoothed = smooth_through_singularity(seq, warn=False)
    assert smoothed == seq


def test_smooth_through_single_sample_whole_sequence_in_band() -> None:
    """Whole sequence is one in-band sample.

    entry_index == exit_index — the degenerate case caught by the explicit
    guard in smooth_through_singularity. Passes through unchanged.
    """
    seq = [JointAngles(math.radians(0.0), math.radians(42.0))]
    smoothed = smooth_through_singularity(seq, warn=False)
    assert smoothed == seq


def test_smooth_through_all_in_band_no_anchor_uses_endpoints() -> None:
    """When the entire sequence is in the singular band, there is no
    out-of-band anchor; the span uses its own endpoints for entry/exit. The
    interior samples then linearly interpolate between those endpoint swivels.
    """
    seq = [
        JointAngles(math.radians(0.5), math.radians(0.0)),
        JointAngles(math.radians(0.0), math.radians(50.0)),  # noisy
        JointAngles(math.radians(-0.5), math.radians(90.0)),
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        smoothed = smooth_through_singularity(seq)
    # Endpoints are the only anchors; the interior sample's swivel is
    # interpolated between sample[0].swivel=0 and sample[-1].swivel=90.
    assert smoothed[0].swivel_rad == math.radians(0.0)
    assert smoothed[2].swivel_rad == math.radians(90.0)
    assert smoothed[1].swivel_rad == pytest.approx(math.radians(45.0), rel=1e-9)


# ---------------------------------------------------------------------------
# 3. TiltSwivelAxis.invert flag — same path, only signs flip
# ---------------------------------------------------------------------------


def _cube_mesh(size_mm: float = 6.0) -> trimesh.Trimesh:
    cube: Any = trimesh.creation.box(extents=[size_mm, size_mm, size_mm])
    cube.apply_translation([0.0, 0.0, size_mm / 2.0])
    return cast(trimesh.Trimesh, cube)


def _slice_with_invert(*, invert_tilt: bool, invert_swivel: bool) -> str:
    """Slice a cube with the open5x_prusa profile, optionally inverting axes.

    Returns the G-code text. Only the profile's invert flags vary between
    invocations; everything else is held constant.
    """
    from bioslice5x import Slicer
    from bioslice5x.profile.models import (
        BuildVolume,
        KinematicChain,
        MachineProfile,
        TiltSwivelAxis,
    )
    from bioslice5x.recipe.models import (
        FixedOrientation,
        Needle,
        Recipe,
        SlicingParams,
        Syringe,
    )

    profile = MachineProfile(
        name="invert_test",
        firmware="rrf",
        build_volume=BuildVolume(x_mm=(-50.0, 50.0), y_mm=(-50.0, 50.0), z_mm=(-10.0, 50.0)),
        kinematic_chain=KinematicChain(
            kind="tilt_swivel",
            tilt=TiltSwivelAxis(
                rotates_about="x",
                letter="A",
                invert=invert_tilt,
                range_deg=(-200.0, 200.0),
            ),
            swivel=TiltSwivelAxis(
                rotates_about="z",
                letter="C",
                invert=invert_swivel,
                range_deg=(-360.0, 360.0),
            ),
        ),
    )
    recipe = Recipe(
        name="invert_test_cube",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7, gauge_label="18G"),
            )
        ],
        slicing=SlicingParams(layer_height_mm=0.4, line_width_mm=0.5, print_speed_mm_per_min=60.0),
        print_orientation=FixedOrientation(tilt_deg=30.0, swivel_deg=45.0),
    )
    return Slicer(profile=profile, recipe=recipe).slice(_cube_mesh()).gcode


@_NEEDS_PY311
def test_invert_flag_flips_only_axis_signs() -> None:
    """invert=True must change *only* the sign of A and C tokens. Everything
    else (X, Y, Z, E, F, comments, header) must be byte-identical.
    """
    base = _slice_with_invert(invert_tilt=False, invert_swivel=False)
    inv = _slice_with_invert(invert_tilt=True, invert_swivel=True)
    base_lines = base.splitlines()
    inv_lines = inv.splitlines()
    assert len(base_lines) == len(inv_lines)
    differences = 0
    for b, i in zip(base_lines, inv_lines, strict=True):
        if b == i:
            continue
        differences += 1
        # The META block carries `tilt_invert=...` / `swivel_invert=...`
        # so the viewer can apply the inverse transform. Those lines
        # legitimately differ when the flag flips; everything else that
        # differs must be a G1 line where only A and C signs change.
        if b.startswith(";META: tilt_invert=") or b.startswith(";META: swivel_invert="):
            assert i.startswith(b[: b.index("=") + 1])
            continue
        assert b.startswith("G1"), (b, i)
        assert i.startswith("G1"), (b, i)
        b_toks = b.split()
        i_toks = i.split()
        assert len(b_toks) == len(i_toks)
        for bt, it in zip(b_toks, i_toks, strict=True):
            if bt == it:
                continue
            letter = bt[0]
            assert letter in ("A", "C"), f"non-axis token differs: {bt!r} vs {it!r}"
            assert float(bt[1:]) == pytest.approx(-float(it[1:]), abs=1e-9)
    # We expect every G1 print line to differ (and only those + the two
    # META lines for the invert flags).
    assert differences > 0


@_NEEDS_PY311
def test_invert_tilt_only() -> None:
    """Inverting only tilt should flip only A, not C."""
    base = _slice_with_invert(invert_tilt=False, invert_swivel=False)
    inv = _slice_with_invert(invert_tilt=True, invert_swivel=False)
    for b, i in zip(base.splitlines(), inv.splitlines(), strict=True):
        if not b.startswith("G1") or b == i:
            continue
        b_toks = b.split()
        i_toks = i.split()
        for bt, it in zip(b_toks, i_toks, strict=True):
            if bt == it:
                continue
            assert bt[0] == "A", f"only A should differ when only tilt is inverted, got {bt!r}"


@_NEEDS_PY311
def test_invert_with_zero_canonical_angle_emits_plain_zero() -> None:
    """`invert=True` applied to a zero canonical angle must not leak `-0.0`
    into the G-code. The `_fmt` helper short-circuits on `value == 0.0`
    (which is `True` for both `+0.0` and `-0.0` in IEEE-754) and returns the
    bare token `"A0"`, not `"A-0.0000"`.

    String-comparison flakiness around negative zero is a classic bug in
    sign-flip code; this test pins the behaviour explicitly.
    """
    from bioslice5x import Slicer
    from bioslice5x.profile.models import (
        BuildVolume,
        KinematicChain,
        MachineProfile,
        TiltSwivelAxis,
    )
    from bioslice5x.recipe.models import (
        FixedOrientation,
        Needle,
        Recipe,
        SlicingParams,
        Syringe,
    )

    profile = MachineProfile(
        name="negzero_test",
        firmware="rrf",
        build_volume=BuildVolume(x_mm=(-50.0, 50.0), y_mm=(-50.0, 50.0), z_mm=(-10.0, 50.0)),
        kinematic_chain=KinematicChain(
            kind="tilt_swivel",
            tilt=TiltSwivelAxis(
                rotates_about="x", letter="A", invert=True, range_deg=(-200.0, 200.0)
            ),
            swivel=TiltSwivelAxis(
                rotates_about="z", letter="C", invert=True, range_deg=(-360.0, 360.0)
            ),
        ),
    )
    recipe = Recipe(
        name="zero_orientation",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7),
            )
        ],
        slicing=SlicingParams(layer_height_mm=0.4, line_width_mm=0.5, print_speed_mm_per_min=60.0),
        # Zero canonical orientation + invert flags ⇒ the postprocessor
        # negates zero. The result must NOT contain "A-0" or "C-0".
        print_orientation=FixedOrientation(tilt_deg=0.0, swivel_deg=0.0),
    )
    gcode = Slicer(profile=profile, recipe=recipe).slice(_cube_mesh()).gcode
    # No "-0" prefixed by either A or C anywhere in the G-code.
    for line in gcode.splitlines():
        if not line.startswith("G1 "):
            continue
        for tok in line.split():
            if tok.startswith(("A", "C")) and tok != "C0" and tok != "A0":
                # Permit tokens like "A0" / "C0" only; anything else with
                # those letters must not begin with a negative sign on a
                # zero-valued joint.
                assert not tok.startswith("A-0"), f"negative zero in A token: {tok!r}"
                assert not tok.startswith("C-0"), f"negative zero in C token: {tok!r}"


@_NEEDS_PY311
def test_voron_profile_emits_B_letter() -> None:
    """Sanity-check that the Voron profile emits 'B' for the tilt token, not 'A'."""
    from bioslice5x import Slicer
    from bioslice5x.recipe.models import (
        FixedOrientation,
        Needle,
        Recipe,
        SlicingParams,
        Syringe,
    )

    profile = load_profile("open5x_voron")
    recipe = Recipe(
        name="voron_test",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7, gauge_label="18G"),
            )
        ],
        slicing=SlicingParams(layer_height_mm=0.4, line_width_mm=0.5, print_speed_mm_per_min=60.0),
        print_orientation=FixedOrientation(tilt_deg=15.0, swivel_deg=10.0),
    )
    gcode = Slicer(profile=profile, recipe=recipe).slice(_cube_mesh()).gcode
    g1_with_tokens = [
        line for line in gcode.splitlines() if line.startswith("G1 ") and " B" in line
    ]
    assert g1_with_tokens, "expected at least one G1 line carrying a B token"
    # And there should be no A tokens on G1 lines (this is a B+C profile).
    for line in gcode.splitlines():
        if line.startswith("G1 "):
            assert " A" not in line, f"unexpected A token on Voron profile: {line!r}"
