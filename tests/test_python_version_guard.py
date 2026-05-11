"""Pin the Python-3.11+ runtime guard.

`emit_rrf` does `from datetime import UTC` lazily inside the header
builder. On Python < 3.11 that import fails; we wrap it in a try/except
and raise a clear `RuntimeError` pointing the user at CONTRIBUTING.md.

This test verifies the guard's behaviour:

- On Python ≥ 3.11: the lazy import succeeds, no RuntimeError, the
  function runs (we don't validate the full output here — other end-to-end
  tests do that). This branch is `skipif(< 3.11)`.
- On Python < 3.11: the lazy import fails; the function raises
  RuntimeError naming the version requirement and CONTRIBUTING.md.

If this test ever passes on 3.10 without raising, the guard regressed
silently — that's a more dangerous failure mode than an emit_rrf
ImportError because a downstream caller might catch ImportError and
silently fall through.
"""

from __future__ import annotations

import sys

import pytest


@pytest.mark.skipif(sys.version_info >= (3, 11), reason="Guard only fires on Python < 3.11.")
def test_emit_rrf_raises_clear_error_on_python_310() -> None:
    """On Python 3.10 the lazy UTC import fails; emit_rrf re-raises as
    RuntimeError with a clear message naming the required version."""
    from bioslice5x.bioink.models import Bioink, CellPayload, RheologicalModel
    from bioslice5x.extruder.syringe import DisplacementSyringe
    from bioslice5x.extruder.validate import StressReport
    from bioslice5x.postprocessor.rrf import emit_rrf
    from bioslice5x.profile.models import BuildVolume, KinematicChain, MachineProfile
    from bioslice5x.recipe.models import Needle, Recipe, SlicingParams, Syringe

    profile = MachineProfile(
        name="t",
        build_volume=BuildVolume(x_mm=(0, 50), y_mm=(0, 50), z_mm=(0, 50)),
        kinematic_chain=KinematicChain(kind="three_axis"),
    )
    bioink = Bioink(
        name="x",
        density_g_per_mL=1.0,
        rheology=RheologicalModel(kind="newtonian", viscosity_pa_s=1.0),
        working_temperature_c=(4.0, 37.0),
        crosslinking="none",
    )
    cells = CellPayload(
        name="c", cell_type="t", cell_density_per_mL=1.0e6, max_wall_shear_stress_pa=5000.0
    )
    syringe = DisplacementSyringe(
        syringe_id=0,
        barrel_inner_diameter_mm=4.65,
        total_volume_uL=1000.0,
        needle=Needle(inner_diameter_mm=0.84, length_mm=12.7),
        bioink=bioink,
        cell_payload=cells,
        temperature_setpoint_c=20.0,
    )
    recipe = Recipe(
        name="r",
        syringes=[
            Syringe(
                id=0,
                bioink="x",
                cell_payload="c",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7),
            )
        ],
        slicing=SlicingParams(),
    )
    stress = StressReport(per_segment=(), max_by_syringe={0: 0.0}, threshold_by_syringe={0: 5000.0})
    with pytest.raises(RuntimeError, match=r"3\.11"):
        emit_rrf(
            moves=[],
            profile=profile,
            recipe=recipe,
            syringes_by_id={0: syringe},
            stress_report=stress,
        )


@pytest.mark.skipif(sys.version_info < (3, 11), reason="Sanity-check for 3.11+ only.")
def test_emit_rrf_no_runtime_error_on_python_311_plus() -> None:
    """On Python 3.11+ the guard's exception path is unreachable.

    We don't run the full emit_rrf here — other end-to-end tests do. We
    just verify `from datetime import UTC` succeeds, which is what the
    guard wraps.
    """
    from datetime import UTC

    assert UTC is not None
