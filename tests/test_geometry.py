"""Geometry tests — mesh load, flat slicing on a known-shape cube."""

from __future__ import annotations

from typing import Any, cast

import pytest
import trimesh

from bioslice5x.geometry.flat_slicer import flat_slice
from bioslice5x.geometry.mesh import load_mesh, mesh_z_extent


def _cube_mesh(size_mm: float = 10.0) -> trimesh.Trimesh:
    cube: Any = trimesh.creation.box(extents=[size_mm, size_mm, size_mm])
    # Translate so z spans [0, size_mm], not [-size_mm/2, size_mm/2].
    cube.apply_translation([0.0, 0.0, size_mm / 2.0])
    return cast(trimesh.Trimesh, cube)


def test_cube_z_extent_is_correct() -> None:
    cube = _cube_mesh(10.0)
    z_min, z_max = mesh_z_extent(cube)
    assert z_min == pytest.approx(0.0, abs=1e-6)
    assert z_max == pytest.approx(10.0, abs=1e-6)


def test_flat_slice_produces_expected_layer_count() -> None:
    cube = _cube_mesh(10.0)
    layers = flat_slice(cube, layer_height_mm=1.0)
    # 10 mm height / 1 mm layer = 10 layers (the slicer skips empty cuts).
    assert len(layers) == 10
    assert layers[0].z < layers[-1].z


def test_flat_slice_each_layer_has_one_polygon_for_a_cube() -> None:
    cube = _cube_mesh(10.0)
    layers = flat_slice(cube, layer_height_mm=1.0)
    for layer in layers:
        # Cube cross-section is a single 10x10 square — one exterior, no holes.
        # Trimesh may keep collinear vertices, so we don't assert exactly 4 points,
        # only that they all lie on the bounding square.
        assert len(layer.polygons) == 1
        assert layer.polygons[0].is_hole is False
        for x, y in layer.polygons[0].points:
            on_edge = abs(abs(x) - 5.0) < 1e-6 or abs(abs(y) - 5.0) < 1e-6
            assert on_edge, f"vertex ({x}, {y}) not on the 10x10 bounding square"


def test_flat_slice_rejects_invalid_layer_height() -> None:
    cube = _cube_mesh(10.0)
    with pytest.raises(ValueError, match="layer_height"):
        flat_slice(cube, layer_height_mm=0.0)


def test_load_mesh_missing_file_raises() -> None:
    from bioslice5x.errors import ProfileValidationError

    with pytest.raises(ProfileValidationError):
        load_mesh("/no/such/file.stl")
