"""Byte-for-byte regression lock for flat-mode (Phase 2a) G-code output.

The Phase 2c Slicer dispatches between flat and conformal slicing modes.
This is the first time flat-mode output is generated through a branch
rather than directly, and any inadvertent change to that branch would
break existing 2b-validated print recipes silently. This test captures
the canonical safe-recipe cube output as a golden file and asserts
identity (modulo the volatile `Generated:` timestamp).

If you intentionally change the flat-mode pipeline output (e.g., add a
new META field, change G1 token order, add a new comment line), you
**must** regenerate the golden file by setting `BIOSLICE5X_REGEN_GOLDEN=1`
and re-running pytest. The regeneration is visible in the diff against
the checked-in `flat_mode_2a_cube.gcode.golden`.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, cast

import pytest
import trimesh

from bioslice5x import Slicer, load_profile
from bioslice5x.recipe.models import Needle, Recipe, SlicingParams, Syringe

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="emit_rrf uses `from datetime import UTC` which is Python 3.11+",
)

GOLDEN_PATH = Path(__file__).parent / "golden" / "flat_mode_2a_cube.gcode.golden"

# The `Generated:` timestamp in the header is the only intentionally
# non-deterministic line. Strip it before comparison.
TIMESTAMP_RE = re.compile(r"^; Generated:.*$", flags=re.MULTILINE)


def _cube_mesh(size_mm: float = 6.0) -> trimesh.Trimesh:
    cube: Any = trimesh.creation.box(extents=[size_mm, size_mm, size_mm])
    cube.apply_translation([0.0, 0.0, size_mm / 2.0])
    return cast(trimesh.Trimesh, cube)


def _canonical_safe_recipe() -> Recipe:
    """The same recipe that test_end_to_end_2a uses for its safe path."""
    return Recipe(
        name="phase_2a_cube",
        syringes=[
            Syringe(
                id=0,
                bioink="collagen_i_8mg_per_mL",
                cell_payload="general_mammalian",
                needle=Needle(inner_diameter_mm=0.84, length_mm=12.7, gauge_label="18G"),
                barrel_inner_diameter_mm=4.65,
                total_volume_uL=1000.0,
            )
        ],
        slicing=SlicingParams(
            layer_height_mm=0.4,
            line_width_mm=0.5,
            print_speed_mm_per_min=60.0,
        ),
    )


def _normalize(gcode: str) -> str:
    """Replace the timestamp line with a fixed placeholder."""
    return TIMESTAMP_RE.sub("; Generated:           <TIMESTAMP>", gcode)


def _current_output() -> str:
    profile = load_profile("hypothetical_3axis")
    result = Slicer(profile=profile, recipe=_canonical_safe_recipe()).slice(_cube_mesh())
    return _normalize(result.gcode)


def test_flat_mode_output_matches_golden() -> None:
    """Diff current flat-mode output against the checked-in golden.

    Failure modes:
    - Intentional change (META field, new comment, etc.): regenerate the
      golden via `BIOSLICE5X_REGEN_GOLDEN=1 pytest tests/test_flat_mode_golden.py`
      and review the diff.
    - Unintentional change (broken dispatch, wrong joint inserted, etc.):
      this is the silent breakage we're guarding against. Fix the code.
    """
    if os.environ.get("BIOSLICE5X_REGEN_GOLDEN") == "1":
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(_current_output(), encoding="utf-8")
        pytest.skip("regenerated golden; re-run without BIOSLICE5X_REGEN_GOLDEN to verify")
    if not GOLDEN_PATH.is_file():
        pytest.skip(
            f"golden file {GOLDEN_PATH} not present — generate it via "
            "BIOSLICE5X_REGEN_GOLDEN=1 pytest"
        )
    expected = GOLDEN_PATH.read_text(encoding="utf-8")
    actual = _current_output()
    assert actual == expected, (
        "Flat-mode G-code output differs from golden. "
        "If this change is intentional, regenerate via BIOSLICE5X_REGEN_GOLDEN=1 "
        "and review the diff."
    )
