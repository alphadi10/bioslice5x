/**
 * TypeScript port of `bioslice5x.visualization.preview.parse_gcode`.
 *
 * Captures the same tokens the Python parser does:
 *  - X/Y/Z absolute coordinates (carried forward when a move omits the letter)
 *  - A/B/C rotary tokens (5-axis prints; null when absent)
 *  - E extrusion volume
 *  - F feed rate
 *  - `;STRESS:<Pa>` trailing comment emitted by the postprocessor —
 *    the load-bearing scalar that powers the viewer's "shear" color mode
 *
 * The header dict picks up both prose `; Key: value` lines and the
 * `;META: key=value` block, so the UI can surface profile / recipe /
 * calibration provenance the same way the Python viewer does.
 */

export interface ParsedMove {
  /** Move endpoint in machine frame, mm. */
  endXyz: [number, number, number];
  /** Travel moves carry no E token; extrusion moves do. */
  isTravel: boolean;
  /** Rotary axes — null when the chain doesn't use that letter. */
  aDeg: number | null;
  bDeg: number | null;
  cDeg: number | null;
  /** Extrusion delta in plunger-millimetres (the E token). */
  extrusionMm: number;
  /** Feed in mm/min. */
  feedMmPerMin: number;
  /** Wall shear stress in Pa, read from `;STRESS:`. null when absent. */
  wallShearPa: number | null;
}

export interface KinematicChainInfo {
  /** "three_axis" or "tilt_swivel" from the META block. */
  kind: string;
  /** Tilt axis letter (A, B, …) or null when the chain has no tilt. */
  tiltLetter: string | null;
  /** Axis the tilt joint rotates about (x/y/z) or null. */
  tiltAxis: "x" | "y" | "z" | null;
  /** Whether the postprocessor negated the tilt angle on emit. */
  tiltInvert: boolean;
  /** Swivel axis letter (C, V, …) or null. */
  swivelLetter: string | null;
  /** Axis the swivel joint rotates about (x/y/z) or null. */
  swivelAxis: "x" | "y" | "z" | null;
  /** Whether the postprocessor negated the swivel angle on emit. */
  swivelInvert: boolean;
}

export interface ParsedGcode {
  moves: ParsedMove[];
  header: Record<string, string>;
  chain: KinematicChainInfo;
}

function parseKinematicChain(header: Record<string, string>): KinematicChainInfo {
  const axisOf = (s: string | undefined): "x" | "y" | "z" | null =>
    s === "x" || s === "y" || s === "z" ? s : null;
  const letterOf = (s: string | undefined): string | null =>
    s && s !== "none" ? s : null;
  const boolOf = (s: string | undefined): boolean => s === "true";
  return {
    kind: header["meta.kinematic_chain"] ?? "three_axis",
    tiltLetter: letterOf(header["meta.tilt_letter"]),
    tiltAxis: axisOf(header["meta.tilt_axis"]),
    tiltInvert: boolOf(header["meta.tilt_invert"]),
    swivelLetter: letterOf(header["meta.swivel_letter"]),
    swivelAxis: axisOf(header["meta.swivel_axis"]),
    swivelInvert: boolOf(header["meta.swivel_invert"]),
  };
}

const TOKEN_RE = /([XYZACEFB])(-?\d+(?:\.\d+)?)/g;
const META_RE = /^;META:\s+(\w+)\s*=\s*(\S+)\s*$/;
const HEADER_FIELD_RE = /^;\s+(.+?):\s+(.+?)\s*$/;
const STRESS_RE = /;STRESS:(-?\d+(?:\.\d+)?)/;

