# BioSlice5X — Web

Browser-based 5-axis slicer + viewer + recipe builder for the
[BioSlice5X](../README.md) FRESH-bioprinting toolchain. Targets Vercel.

## Architecture

```
┌─ web/ ──────────────────────────────────────────────────┐
│  app/                   Next.js 15 App Router UI         │
│  components/            Three.js viewer + recipe builder  │
│  lib/                   G-code parser, types, API client  │
│  api/                   Python serverless functions       │
│  └── lib/bioslice5x/    Vendored Python package           │
└──────────────────────────────────────────────────────────┘
```

The Python slicer is **vendored** into `api/lib/bioslice5x/`. To pick up
upstream slicer changes:

```bash
bash scripts/sync-bioslice5x.sh
```

## Local development

```bash
cd web
npm install
npm run dev
# → http://localhost:3000
```

The Python serverless functions run on `vercel dev`. To exercise the
full slice flow locally:

```bash
npm install -g vercel
vercel link             # link to alphadi10s-projects
vercel dev              # serves Next.js + Python functions together
```

Note: `vercel dev` runs `pip install` for the Python deps on first
launch — this takes a minute. Subsequent launches use the cache.

## Production deployment

```bash
vercel deploy --prod    # or git push to the linked branch
```

The deployment includes:

- Next.js static pages + client bundle
- Four Python serverless functions:
  - `POST /api/slice` — main slicer (300s timeout, 3 GB memory)
  - `GET /api/bioinks` — shipped bioink library
  - `GET /api/cells` — shipped cell payloads
  - `GET /api/profiles` — shipped machine profiles

## API contract

### `POST /api/slice`

```json
{
  "mesh": { "format": "stl", "data_base64": "..." },
  "profile": "open5x_prusa",
  "recipe": { ...Recipe... }
}
```

Returns `{ gcode: string, stats: SliceStats }` on success, or `422` with
a structured `CellViabilityError` payload when the recipe would over-shear
the cells in any segment.

### `GET /api/bioinks` / `/api/cells` / `/api/profiles`

Read-only JSON arrays of the shipped libraries. Populated from the
vendored `bioslice5x` Python package at request time, so the source of
truth is always the shipped YAMLs in
`src/bioslice5x/bioink/library/` and
`src/bioslice5x/profile/library/`.

## What the web app does (and doesn't)

**Does:**
- Recipe builder (syringes, bioinks, cells, needles, regions, slicing
  params) — no YAML editing required.
- STL upload + slice on the server.
- 3D toolpath viewer with Z-height and wall-shear-stress coloring,
  layer scrubber, semi-transparent source-mesh overlay.
- G-code download.
- Cell viability hard refusal — surfaces the offending segment.

**Doesn't (yet):**
- User accounts / saved recipes — every session is fresh.
- Conformal slicing UI (the `wrap_around_axis` mode exists in the
  schema but the form doesn't expose its sub-fields yet).
- Bath modeling, per-bioink retract/purge, photopolymerization modes.

## Limits (Vercel Pro)

- Mesh upload: 50 MB hard cap (set in `api/slice.py`). Vercel Pro's
  request-body ceiling accommodates the base64 overhead.
- Slice timeout: 300 seconds (5 minutes). Adequate for centimeter-scale
  CHIPS prints at sub-millimeter layer height.
- Function memory: 3008 MB on the slice endpoint, 1024 MB on the read
  endpoints.
- Function size: each Python function packs `bioslice5x` + numpy +
  trimesh + shapely. Sized at ~150 MB unzipped, well under Vercel's
  250 MB function limit.

## Citation

If you use the web tool in research, cite the project + the underlying
papers — see [`/CITATION.cff`](../CITATION.cff) in the repo root.
