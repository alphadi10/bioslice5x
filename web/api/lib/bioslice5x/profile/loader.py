"""Machine profile YAML loader.

Profiles live in `src/bioslice5x/profile/library/<name>.yaml`. Use
`load_profile("hypothetical_3axis")` for a shipped profile, or pass a path.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any, cast

import yaml

from bioslice5x.errors import ProfileValidationError
from bioslice5x.profile.models import MachineProfile


def _library_dir() -> Path:
    return Path(str(resources.files("bioslice5x.profile") / "library"))


def load_profile(name_or_path: str | Path) -> MachineProfile:
    """Load a machine profile by shipped-library name or filesystem path."""
    candidate = Path(name_or_path)
    if not candidate.is_file():
        candidate = _library_dir() / f"{name_or_path}.yaml"
    if not candidate.is_file():
        raise ProfileValidationError(
            source=str(name_or_path),
            detail=f"profile not found (looked for path and {_library_dir()}/{name_or_path}.yaml)",
        )
    try:
        with candidate.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileValidationError(source=str(candidate), detail=str(exc)) from exc
    if not isinstance(data, dict):
        raise ProfileValidationError(source=str(candidate), detail="top-level must be a mapping")
    try:
        return MachineProfile.model_validate(cast(dict[str, Any], data))
    except Exception as exc:
        raise ProfileValidationError(source=str(candidate), detail=str(exc)) from exc


__all__ = ["load_profile"]
