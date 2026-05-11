"""Recipe YAML loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

from bioslice5x.errors import ProfileValidationError
from bioslice5x.recipe.models import Recipe


def load_recipe(path: str | Path) -> Recipe:
    """Load and validate a recipe YAML file."""
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileValidationError(source=str(path), detail=str(exc)) from exc
    if not isinstance(data, dict):
        raise ProfileValidationError(source=str(path), detail="top-level must be a mapping")
    try:
        return Recipe.model_validate(cast(dict[str, Any], data))
    except Exception as exc:
        raise ProfileValidationError(source=str(path), detail=str(exc)) from exc


__all__ = ["load_recipe"]
