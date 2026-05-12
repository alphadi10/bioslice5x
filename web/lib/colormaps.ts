/**
 * Two colormaps matching the PyVista desktop viewer:
 *
 *  - `viridis` — perceptually uniform; used for Z-height coloring.
 *    Sampled from matplotlib at evenly-spaced t values; 8 stops are
 *    enough for a smooth gradient when linearly interpolated.
 *  - `hot` — black → red → yellow → white; used for shear-stress
 *    coloring so red marks "approaching the cell-viability limit"
 *    and yellow/white marks "over." Matches the PyVista 'hot' cmap.
 *
 * Both maps take a `t in [0, 1]` value and return an [r, g, b] triplet
 * with components in [0, 1]. Callers are responsible for normalizing
 * the scalar (Z, shear Pa) into the unit interval and clamping.
 */

type Triplet = readonly [number, number, number];

const VIRIDIS_STOPS: ReadonlyArray<Triplet> = [
  [0.267, 0.005, 0.329],
  [0.283, 0.141, 0.458],
  [0.254, 0.265, 0.530],
  [0.207, 0.372, 0.553],
  [0.164, 0.471, 0.558],
  [0.128, 0.567, 0.551],
  [0.135, 0.659, 0.518],
  [0.267, 0.749, 0.441],
  [0.478, 0.821, 0.318],
  [0.741, 0.873, 0.150],
  [0.993, 0.906, 0.144],
];

const HOT_STOPS: ReadonlyArray<Triplet> = [
  [0.04, 0.0, 0.0],
  [0.42, 0.0, 0.0],
  [0.78, 0.0, 0.0],
  [1.0, 0.18, 0.0],
  [1.0, 0.56, 0.0],
  [1.0, 0.92, 0.0],
  [1.0, 1.0, 0.62],
  [1.0, 1.0, 1.0],
];

function lerp(stops: ReadonlyArray<Triplet>, t: number): Triplet {
  if (!Number.isFinite(t)) return stops[0];
  const clamped = Math.max(0, Math.min(1, t));
  if (clamped <= 0) return stops[0];
  if (clamped >= 1) return stops[stops.length - 1];
  const idx = clamped * (stops.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.min(stops.length - 1, lo + 1);
  const f = idx - lo;
  const a = stops[lo];
  const b = stops[hi];
  return [
    a[0] + (b[0] - a[0]) * f,
    a[1] + (b[1] - a[1]) * f,
    a[2] + (b[2] - a[2]) * f,
  ];
}

export function viridis(t: number): Triplet {
  return lerp(VIRIDIS_STOPS, t);
}

export function hot(t: number): Triplet {
  return lerp(HOT_STOPS, t);
}

export type Colormap = "viridis" | "hot";

export function sample(map: Colormap, t: number): Triplet {
  return map === "viridis" ? viridis(t) : hot(t);
}

/**
 * Discrete palette for layer-index coloring. Eight distinct hues that
 * cycle through the palette, so adjacent layers differ obviously and
 * the layer slider produces visible per-step changes. Hand-picked for
 * contrast on white and dark backgrounds.
 */
const LAYER_PALETTE: ReadonlyArray<Triplet> = [
  [0.86, 0.21, 0.27],  // crimson
  [0.96, 0.49, 0.0],   // orange
  [0.94, 0.78, 0.06],  // amber
  [0.36, 0.7, 0.34],   // green
  [0.16, 0.58, 0.58],  // teal
  [0.2, 0.46, 0.78],   // blue
  [0.5, 0.3, 0.7],     // purple
  [0.78, 0.36, 0.62],  // magenta
];

export function layerColor(layerIndex: number): Triplet {
  if (!Number.isFinite(layerIndex) || layerIndex < 0) return LAYER_PALETTE[0];
  return LAYER_PALETTE[layerIndex % LAYER_PALETTE.length];
}
