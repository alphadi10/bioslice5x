"""3D visualization for BioSlice5X G-code.

Phase 4 ships the toolpath viewer (`preview`). Phase 5+ will add mesh
overlay, layer scrubbing, and shear-stress coloring against a SliceResult.
See `docs/adr/0004-toolpath-viewer-backend.md` for the PyVista decision.
"""

from __future__ import annotations

from bioslice5x.visualization.preview import (
    ParsedMove,
    ToolpathViewer,
    parse_gcode,
    preview_gcode,
)

__all__ = [
    "ParsedMove",
    "ToolpathViewer",
    "parse_gcode",
    "preview_gcode",
]
