"""Test-suite configuration shared across all test modules.

The single non-trivial concern this file handles is **PyVista headless
rendering on Linux CI**. Without a display server or software-mesa
configured, VTK's OpenGL context creation segfaults inside C code —
which Python cannot catch, so per-test try/except blocks don't help.
We probe the environment at session start and either:

  1. Start xvfb via `pyvista.start_xvfb()` if available, putting the
     suite in a position to render off-screen, or
  2. Set a session-level skip marker that the rendering tests check.

Non-Linux platforms (macOS / Windows) don't need xvfb; pyvista's
off-screen mode works via the native graphics layer.
"""

from __future__ import annotations

import platform

import pytest


def _try_start_xvfb() -> bool:
    """Return True if PyVista is ready for off-screen rendering."""
    try:
        import pyvista as pv
    except ImportError:
        return False

    pv.OFF_SCREEN = True

    # macOS / Windows: native off-screen rendering works without xvfb.
    if platform.system() != "Linux":
        return True

    # Linux: try xvfb. If pyvista's helper isn't present (older builds)
    # or xvfb itself isn't installed, give up gracefully — the rendering
    # tests will skip rather than segfault.
    start = getattr(pv, "start_xvfb", None)
    if start is None:
        return False
    try:
        start(wait=0.05, window_size=(400, 400))
    except Exception:
        return False
    return True


PYVISTA_RENDER_OK = _try_start_xvfb()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip rendering tests when PyVista can't actually render.

    A Python-level segfault in VTK's OpenGL context creation crashes
    the interpreter; pytest can't recover. The only safe behaviour in
    a headless environment without working software rendering is to
    skip rather than run-and-die.
    """
    if PYVISTA_RENDER_OK:
        return
    skip_render = pytest.mark.skip(
        reason=(
            "PyVista off-screen rendering unavailable on this platform "
            "(no xvfb / no software-mesa). Rendering smoke tests skipped."
        )
    )
    for item in items:
        # Identify rendering tests by name — every screenshot smoke test
        # in test_preview_smoke.py mentions "screenshot" or "renders".
        name = item.nodeid
        if "test_screenshot_" in name or "test_preview_smoke.py::test_missing_mesh_overlay" in name:
            item.add_marker(skip_render)
