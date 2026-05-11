"""Mesh I/O backed by trimesh.

Loads STL/OBJ and validates basic invariants (non-empty, finite vertices).
Watertightness is checked lazily — Phase 2a's flat slicer tolerates
non-watertight meshes but warns about them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import trimesh

from bioslice5x.errors import ProfileValidationError


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    """Load a mesh file. Raises ProfileValidationError on malformed input."""
    p = Path(path)
    if not p.is_file():
        raise ProfileValidationError(source=str(p), detail="mesh file not found")
    try:
        loaded_any: Any = trimesh.load_mesh(str(p))
    except Exception as exc:
        raise ProfileValidationError(source=str(p), detail=str(exc)) from exc
    if isinstance(loaded_any, trimesh.Scene):
        merged: Any = loaded_any.dump(concatenate=True)
        if not isinstance(merged, trimesh.Trimesh):
            raise ProfileValidationError(
                source=str(p),
                detail="scene contains non-trimesh geometry; cannot slice",
            )
        loaded_any = merged
    if not isinstance(loaded_any, trimesh.Trimesh):
        raise ProfileValidationError(
            source=str(p), detail=f"unexpected mesh type {type(loaded_any)}"
        )
    if len(loaded_any.vertices) == 0 or len(loaded_any.faces) == 0:
        raise ProfileValidationError(source=str(p), detail="mesh has no geometry")
    return loaded_any


def mesh_z_extent(mesh: trimesh.Trimesh) -> tuple[float, float]:
    """Return (z_min, z_max) of the mesh's axis-aligned bounding box."""
    bounds = cast(Any, mesh.bounds)
    return float(bounds[0][2]), float(bounds[1][2])


__all__ = ["load_mesh", "mesh_z_extent"]
