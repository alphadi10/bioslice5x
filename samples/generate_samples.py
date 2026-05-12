#!/usr/bin/env python3
"""Generate the sample meshes referenced in `docs/tutorial/quickstart.md`.

Procedural generation (not checked-in binaries) keeps the repo small and
the meshes editable. Run once after cloning:

    uv run python samples/generate_samples.py

Produces:
    samples/cube_10mm.stl
    samples/cylinder_5mm_radius_10mm_tall.stl
    samples/chips_pancreatic_envelope.stl       # CHIPS T1D reference envelope
    samples/vascular_scaffold.stl               # 5-axis rotational test fixture
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import trimesh


def _cube(size_mm: float = 10.0) -> trimesh.Trimesh:
    cube: Any = trimesh.creation.box(extents=[size_mm, size_mm, size_mm])
    cube.apply_translation([0.0, 0.0, size_mm / 2.0])
    return cast(trimesh.Trimesh, cube)


def _cylinder(radius_mm: float = 5.0, height_mm: float = 10.0) -> trimesh.Trimesh:
    cyl: Any = trimesh.creation.cylinder(radius=radius_mm, height=height_mm, sections=64)
    cyl.apply_translation([0.0, 0.0, height_mm / 2.0])
    return cast(trimesh.Trimesh, cyl)


def _chips_pancreatic_envelope(radius_mm: float = 10.0, height_mm: float = 4.0) -> trimesh.Trimesh:
    """Centimeter-scale pill envelope approximating the CHIPS pancreatic construct.

    The published CHIPS pancreatic-like construct (Shiwarski et al. 2025
    Science Advances DOI 10.1126/sciadv.adu5905) is a centimeter-scale
    disc with an internal fibrin/MIN6 core and a type-I collagen shell
    surrounding it, plus ~100 µm perfusable channels. v0.1.x cannot
    represent the channels (requires the v0.1.1 submesh region selector
    and the v0.2.x conformal-infill channel writer); the envelope is the
    starting point and the recipe at `samples/chips_pancreatic_recipe.yaml`
    is loud about which CHIPS features it does and does not yet exercise.
    """
    pill: Any = trimesh.creation.cylinder(radius=radius_mm, height=height_mm, sections=96)
    pill.apply_translation([0.0, 0.0, height_mm / 2.0])
    return cast(trimesh.Trimesh, pill)


def _vascular_scaffold(
    radius_mm: float = 5.0, height_mm: float = 20.0, sections: int = 96
) -> trimesh.Trimesh:
    """Tall thin-walled cylinder — vascular-graft-scale rotational fixture.

    The wrap-around-axis conformal slicer uses `cylinder_radius_mm` from
    the recipe and the mesh's axial extent (z-min to z-max). A taller-
    than-wide cylinder maximises the number of axial layers per pass,
    exercising 5-axis G-code emission across many distinct (tilt,
    swivel) combinations in a single print.

    20 mm tall × 5 mm radius is realistic for a vascular-graft test
    section in the FRESH literature (Feinberg lab and others routinely
    print constructs in this range). 96-section faceting keeps the
    mesh smooth enough that the conformal slicer's axial extent
    detection is unambiguous.
    """
    cyl: Any = trimesh.creation.cylinder(radius=radius_mm, height=height_mm, sections=sections)
    cyl.apply_translation([0.0, 0.0, height_mm / 2.0])
    return cast(trimesh.Trimesh, cyl)


def main() -> int:
    out = Path(__file__).resolve().parent
    out.mkdir(exist_ok=True)
    _cube(10.0).export(out / "cube_10mm.stl")
    _cylinder(5.0, 10.0).export(out / "cylinder_5mm_radius_10mm_tall.stl")
    _chips_pancreatic_envelope(10.0, 4.0).export(out / "chips_pancreatic_envelope.stl")
    _vascular_scaffold(5.0, 20.0).export(out / "vascular_scaffold.stl")
    print(f"wrote: {out / 'cube_10mm.stl'}")
    print(f"wrote: {out / 'cylinder_5mm_radius_10mm_tall.stl'}")
    print(f"wrote: {out / 'chips_pancreatic_envelope.stl'}")
    print(f"wrote: {out / 'vascular_scaffold.stl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
