/**
 * Default recipe — tuned to give a usable FRESH starting point that
 * slices without tripping the cell-viability check for the
 * default-shipped collagen + general-mammalian pair.
 *
 * The shear envelope (Newtonian estimate with bulk viscosity = K = 80
 * Pa·s for collagen-I @ 8 mg/mL) constrains the (needle, line_width,
 * layer_height, feed) tuple. With the values below:
 *
 *   τ_wall = 4·μ·Q / (π·r³)
 *          = 4·80·(0.84e-3·0.3e-3·5e-3) / (π·(0.42e-3)³)
 *          ≈ 1.75 kPa
 *
 * That sits safely under the 5 kPa general-mammalian threshold and the
 * 2 kPa hUVEC threshold; MIN6 β-cells (1.5 kPa) would be borderline,
 * which is correct — that recipe demands a custom slowdown or a finer
 * gauge, and the slicer's CellViabilityError will tell the user so
 * with a specific remediation hint.
 *
 * The line-width / needle-ID ratio is exactly 1.0× — the bath holds
 * the deposited filament at the same nominal cross-section as the
 * needle, which is the FRESH "neutral" condition (no thinning, no
 * piling). The recipe builder surfaces an inline hint if the ratio
 * drifts outside [0.7, 1.6].
 */

import type { Recipe } from "@/lib/types";

export const DEFAULT_RECIPE: Recipe = {
  name: "my_recipe",
  syringes: [
    {
      id: 0,
      bioink: "collagen_i_8mg_per_mL",
      cell_payload: "general_mammalian",
      needle: { inner_diameter_mm: 0.84, length_mm: 12.7, gauge_label: "18G" },
      region: { kind: "all" },
      purge_volume_uL: 5,
      barrel_inner_diameter_mm: 4.65,
      total_volume_uL: 1000,
      temperature_setpoint_c: null,
      retract_volume_uL: 0.5,
    },
  ],
  slicing: {
    layer_height_mm: 0.3,
    line_width_mm: 0.84,
    print_speed_mm_per_min: 300,
    travel_speed_mm_per_min: 1200,
    travel_speed_reduction_in_bath: 0.5,
    mode: { kind: "flat" },
    infill_density: 0.2,
    infill_pattern: "rectilinear",
    infill_angle_deg: 0,
    singularity_threshold_deg: 2,
    safe_park_clearance_mm: 10,
  },
  print_orientation: { kind: "fixed", tilt_deg: 0, swivel_deg: 0 },
  bath: null,
  notes: "",
};

// Common blunt-tip dispensing needle gauges. IDs are nominal manufacturer
// values for plastic blunt-tip needles used in bioprinting; some gauges
// have ID variants by vendor — verify if precision matters.
export const NEEDLE_GAUGES: ReadonlyArray<{ label: string; idMm: number }> = [
  { label: "14G (1.55 mm ID)", idMm: 1.55 },
  { label: "16G (1.19 mm ID)", idMm: 1.19 },
  { label: "18G (0.84 mm ID)", idMm: 0.84 },
  { label: "20G (0.60 mm ID)", idMm: 0.6 },
  { label: "22G (0.41 mm ID)", idMm: 0.41 },
  { label: "25G (0.26 mm ID)", idMm: 0.26 },
  { label: "27G (0.21 mm ID)", idMm: 0.21 },
  { label: "30G (0.15 mm ID)", idMm: 0.15 },
];
