"""Pin the worked examples in docs/PHASE_2B_NOTES.md against drift.

The doc has prose-form numerical examples for both the A+C (Prusa) and B+C
(Voron) profiles, including the expected machine-frame coordinates for a
specific part-frame vertex and joint configuration. Prose drifts the first
time someone touches the kinematics math; this test pulls those values
through the real chain + postprocessor and asserts they match.

If you change the kinematic math or convention and these break: update
PHASE_2B_NOTES.md to match, *then* update this test.
"""

from __future__ import annotations

import math
import sys

import numpy as np
import pytest

from bioslice5x.kinematics.canonical import JointAngles
from bioslice5x.kinematics.chain import kinematic_chain_from_profile
from bioslice5x.postprocessor.rrf import _axis_token
from bioslice5x.profile.loader import load_profile

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="postprocessor._axis_token indirectly depends on emit_rrf chain via package init "
    "with `datetime.UTC` (Python 3.11+); tests run on CI 3.11/3.12.",
)

# The shared example: part-frame vertex (10, 0, 5), joints (30°, 45°).
PART_VERTEX = (10.0, 0.0, 5.0)
TILT_DEG = 30.0
SWIVEL_DEG = 45.0


def _joints() -> JointAngles:
    return JointAngles(
        tilt_rad=math.radians(TILT_DEG),
        swivel_rad=math.radians(SWIVEL_DEG),
    )


def test_prusa_worked_example_machine_xyz() -> None:
    """PHASE_2B_NOTES.md §2: R_x(π/6) · R_z(π/4) · (10, 0, 5) ≈ (7.071, 3.624, 7.866).

    Step by step:
      R_z(45°) · (10, 0, 5) = (7.0711, 7.0711, 5)
      R_x(30°) · (7.0711, 7.0711, 5)
          = (7.0711, 7.0711·cos30 - 5·sin30, 7.0711·sin30 + 5·cos30)
          = (7.0711, 6.1237 - 2.5, 3.5355 + 4.3301)
          = (7.0711, 3.6237, 7.8657)
    """
    prusa = load_profile("open5x_prusa")
    chain = kinematic_chain_from_profile(prusa)
    machine = chain.part_to_machine(PART_VERTEX, _joints())
    assert np.allclose(machine, (7.0711, 3.6237, 7.8657), atol=1e-3)


def test_voron_worked_example_machine_xyz() -> None:
    """PHASE_2B_NOTES.md §3: R_y(π/6) · R_z(π/4) · (10, 0, 5) ≈ (8.624, 7.071, 0.795).

    Step by step:
      R_z(45°) · (10, 0, 5) = (7.0711, 7.0711, 5)
      R_y(30°) · (7.0711, 7.0711, 5)
          = (7.0711·cos30 + 5·sin30, 7.0711, -7.0711·sin30 + 5·cos30)
          = (6.1237 + 2.5, 7.0711, -3.5355 + 4.3301)
          = (8.6237, 7.0711, 0.7946)
    """
    voron = load_profile("open5x_voron")
    chain = kinematic_chain_from_profile(voron)
    machine = chain.part_to_machine(PART_VERTEX, _joints())
    assert np.allclose(machine, (8.6237, 7.0711, 0.7946), atol=1e-3)


def test_prusa_worked_example_emitted_axis_tokens() -> None:
    """The G-code A and C tokens at joints (30°, 45°) on the Prusa profile."""
    prusa = load_profile("open5x_prusa")
    assert prusa.kinematic_chain.tilt is not None
    assert prusa.kinematic_chain.swivel is not None
    joints = _joints()
    a_token = _axis_token(prusa.kinematic_chain.tilt, joints.tilt_rad)
    c_token = _axis_token(prusa.kinematic_chain.swivel, joints.swivel_rad)
    assert a_token == "A30"
    assert c_token == "C45"


def test_voron_worked_example_emitted_axis_tokens() -> None:
    """Same canonical joints, B+C profile — letters differ but values match."""
    voron = load_profile("open5x_voron")
    assert voron.kinematic_chain.tilt is not None
    assert voron.kinematic_chain.swivel is not None
    joints = _joints()
    b_token = _axis_token(voron.kinematic_chain.tilt, joints.tilt_rad)
    c_token = _axis_token(voron.kinematic_chain.swivel, joints.swivel_rad)
    assert b_token == "B30"
    assert c_token == "C45"


def test_invert_flag_worked_example() -> None:
    """PHASE_2B_NOTES.md §4: with `invert: true` on the tilt axis and the
    example joints, the A token becomes A-30 while C is unchanged."""
    prusa = load_profile("open5x_prusa")
    assert prusa.kinematic_chain.tilt is not None
    inverted = prusa.kinematic_chain.tilt.model_copy(update={"invert": True})
    joints = _joints()
    a_token = _axis_token(inverted, joints.tilt_rad)
    assert a_token == "A-30"


def test_pytest_approx_pins_machine_xyz_components() -> None:
    """Tighter pinning of the Prusa worked-example coordinates than the
    doc-rounded 3-decimal display values. If the canonical-math
    implementation ever changes its sign or order of operations, this is
    the first thing that breaks.
    """
    prusa = load_profile("open5x_prusa")
    chain = kinematic_chain_from_profile(prusa)
    x, y, z = chain.part_to_machine(PART_VERTEX, _joints())
    # R_z(45°): (10, 0, 5) → (10·cos45, 10·sin45, 5) = (7.0710678, 7.0710678, 5)
    # R_x(30°): (7.0710678, 7.0710678·cos30 - 5·sin30, 7.0710678·sin30 + 5·cos30)
    #        = (7.0710678, 7.0710678·0.866 - 2.5, 3.5355339 + 4.330127)
    #        = (7.0710678, 6.1237 - 2.5, 7.8657)
    expected_x = 10.0 * math.cos(math.radians(45.0))
    expected_y = 10.0 * math.sin(math.radians(45.0)) * math.cos(
        math.radians(30.0)
    ) - 5.0 * math.sin(math.radians(30.0))
    expected_z = 10.0 * math.sin(math.radians(45.0)) * math.sin(
        math.radians(30.0)
    ) + 5.0 * math.cos(math.radians(30.0))
    assert x == pytest.approx(expected_x, rel=1e-12)
    assert y == pytest.approx(expected_y, rel=1e-12)
    assert z == pytest.approx(expected_z, rel=1e-12)
