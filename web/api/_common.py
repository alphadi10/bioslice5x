"""Shared helpers for the BioSlice5X Vercel Python serverless endpoints.

Vercel's Python runtime exposes each `api/<name>.py` file as a route that
imports a `handler` class (BaseHTTPRequestHandler subclass). The handler
classes here delegate to small pure functions that do the actual work,
so the same logic is unit-testable outside the Vercel runtime.

The vendored `bioslice5x` package lives in `api/lib/bioslice5x/`; we
prepend `api/lib/` to `sys.path` at module load so handlers can
`import bioslice5x` without further fuss.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Add api/lib/ to sys.path so `import bioslice5x` resolves to the
# vendored copy. Idempotent — re-adding is a no-op.
_LIB = Path(__file__).resolve().parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))


def json_response(handler: Any, status: int, payload: Any) -> None:
    """Write a JSON response back through a BaseHTTPRequestHandler.

    Sets CORS headers permissive enough for browser fetches from the
    same Vercel deployment and from localhost (for dev). Wider CORS is
    fine for this app — the slicer doesn't take credentials, doesn't
    store anything, and the data flowing through it is meant to be
    shared publicly anyway.
    """
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body)


def cors_preflight(handler: Any) -> None:
    """Respond to a CORS OPTIONS preflight with 204."""
    handler.send_response(204)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()


def error_response(handler: Any, status: int, message: str, **detail: Any) -> None:
    """Standard error envelope: `{error: {message, ...detail}}`."""
    json_response(handler, status, {"error": {"message": message, **detail}})


__all__ = ["cors_preflight", "error_response", "json_response"]
