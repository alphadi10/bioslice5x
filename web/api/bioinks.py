"""GET /api/bioinks — list every shipped bioink with rheology + provenance.

Used by the recipe builder UI to populate the bioink dropdown. The
response is the bioink library serialized as JSON, keyed by name. Each
record carries the `calibrated_against` provenance so the UI can mark
uncalibrated defaults in red — matching the desktop viewer's behavior.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from typing import Any

# Shared helpers + sys.path setup for the vendored bioslice5x package.
import api._common as _common  # noqa: F401  (side-effect: sys.path)
from api._common import cors_preflight, error_response, json_response


def _list_bioinks() -> list[dict[str, Any]]:
    """Load every shipped bioink and serialize for the UI."""
    from bioslice5x.bioink.loader import load_default_library

    bioinks, _cells = load_default_library()
    out: list[dict[str, Any]] = []
    for name in sorted(bioinks):
        b = bioinks[name]
        out.append(
            {
                "name": b.name,
                "density_g_per_mL": b.density_g_per_mL,
                "rheology": {
                    "kind": b.rheology.kind,
                    "viscosity_pa_s": b.rheology.viscosity_pa_s,
                    "consistency_k": b.rheology.consistency_k,
                    "flow_index_n": b.rheology.flow_index_n,
                    "yield_stress_pa": b.rheology.yield_stress_pa,
                },
                "working_temperature_c": list(b.working_temperature_c),
                "crosslinking": b.crosslinking,
                "calibrated_against": b.calibrated_against,
                "calibrated": "uncalibrated" not in b.calibrated_against.lower(),
                "notes": b.notes,
            }
        )
    return out


class handler(BaseHTTPRequestHandler):  # noqa: N801 (Vercel convention)
    def do_OPTIONS(self) -> None:
        cors_preflight(self)

    def do_GET(self) -> None:
        try:
            payload = {"bioinks": _list_bioinks()}
            json_response(self, 200, payload)
        except Exception as exc:
            error_response(self, 500, f"failed to load bioinks: {exc}", type=type(exc).__name__)
