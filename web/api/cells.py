"""GET /api/cells — list every shipped cell payload with shear thresholds.

Used by the recipe builder to populate the cell-payload dropdown. Each
record carries its max wall shear stress threshold (the binding
constraint on the slicer's cell-viability validation) and the
`calibrated_against` provenance.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from typing import Any

import api._common as _common  # noqa: F401  (side-effect: sys.path)
from api._common import cors_preflight, error_response, json_response


def _list_cells() -> list[dict[str, Any]]:
    from bioslice5x.bioink.loader import load_default_library

    _bioinks, cells = load_default_library()
    out: list[dict[str, Any]] = []
    for name in sorted(cells):
        c = cells[name]
        out.append(
            {
                "name": c.name,
                "cell_type": c.cell_type,
                "cell_density_per_mL": c.cell_density_per_mL,
                "max_wall_shear_stress_pa": c.max_wall_shear_stress_pa,
                "calibrated_against": c.calibrated_against,
                "calibrated": "uncalibrated" not in c.calibrated_against.lower(),
                "notes": c.notes,
            }
        )
    return out


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self) -> None:
        cors_preflight(self)

    def do_GET(self) -> None:
        try:
            json_response(self, 200, {"cells": _list_cells()})
        except Exception as exc:
            error_response(self, 500, f"failed to load cells: {exc}", type=type(exc).__name__)
