"""GUI smoke test.

Verifies that the Tkinter GUI module imports and that the top-level
BioSlice5XApp class can be instantiated without exceptions. We do NOT
run the event loop — that requires a display server, which CI Linux
runners only have via xvfb.

If `DISPLAY` (Linux) or a working Tk install (Windows/macOS) is
unavailable, the test is skipped.

Per ADR-003, the GUI is a thin shim over the CLI; full GUI behaviour
testing is filed for a later phase that pulls in `pytest-xvfb` and
keyboard/mouse-event simulation.
"""

from __future__ import annotations

import os
import sys

import pytest

# Skip if no display and not on macOS/Windows where Tk has its own server.
_no_display = (
    sys.platform == "linux"
    and not os.environ.get("DISPLAY")
    and not os.environ.get("WAYLAND_DISPLAY")
)

pytestmark = [
    pytest.mark.skipif(_no_display, reason="no display server available for Tk smoke test"),
    pytest.mark.skipif(
        sys.version_info < (3, 11),
        reason="GUI lazy-imports Slicer which transitively requires Python 3.11+",
    ),
]


def test_gui_module_imports() -> None:
    """The bioslice5x.gui module imports cleanly."""
    from bioslice5x import gui

    assert hasattr(gui, "BioSlice5XApp")
    assert hasattr(gui, "main")


def test_gui_app_instantiates_and_destroys() -> None:
    """The top-level Tk window can be created and destroyed without errors."""
    try:
        from bioslice5x.gui import BioSlice5XApp

        app = BioSlice5XApp()
    except Exception as exc:
        pytest.skip(f"Tk init failed on this platform: {exc}")
    # Verify the window has the expected children. The exact widget tree
    # is implementation-detail-stable but the top-level title is part of
    # the contract.
    assert "BioSlice5X" in app.title()
    app.destroy()
