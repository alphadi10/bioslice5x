"""POST /api/slice — main slicing endpoint.

Accepts a JSON body of shape:

    {
      "mesh": {
        "format": "stl" | "obj",
        "data_base64": "<base64-encoded mesh bytes>"
      },
      "profile": "open5x_prusa" | "open5x_voron" | "hypothetical_3axis",
      "recipe": { ...Recipe pydantic schema... }
    }

Returns:

    {
      "gcode": "<emitted text>",
      "stats": {
        "total_moves": 4680,
        "estimated_seconds": 2101.0,
        "max_wall_shear_pa": 3709.0,
        "max_wall_shear_by_syringe": {0: 23.2, 1: 3709.0},
        "threshold_by_syringe": {0: 1500.0, 1: 5000.0},
        "total_bioink_uL_by_syringe": {0: 64.0, 1: 470.5},
        "syringe_count": 2
      }
    }

On a CellViabilityError, returns 422 with the offending segment + how
much it exceeded the threshold. The frontend renders this as a hard
"refused to slice" notice rather than silently dropping the violation.
"""

from __future__ import annotations

import base64
import io
import json
from functools import lru_cache
from http.server import BaseHTTPRequestHandler
from typing import Any

import api._common as _common  # noqa: F401  (side-effect: sys.path)
from api._common import cors_preflight, error_response, json_response

# Module-level imports — keep them out of `_slice()` so Vercel can cache
# the import state across warm invocations. Cold-start savings of
# ~200-400 ms per warm call were measured during the audit. The cost
# of holding trimesh + bioslice5x in memory across requests is bounded
# (single-tenant serverless function) and worth the latency reduction.
import trimesh  # type: ignore[import-untyped]

from bioslice5x.errors import CellViabilityError
from bioslice5x.profile.loader import load_profile as _load_profile_uncached
from bioslice5x.recipe.models import Recipe
from bioslice5x.slicer import Slicer

# Conservative size cap — protects against accidentally huge uploads
# while staying well under Vercel Pro's request-body ceiling (the
# JSON envelope wraps a base64 blob, so the on-wire size is ~1.37x
# the raw mesh; 50 MB raw → ~68 MB request body).
MAX_MESH_BYTES = 50 * 1024 * 1024  # 50 MB


@lru_cache(maxsize=8)
def _cached_profile(name: str):
    """Profiles are read-only YAML; cache them across warm requests."""
    return _load_profile_uncached(name)


def _slice(payload: dict[str, Any]) -> dict[str, Any]:
    """Pure-function slice — no HTTP concerns. Returns the response body."""
    # ----- Validate the request envelope. -----
    mesh_block = payload.get("mesh")
    if not isinstance(mesh_block, dict):
        raise ValueError("missing or invalid `mesh` block")
    fmt = mesh_block.get("format", "stl")
    if fmt not in ("stl", "obj"):
        raise ValueError(f"unsupported mesh format: {fmt!r}")
    data_b64 = mesh_block.get("data_base64")
    if not isinstance(data_b64, str) or not data_b64:
        raise ValueError("missing `mesh.data_base64`")
    try:
        mesh_bytes = base64.b64decode(data_b64, validate=True)
    except Exception as exc:
        raise ValueError(f"`mesh.data_base64` is not valid base64: {exc}") from exc
    if len(mesh_bytes) > MAX_MESH_BYTES:
        raise ValueError(
            f"mesh is {len(mesh_bytes) / 1024 / 1024:.1f} MB; "
            f"max is {MAX_MESH_BYTES // 1024 // 1024} MB"
        )

    profile_name = payload.get("profile")
    if not isinstance(profile_name, str):
        raise ValueError("missing `profile` (string name)")

    recipe_block = payload.get("recipe")
    if not isinstance(recipe_block, dict):
        raise ValueError("missing or invalid `recipe` block")

    # ----- Parse + load. -----
    profile = _cached_profile(profile_name)
    recipe = Recipe.model_validate(recipe_block)

    # Load straight from a BytesIO — no temp file, no fs round-trip, no
    # cleanup-on-Windows surprises in the serverless runtime.
    mesh = trimesh.load(
        io.BytesIO(mesh_bytes),
        file_type=fmt,
        force="mesh",
    )

    # ----- Slice. -----
    slicer = Slicer(profile=profile, recipe=recipe)
    try:
        result = slicer.slice(mesh)
    except CellViabilityError as exc:
        # Surface the structured violation so the frontend can render the
        # specific segment, its computed stress, and the threshold.
        raise _CellViabilityHTTPError(
            segment_id=exc.segment_id,
            computed_wall_shear_pa=exc.computed_wall_shear_pa,
            threshold_pa=exc.threshold_pa,
            bioink_name=exc.bioink_name,
            cell_type=exc.cell_type,
            remediation=exc.remediation,
        ) from exc

    # ----- Pack the response. -----
    sr = result.stress_report
    return {
        "gcode": result.gcode,
        "stats": {
            "total_moves": len(result.moves),
            "estimated_seconds": result.estimated_seconds,
            "max_wall_shear_pa": sr.max_observed_pa(),
            "max_wall_shear_by_syringe": dict(sr.max_by_syringe),
            "threshold_by_syringe": dict(sr.threshold_by_syringe),
            "total_bioink_uL_by_syringe": dict(result.total_bioink_uL_by_syringe),
            "syringe_count": len(recipe.syringes),
        },
    }


class _CellViabilityHTTPError(Exception):
    """Carries the bits the frontend needs to render a viability refusal."""

    def __init__(
        self,
        *,
        segment_id: str,
        computed_wall_shear_pa: float,
        threshold_pa: float,
        bioink_name: str,
        cell_type: str,
        remediation: str,
    ) -> None:
        super().__init__(
            f"cell viability violation at segment {segment_id}: "
            f"{computed_wall_shear_pa:.1f} Pa > {threshold_pa:.1f} Pa"
        )
        self.segment_id = segment_id
        self.computed_wall_shear_pa = computed_wall_shear_pa
        self.threshold_pa = threshold_pa
        self.bioink_name = bioink_name
        self.cell_type = cell_type
        self.remediation = remediation

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": "cell_viability",
            "segment_id": self.segment_id,
            "computed_wall_shear_pa": self.computed_wall_shear_pa,
            "threshold_pa": self.threshold_pa,
            "bioink_name": self.bioink_name,
            "cell_type": self.cell_type,
            "remediation": self.remediation,
        }


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self) -> None:
        cors_preflight(self)

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                error_response(self, 400, "empty request body")
                return
            if length > MAX_MESH_BYTES + 1024 * 1024:
                error_response(self, 413, f"request body too large ({length} bytes)")
                return
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                error_response(self, 400, f"invalid JSON: {exc}")
                return
            response = _slice(payload)
            json_response(self, 200, response)
        except _CellViabilityHTTPError as exc:
            # 422 Unprocessable Entity — the request was well-formed but
            # the configuration is unsafe for cells.
            json_response(self, 422, {"error": exc.to_payload()})
        except ValueError as exc:
            error_response(self, 400, str(exc))
        except Exception as exc:
            error_response(self, 500, f"unexpected error: {exc}", type=type(exc).__name__)