export function parseGcode(text: string): ParsedGcode {
  const moves: ParsedMove[] = [];
  const header: Record<string, string> = {};

  // Track running absolute position; first move starts at (0, 0, 0).
  // This matches the Python parser's convention (the G-code header
  // sets G90 absolute mode before the first G1).
  let curX = 0;
  let curY = 0;
  let curZ = 0;
  let curA: number | null = null;
  let curB: number | null = null;
  let curC: number | null = null;
  let inPrint = false;

  for (const rawLine of text.split(/\r?\n/)) {
    const stripped = rawLine.trim();

    const meta = META_RE.exec(stripped);
    if (meta) {
      header[`meta.${meta[1]}`] = meta[2];
      continue;
    }

    if (!inPrint) {
      const fieldMatch = HEADER_FIELD_RE.exec(stripped);
      if (fieldMatch) {
        header[fieldMatch[1]] = fieldMatch[2];
      }
    }

    if (stripped === "; ---- start of print ----") {
      inPrint = true;
      continue;
    }
    if (stripped === "; ---- end of print ----") {
      inPrint = false;
      continue;
    }
    if (!inPrint || !stripped.startsWith("G1")) {
      continue;
    }

    // Parse G1 tokens.
    const tokens: Record<string, number> = {};
    TOKEN_RE.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = TOKEN_RE.exec(stripped)) !== null) {
      tokens[m[1]] = parseFloat(m[2]);
    }
    if (Object.keys(tokens).length === 0) continue;

    const newX = "X" in tokens ? tokens.X : curX;
    const newY = "Y" in tokens ? tokens.Y : curY;
    const newZ = "Z" in tokens ? tokens.Z : curZ;
    const newA: number | null = "A" in tokens ? tokens.A : curA;
    const newB: number | null = "B" in tokens ? tokens.B : curB;
    const newC: number | null = "C" in tokens ? tokens.C : curC;
    const extrusion = "E" in tokens ? tokens.E : 0;
    const feed = "F" in tokens ? tokens.F : 0;
    const isTravel = !("E" in tokens);

    const stressMatch = STRESS_RE.exec(stripped);
    const wallShearPa = stressMatch ? parseFloat(stressMatch[1]) : null;

    moves.push({
      endXyz: [newX, newY, newZ],
      isTravel,
      aDeg: newA,
      bDeg: newB,
      cDeg: newC,
      extrusionMm: extrusion,
      feedMmPerMin: feed,
      wallShearPa,
    });

    curX = newX;
    curY = newY;
    curZ = newZ;
    curA = newA;
    curB = newB;
    curC = newC;
  }

  return { moves, header, chain: parseKinematicChain(header) };
}

/**
 * Bin extrusion moves into layer indices for the scrubber.
 *
 * Flat / wrap-Z prints climb monotonically in Z; binning by rounded Z
 * (to 10 µm) reproduces the slicer's `layer_height_mm`. Conformal /
 * 5-axis prints with continuously varying Z fall back to 100 ordinal
 * bands over move order — the scrubber maps to "time-in-print" instead
 * of physical layers, which is still useful.
 *
 * Mirrors `bioslice5x.visualization.preview._compute_layer_indices`.
 */
export function computeLayerIndices(moves: ParsedMove[]): Int32Array {
  const ext = moves.filter((m) => !m.isTravel);
  if (ext.length === 0) return new Int32Array(0);

  // Round Z to 10 µm to absorb FP jitter.
  const zsRounded = ext.map((m) => Math.round(m.endXyz[2] * 100) / 100);
  const distinct = Array.from(new Set(zsRounded)).sort((a, b) => a - b);

  if (distinct.length <= Math.max(1, Math.floor(ext.length / 5))) {
    const rank = new Map<number, number>();
    distinct.forEach((z, i) => rank.set(z, i));
    return Int32Array.from(zsRounded, (z) => rank.get(z) ?? 0);
  }

  // Ordinal-band fallback: 100 equal-count bands.
  const nBands = Math.min(100, ext.length);
  return Int32Array.from(ext, (_m, i) =>
    Math.min(Math.floor((i * nBands) / ext.length), nBands - 1)
  );
}
