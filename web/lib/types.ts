/**
 * TypeScript mirrors of the bioslice5x pydantic schema.
 *
 * These are the shapes exchanged with the Python API. They map 1:1 to
 * `bioslice5x.recipe.models.*` and `bioslice5x.profile.models.*` — keep
 * this file in sync with the Python schema, or use the generated JSON
 * Schemas in `/schemas/` as the source of truth.
 */

export interface RheologicalModel {
  kind: "newtonian" | "power_law" | "herschel_bulkley";
  viscosity_pa_s: number | null;
  consistency_k: number | null;
  flow_index_n: number | null;
  yield_stress_pa: number | null;
}

export interface BioinkRecord {
  name: string;
  density_g_per_mL: number;
  rheology: RheologicalModel;
  working_temperature_c: [number, number];
  crosslinking: "thermal" | "ionic" | "photo" | "enzymatic" | "none";
  calibrated_against: string;
  calibrated: boolean;
  notes: string;
}

export interface CellPayloadRecord {
  name: string;
  cell_type: string;
  cell_density_per_mL: number;
  max_wall_shear_stress_pa: number;
  calibrated_against: string;
  calibrated: boolean;
  notes: string;
}

export interface KinematicAxis {
  letter: string;
  rotates_about: "x" | "y" | "z";
  range_deg: [number, number];
  invert: boolean;
}

export interface KinematicChain {
  kind: "three_axis" | "tilt_swivel";
  tilt?: KinematicAxis;
  swivel?: KinematicAxis;
}

export interface ProfileRecord {
  name: string;
  firmware: string;
  build_volume: {
    x_mm: [number, number];
    y_mm: [number, number];
    z_mm: [number, number];
  };
  kinematic_chain: KinematicChain;
}

// -------------------------------------------------------------------
// Recipe — sent in `POST /api/slice`.
// -------------------------------------------------------------------

export interface Needle {
  inner_diameter_mm: number;
  length_mm: number;
  gauge_label: string;
}

export type Region =
  | { kind: "all" }
  | { kind: "bbox"; min: [number, number, number]; max: [number, number, number] };

export interface Syringe {
  id: number;
  bioink: string;
  cell_payload: string;
  needle: Needle;
  region: Region;
  purge_volume_uL: number;
  barrel_inner_diameter_mm: number;
  total_volume_uL: number;
  temperature_setpoint_c: number | null;
  /** Volumetric retract before each travel + at end-of-print.
   * 0 disables retract entirely. Defaults to 0.5 µL — sensible for
   * 22-25G needles on 1 mL slip-tip syringes. Tune per syringe + bioink. */
  retract_volume_uL: number;
}

export type SlicingMode =
  | { kind: "flat" }
  | {
      kind: "wrap_around_axis";
      wrap_axis: "x" | "y" | "z";
      cylinder_radius_mm: number;
      arc_start_deg: number;
      arc_end_deg: number;
      conformal_arc_sampling_mm: number | null;
      allow_tilt_arc_split: boolean;
      arc_split_count: number;
    };

export interface SlicingParams {
  layer_height_mm: number;
  line_width_mm: number;
  print_speed_mm_per_min: number;
  travel_speed_mm_per_min: number;
  travel_speed_reduction_in_bath: number;
  mode: SlicingMode;
  infill_density: number;
  infill_pattern: "rectilinear";
  infill_angle_deg: number;
  /** Tilt-magnitude threshold for the singularity smoother. Vertices
   * whose tilt sits inside this band get their swivel linearly
   * interpolated across contiguous in-band runs. Recipe-controlled so
   * lab calibration can tune. Default 2°. */
  singularity_threshold_deg: number;
  /** Safe-park clearance for end-of-print: the EOF sequence raises Z by
   * this many mm before homing rotaries, so the needle clears the bath. */
  safe_park_clearance_mm: number;
}

export type PrintOrientation =
  | { kind: "fixed"; tilt_deg: number; swivel_deg: number }
  | { kind: "per_layer"; tilts_deg: number[]; swivels_deg: number[] };

export interface Recipe {
  name: string;
  syringes: Syringe[];
  slicing: SlicingParams;
  print_orientation: PrintOrientation;
  bath: null;
  notes: string;
}

// -------------------------------------------------------------------
// Slice API response.
// -------------------------------------------------------------------

export interface SliceStats {
  total_moves: number;
  estimated_seconds: number;
  max_wall_shear_pa: number;
  max_wall_shear_by_syringe: Record<string, number>;
  threshold_by_syringe: Record<string, number>;
  total_bioink_uL_by_syringe: Record<string, number>;
  syringe_count: number;
}

export interface SliceResponse {
  gcode: string;
  stats: SliceStats;
}

export interface CellViabilityError {
  kind: "cell_viability";
  segment_id: string;
  computed_wall_shear_pa: number;
  threshold_pa: number;
  bioink_name: string;
  cell_type: string;
  remediation: string;
}

export interface ApiErrorPayload {
  message: string;
  type?: string;
  detail?: string;
  /** Optional pydantic field path for validation errors. */
  field?: string;
}

export interface ApiError {
  error: ApiErrorPayload | CellViabilityError;
}
