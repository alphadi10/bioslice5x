"""YAML-backed library of reference bioinks and cell payloads.

Library YAML files live in `src/bioslice5x/bioink/library/`. Each bioink is
its own file; cells are aggregated in `cells.yaml`. Drop a new YAML file in
the library directory to add a bioink — no Python edits required.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any, cast

import yaml

from bioslice5x.bioink.models import Bioink, CellPayload
from bioslice5x.errors import ProfileValidationError


def _library_dir() -> Path:
    return Path(str(resources.files("bioslice5x.bioink") / "library"))


def load_bioink_yaml(path: Path) -> Bioink:
    """Parse a single bioink YAML file into a validated Bioink."""
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileValidationError(source=str(path), detail=str(exc)) from exc
    if not isinstance(data, dict):
        raise ProfileValidationError(source=str(path), detail="top-level must be a mapping")
    try:
        return Bioink.model_validate(cast(dict[str, Any], data))
    except Exception as exc:
        raise ProfileValidationError(source=str(path), detail=str(exc)) from exc


def load_cells_yaml(path: Path) -> dict[str, CellPayload]:
    """Parse a cells.yaml file into a dict keyed by cell payload name."""
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileValidationError(source=str(path), detail=str(exc)) from exc
    if not isinstance(data, dict) or "cells" not in data:
        raise ProfileValidationError(source=str(path), detail="missing top-level 'cells' key")
    out: dict[str, CellPayload] = {}
    cells_map = cast(dict[str, dict[str, Any]], data["cells"])
    for cell_name, payload in cells_map.items():
        payload_with_name = {"name": cell_name, **payload}
        try:
            out[cell_name] = CellPayload.model_validate(payload_with_name)
        except Exception as exc:
            raise ProfileValidationError(source=f"{path}::{cell_name}", detail=str(exc)) from exc
    return out


def load_default_library() -> tuple[dict[str, Bioink], dict[str, CellPayload]]:
    """Load every bioink YAML and the cells.yaml from the shipped library."""
    lib_dir = _library_dir()
    bioinks: dict[str, Bioink] = {}
    cells: dict[str, CellPayload] = {}
    for path in sorted(lib_dir.glob("*.yaml")):
        if path.name == "cells.yaml":
            cells = load_cells_yaml(path)
        else:
            bioink = load_bioink_yaml(path)
            bioinks[bioink.name] = bioink
    return bioinks, cells


def load_bioink_by_name(name: str) -> Bioink:
    """Convenience: load a single shipped bioink by name."""
    bioinks, _ = load_default_library()
    if name not in bioinks:
        raise ProfileValidationError(
            source="bioink library",
            detail=f"bioink {name!r} not found; available: {sorted(bioinks)}",
        )
    return bioinks[name]


def load_cell_by_name(name: str) -> CellPayload:
    """Convenience: load a single shipped cell payload by name."""
    _, cells = load_default_library()
    if name not in cells:
        raise ProfileValidationError(
            source="bioink library",
            detail=f"cell payload {name!r} not found; available: {sorted(cells)}",
        )
    return cells[name]


__all__ = [
    "load_bioink_by_name",
    "load_bioink_yaml",
    "load_cell_by_name",
    "load_cells_yaml",
    "load_default_library",
]
