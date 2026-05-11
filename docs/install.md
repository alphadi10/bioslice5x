# Installing BioSlice5X

Pick the path that matches your situation.

## Python-comfortable researcher: PyPI

```bash
pip install bioslice5x
```

Or with `uv`:

```bash
uv pip install bioslice5x
```

After install, both commands are available on your PATH:

- `bioslice5x` — CLI (slice meshes from the shell or scripts)
- `bioslice5x-gui` — minimal Tkinter GUI

Tkinter is part of the Python stdlib on most installs; if `bioslice5x-gui`
errors with "No module named '_tkinter'" on Linux, install your distro's
`python3-tk` package:

```bash
# Debian / Ubuntu
sudo apt install python3-tk
# Fedora / RHEL
sudo dnf install python3-tkinter
```

**Python 3.11 or newer is required.** Earlier Pythons can't run the
G-code emitter (see `CONTRIBUTING.md` §Python versions for details).

## Non-Python user: standalone binary

Download the binary for your OS from the [latest GitHub
Release](https://github.com/bioslice5x/bioslice5x/releases/latest):

| OS | Filename |
| --- | --- |
| Linux x86_64 | `bioslice5x-vX.Y.Z-ubuntu-latest` |
| macOS Intel | `bioslice5x-vX.Y.Z-macos-13` |
| macOS Apple Silicon | `bioslice5x-vX.Y.Z-macos-latest` |
| Windows x86_64 | `bioslice5x-vX.Y.Z-windows-latest.exe` |

```bash
# Linux/macOS — make executable and run
chmod +x bioslice5x-v0.1.0-macos-latest
./bioslice5x-v0.1.0-macos-latest --version
```

The binary bundles Python and every dependency; no separate install
required. The GUI launch command for binary installs is:

```bash
./bioslice5x-v0.1.0-macos-latest gui  # NOT YET — v0.1.1
```

For v0.1.0 the binary ships the CLI only. The GUI is available via the
PyPI install only. Standalone GUI binary is filed as a v0.1.1
deliverable.

### macOS Gatekeeper

The binary is not signed for v0.1.0. macOS will refuse to run it on
first launch:

```
"bioslice5x" cannot be opened because the developer cannot be verified.
```

Workaround: right-click the binary in Finder → Open → confirm in the
dialog. After the first manual approval, future runs from the command
line work normally.

Code-signing + notarisation is a v0.1.1+ deliverable; see
`docs/RELEASING.md`.

### Windows SmartScreen

Similar to Gatekeeper — Windows will warn on first launch. Click "More
info" → "Run anyway." Code-signing is the same v0.1.1+ deliverable.

## Contributor / from source

```bash
git clone https://github.com/bioslice5x/bioslice5x
cd bioslice5x
uv sync --all-extras --dev
```

Verify with:

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy
uv run lint-imports
```

See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the full dev workflow.

## Verifying the install

After any install method, verify with:

```bash
bioslice5x --version
# Should print: bioslice5x 0.1.0
```

And the smoke-test slice:

```bash
# From-source / PyPI install (with samples)
python samples/generate_samples.py
bioslice5x slice samples/cube_10mm.stl \
    --profile hypothetical_3axis \
    --recipe samples/cube_collagen_recipe.yaml \
    --output /tmp/test.gcode
head -30 /tmp/test.gcode
```

Expect a G-code file with a comment header carrying bioink and cell
metadata, then a sequence of `G1` lines.

## Next steps

- [`docs/tutorial/quickstart.md`](tutorial/quickstart.md) — guided
  walkthrough from a fresh checkout.
- [`README.md`](../README.md) — overview.
- [`LIMITATIONS.md`](../LIMITATIONS.md) — what v0.1.0 doesn't do.
