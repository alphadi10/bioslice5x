"""G-code emission (RepRapFirmware dialect).

Phase 2a: 3-axis emitter. Phase 2b adds A/C tokens via the kinematic-chain
spec in the machine profile.
"""

from __future__ import annotations

from bioslice5x.postprocessor.rrf import EmittedGCode, emit_rrf

__all__ = ["EmittedGCode", "emit_rrf"]
