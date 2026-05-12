#!/usr/bin/env python3
"""Regenerate the bundled sample G-code artifacts at the repo root.

These files are demos / documentation, not source code — but committing
them lets readers see what the slicer emits without running it. The risk
is staleness: a change to the emitter that doesn't break tests can leave
the bundled `.gcode` files lying about. Run this script after any change
to the slicer or post-processor and commit the result alongside the code
change. CI does not pin these (the byte-for-byte regression-locked file
is at `tests/golden/flat_mode_2a_cube.gcode.golden`); this script is the
audit trail for the human-facing samples.

Run from the repo root:

    uv run python scripts/regen_sample_gcode.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

import trimesh

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from bioslice5x import Slicer, load_profile  # noqa: E402
from bioslice5x.recipe.models import (  # noqa: E402
    FixedOrientation,
    Needle,
    Recipe,
    SlicingParams,
    Syringe,
    WrapAroundAxisSlicing,
)


def _cube_mesh(size_mm: float = 6.0) -> trimesh.Trimesh:
    cube: Any = trimesh.creation.box(extents=[size_mm, size_mm, size_mm])
    cube.apply_translation([0.0, 0.0, size_mm / 2.0])
    return cast(trimesh.Trimesh, cube)


def _cylinder_mesh(radius_mm: float = 5.0, height_mm: float = 20.0) -> trimesh.Trimesh:
    cyl: Any = trimesh.creation.cylinder(radius=radius_mm, height=height_mm, sections=96)
    cyl.apply_translation([0.0, 0.0, height_mm / 2.0])
    return cast(trimesh.Trimesh, cyl)


def _safe_cube_recipe() -> Recipe:
    return Recipe(
        name="cube_demo",
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
        ),
    )


def _tilted_cube_recipe() -> Recipe:
    return Recipe(
        name="tilted_cube_demo",
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
        ),
        print_orientation=FixedOrientation(tilt_deg=30.0, swivel_deg=0.0),
    )


def _cylinder_conformal_recipe() -> Recipe:
    return Recipe(
        name="cylinder_conformal_demo",
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
            mode=WrapAroundAxisSlicing(
                wrap_axis="z",
                cylinder_radius_mm=5.0,
            ),
        ),
        print_orientation=FixedOrientation(),
    )


def main() -> int:
    print("Regenerating bundled sample G-code artifacts...")
    three_axis = load_profile("hypothetical_3axis")
    prusa = load_profile("open5x_prusa")

    cube_out = _REPO_ROOT / "cube.gcode"
    Slicer(profile=three_axis, recipe=_safe_cube_recipe()).slice(_cube_mesh()).write_gcode(cube_out)
    print(f"  wrote {cube_out.name}")

    tilted_out = _REPO_ROOT / "tilted_cube.gcode"
    Slicer(profile=prusa, recipe=_tilted_cube_recipe()).slice(_cube_mesh()).write_gcode(tilted_out)
    print(f"  wrote {tilted_out.name}")

    cyl_out = _REPO_ROOT / "cylinder.gcode"
    Slicer(profile=prusa, recipe=_cylinder_conformal_recipe()).slice(
        _cylinder_mesh()
    ).write_gcode(cyl_out)
    print(f"  wrote {cyl_out.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
