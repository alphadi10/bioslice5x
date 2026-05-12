"""GET /api/profiles — list every shipped machine profile.

Used by the recipe builder to populate the profile picker. Each record
carries the build volume + kinematic chain so the viewer can render the
correct wireframe and pick the right tilt/swivel letters.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from typing import Any

import api._common as _common  # noqa: F401  (side-effect: sys.path)
from api._common import cors_preflight, error_response, json_response

SHIPPED = ["open5x_prusa", "open5x_voron", "hypothetical_3axis"]


def _list_profiles() -> list[dict[str, Any]]:
    from bioslice5x.profile.loader import load_profile

    out: list[dict[str, Any]] = []
    for name in SHIPPED:
        p = load_profile(name)
        kc = p.kinematic_chain
        chain: dict[str, Any] = {"kind": kc.kind}
        if kc.tilt is not None:
            chain["tilt"] = {
                "letter": kc.tilt.letter,
                "rotates_about": kc.tilt.rotates_about,
                "range_deg": list(kc.tilt.range_deg),
                "invert": kc.tilt.invert,
            }
        if kc.swivel is not None:
            chain["swivel"] = {
                "letter": kc.swivel.letter,
                "rotates_about": kc.swivel.rotates_about,
                "range_deg": list(kc.swivel.range_deg),
                "invert": kc.swivel.invert,
            }
        out.append(
            {
                "name": p.name,
                "firmware": p.firmware,
                "build_volume": {
                    "x_mm": list(p.build_volume.x_mm),
                    "y_mm": list(p.build_volume.y_mm),
                    "z_mm": list(p.build_volume.z_mm),
                },
                "kinematic_chain": chain,
            }
        )
    return out


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self) -> None:
        cors_preflight(self)

    def do_GET(self) -> None:
        try:
            json_response(self, 200, {"profiles": _list_profiles()})
        except Exception as exc:
            error_response(self, 500, f"failed to load profiles: {exc}", type=type(exc).__name__)
