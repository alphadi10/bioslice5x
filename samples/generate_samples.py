#!/usr/bin/env python3
"""Generate the sample meshes referenced in `docs/tutorial/quickstart.md`.

Procedural generation (not checked-in binaries) keeps the repo small and
the meshes editable. Run once after cloning:

    uv run python samples/generate_samples.py

Produces:
    samples/cube_10mm.stl
    samples/cylinder_5mm_radius_10mm_tall.stl
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


def main() -> int:
    out = Path(__file__).resolve().parent
    out.mkdir(exist_ok=True)
    _cube(10.0).export(out / "cube_10mm.stl")
    _cylinder(5.0, 10.0).export(out / "cylinder_5mm_radius_10mm_tall.stl")
    print(f"wrote: {out / 'cube_10mm.stl'}")
    print(f"wrote: {out / 'cylinder_5mm_radius_10mm_tall.stl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
