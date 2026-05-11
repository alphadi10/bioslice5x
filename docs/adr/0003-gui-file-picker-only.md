# ADR-003: GUI uses file pickers only (no inline recipe editor) for v0.1.0

**Status:** Accepted.
**Date:** 2026-05-11.
**Companion test:** none required (the alternatives have no cell-safety
implications and no numerical worked examples — pure UX choice).

## Context

v0.1.0 ships a minimal Tkinter GUI wrapping the BioSlice5X CLI. The
question: how do users specify recipes?

## Considered alternatives

### (a) File picker only (chosen)

The GUI exposes a "Recipe (YAML):" entry with a Browse button. The user
picks a YAML file from disk; the GUI does not edit recipes inline.

- **Pros:** Tiny UI surface. YAML is already the documented recipe
  format; the file is reusable across runs and version-controllable.
  The GUI is a thin shim over the CLI — every recipe authored in a text
  editor works in both. No schema-form-rendering work.
- **Cons:** New users without a recipe template have to find or write
  one from scratch. Mitigated by shipping `samples/cube_collagen_recipe.yaml`
  and `samples/cylinder_conformal_recipe.yaml`.

### (b) Inline form-based editor

The GUI renders a form for each Recipe field — dropdown for bioink
(populated from the library), number inputs for slicing params,
add/remove rows for multi-syringe, etc. Saves to YAML behind the scenes.

- **Pros:** No need to know YAML. Friendlier for wet-lab users.
- **Cons:** A real form needs:
  - Rendering nested pydantic models (Syringe, Region, Bath, slicing
    Mode discriminated union, PrintOrientation discriminated union)
  - Validation feedback inline as the user types
  - Save/load to file as a separate workflow
  - Schema-evolution maintenance (every new recipe field touches the GUI)
  - Approximately 600+ lines of Tkinter widget code
  Not v0.1.0 scope; substantively a different deliverable.

### (c) Embedded YAML editor with syntax highlighting

A text widget with YAML colorization and live schema validation against
`schemas/recipe.schema.json`.

- **Pros:** YAML literacy assumed (matches CLI users); no form-renderer
  to maintain; live validation gives fast feedback.
- **Cons:** Tkinter's `Text` widget doesn't ship with YAML
  highlighting; `tk-html-widgets` or a `tk_async_execute` integration
  would be needed. Schema-based completion is non-trivial. The
  competitive baseline (file picker + an external editor like VS Code
  with the YAML extension reading our exported JSON schema) is
  arguably better.

## Decision

**(a) File picker only for v0.1.0.**

Reasoning:

- The recipe schema is well-typed, with strict pydantic validation, and
  the project exports JSON Schema files (`schemas/recipe.schema.json`).
  Any modern editor consuming the schema will give the user better
  autocomplete + validation than we'd build into Tkinter.
- The GUI's job is "make the slicer launchable by non-CLI users." That's
  done by the file pickers + the Slice button + a log panel + an
  output-folder button. Recipe authoring is a different problem.
- An ADR-driven later upgrade to (b) or (c) is cleanly possible — the
  GUI module has a single entry point and no API contract beyond
  "launch the slicer with these four inputs."

## Worked example

The v0.1.0 GUI workflow:

1. User runs `bioslice5x-gui`.
2. Window opens. Four input fields:
   - **Input mesh** — Browse opens an STL/OBJ picker.
   - **Machine profile** — combobox of shipped profiles + "(load from
     file…)".
   - **Recipe (YAML)** — Browse opens a YAML picker.
   - **Output G-code** — defaults to `<mesh-basename>.gcode` next to
     the mesh; can be re-targeted.
3. User clicks **Slice**.
4. Background thread runs the slicer; log panel appends progress lines.
5. On completion: log shows move count, max wall shear, estimated time.
   **Open output folder** button is enabled.
6. User opens the folder; the G-code is there.

Total clicks from launch to G-code in folder: 5 (4 Browses + Slice).
With defaults filled in for repeat runs, 2 (re-pick mesh or recipe, then
Slice).

## Out of scope

- 3D toolpath preview pane (filed for v0.2.0; deserves its own ADR
  because pyvista/trimesh viewer choice has rendering-stack
  implications).
- Inline recipe editor (deferred per above; if/when implemented, file an
  ADR-NNN that supersedes the relevant part of this one).
- Live bioprinter connection / G-code streaming (out of project scope;
  belongs to a separate OctoPrint-style integration).
- Recipe-from-template wizard ("New recipe from template…" generates a
  YAML from a guided dialog). Plausible v0.1.1.
