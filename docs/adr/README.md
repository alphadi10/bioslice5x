# Architecture Decision Records (ADRs)

This directory holds ADRs that document user-visible behavior decisions
where multiple alternatives are plausible and produce visibly different
print outcomes.

## When an ADR is required

File an ADR before implementation when **all** of these are true:

1. The behavior is user-visible (affects what comes out of the slicer, or
   how the user must invoke it).
2. There are at least two plausible alternatives.
3. The alternatives produce visibly different outputs or workflows — not
   just internal implementation differences.

ADRs are especially required when at least one alternative has cell-safety
implications (the FRESH "deposit perpendicular to the surface" principle,
shear-stress threshold semantics, multi-syringe purge protocols affecting
deposited geometry, etc.). For those, the cell-safety alternative MUST be
explicitly rejected with reasoning, even if it appears mechanically simpler.

## When an ADR is NOT required

- Routine implementation details (data structures, algorithm choice,
  variable naming).
- Bug fixes — even ones with subtle correctness implications. File a test
  capturing the regression instead.
- Doc updates within existing structure.
- Internal API design that doesn't reach the user-visible surface.
- Defaults with a narrow design space (e.g., the conformal arc-sampling
  default of one sample per line-width — there isn't a meaningfully
  different alternative).

## ADR format

Each ADR is `NNNN-short-title.md` numbered sequentially. Contents:

1. **Status** — Proposed | Accepted | Rejected | Superseded by NNNN.
2. **Date** — ISO 8601, YYYY-MM-DD.
3. **Companion test** — path to the doctest-equivalent test pinning the
   numerical worked examples (mandatory when the ADR has any numerics).
4. **Context** — what problem requires a decision.
5. **Considered alternatives** — each with pros and cons.
6. **Decision** — chosen alternative, with reasoning. Rejected
   alternatives with rejection reasoning. Cell-safety reasoning is
   explicit where applicable.
7. **Worked example** — pinned by the companion test.
8. **Out of scope** — what this ADR does NOT decide, to head off later
   "didn't ADR-001 cover this?" confusion.

## Index

- [ADR-001 — Wrap-tilt clamping strategy](0001-wrap-tilt-clamping.md). Accepted.
  Refuse-loudly default + opt-in arc-split. Rejects tilt-to-max-then-swivel
  on cell-safety grounds.
- [ADR-002 — Default infill pattern](0002-default-infill-pattern.md). Accepted.
  Rectilinear at user-configurable density and angle for v0.1.0; concentric
  and gyroid deferred to v0.2.0.
- [ADR-003 — GUI file-picker only (no inline recipe editor)](0003-gui-file-picker-only.md).
  Accepted. v0.1.0 GUI is a thin shim over the CLI; recipes are YAML
  files authored externally. Inline form editor deferred.

## Drift protection

Numerical examples in ADRs are pinned by tests in `tests/` that re-derive
the numbers from the code. Prose worked examples drift the first time
someone touches the math; tested ones don't. See `tests/test_adr_001_examples.py`
for the pattern.
