"""Bath YAML loader.

Library files live in `src/bioslice5x/bath/library/`. Each file is a
single bath spec; recipes reference baths by name.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any, cast

import yaml

from bioslice5x.bath.models import BathSpec, PlaneBath
from bioslice5x.errors import ProfileValidationError


def _library_dir() -> Path:
    return Path(str(resources.files("bioslice5x.bath") / "library"))


def load_bath(name_or_path: str | Path) -> BathSpec:
    """Load a bath spec by shipped-library name or filesystem path."""
    candidate = Path(name_or_path)
    if not candidate.is_file():
        candidate = _library_dir() / f"{name_or_path}.yaml"
    if not candidate.is_file():
        raise ProfileValidationError(
            source=str(name_or_path),
            detail=f"bath not found (looked for path and {_library_dir()}/{name_or_path}.yaml)",
        )
    try:
        with candidate.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileValidationError(source=str(candidate), detail=str(exc)) from exc
    if not isinstance(data, dict):
        raise ProfileValidationError(source=str(candidate), detail="top-level must be a mapping")
    try:
        return PlaneBath.model_validate(cast(dict[str, Any], data))
    except Exception as exc:
        raise ProfileValidationError(source=str(candidate), detail=str(exc)) from exc


__all__ = ["load_bath"]
