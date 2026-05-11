#!/usr/bin/env python3
"""Regenerate JSON Schema files for Recipe and MachineProfile.

Run as part of the verification gate. CI fails if the generated schemas
drift from the checked-in versions (the regenerate-then-git-diff pattern
catches missed updates without manual sync work).

Schemas are written to `schemas/recipe.schema.json` and
`schemas/profile.schema.json`. Recipe schemas are referenced from YAML
files via the `# yaml-language-server: $schema=...` editor pragma — most
modern editors will then offer field autocomplete and validation as the
user types their recipe.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from bioslice5x.profile.models import MachineProfile  # noqa: E402
from bioslice5x.recipe.models import Recipe  # noqa: E402

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def main() -> int:
    SCHEMAS_DIR.mkdir(exist_ok=True)
    for model, name in [(Recipe, "recipe"), (MachineProfile, "profile")]:
        schema = model.model_json_schema()
        path = SCHEMAS_DIR / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
