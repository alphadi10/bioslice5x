/**
 * Recipe import / export and localStorage persistence.
 *
 * Wet-lab users iterate on the same recipe over hours — tweak shear,
 * needle, region; re-slice; tweak again. A page reload mid-session
 * losing two hours of calibration work is the single most painful UX
 * gap the audit flagged. This module gives:
 *
 *  - `exportRecipeYaml` / `importRecipeYaml`: round-trip the same YAML
 *    shape the Python CLI consumes (`uv run bioslice5x slice ...`), so
 *    a UI-tuned recipe can be handed straight to the CLI on a real
 *    print rig or shared with a collaborator by email.
 *  - `loadStoredRecipe` / `saveStoredRecipe`: opportunistic
 *    localStorage persistence keyed by version. Non-fatal on any
 *    error — we never want the editor to crash because the user has a
 *    stale stored shape; we just fall back to the bundled default.
 *
 * Import is permissive: zod validates the shape and fills missing
 * optional fields with sensible defaults, so older YAML files (pre
 * v0.1.2, without retract_volume_uL) still load.
 */

import yaml from "js-yaml";
import { z } from "zod";
import type { Recipe } from "@/lib/types";
import { DEFAULT_RECIPE } from "@/lib/defaults";

const STORAGE_KEY = "bioslice5x:recipe:v1";

const needleSchema = z.object({
  inner_diameter_mm: z.number().positive(),
  length_mm: z.number().positive(),
  gauge_label: z.string().default(""),
});

const regionSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("all") }),
  z.object({
    kind: z.literal("bbox"),
    min: z.tuple([z.number(), z.number(), z.number()]),
    max: z.tuple([z.number(), z.number(), z.number()]),
  }),
]);

const syringeSchema = z.object({
  id: z.number().int().nonnegative(),
  bioink: z.string(),
  cell_payload: z.string(),
  needle: needleSchema,
  region: regionSchema.default({ kind: "all" }),
  purge_volume_uL: z.number().nonnegative().default(5),
  barrel_inner_diameter_mm: z.number().positive().default(4.65),
  total_volume_uL: z.number().positive().default(1000),
  temperature_setpoint_c: z.number().nullable().default(null),
  retract_volume_uL: z.number().nonnegative().default(0.5),
});

const slicingModeSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("flat") }),
  z.object({
    kind: z.literal("wrap_around_axis"),
    wrap_axis: z.enum(["x", "y", "z"]),
    cylinder_radius_mm: z.number().positive(),
    arc_start_deg: z.number().default(-180),
    arc_end_deg: z.number().default(180),
    conformal_arc_sampling_mm: z.number().positive().nullable().default(null),
    allow_tilt_arc_split: z.boolean().default(false),
    arc_split_count: z.number().int().min(1).default(1),
  }),
]);

const slicingParamsSchema = z.object({
  layer_height_mm: z.number().positive().default(0.2),
  line_width_mm: z.number().positive().default(0.4),
  print_speed_mm_per_min: z.number().positive().default(600),
  travel_speed_mm_per_min: z.number().positive().default(1200),
  travel_speed_reduction_in_bath: z.number().positive().max(1).default(0.5),
  mode: slicingModeSchema.default({ kind: "flat" }),
  infill_density: z.number().min(0).max(1).default(0),
  infill_pattern: z.literal("rectilinear").default("rectilinear"),
  infill_angle_deg: z.number().default(0),
  singularity_threshold_deg: z.number().positive().max(15).default(2),
  safe_park_clearance_mm: z.number().nonnegative().default(10),
});

const printOrientationSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("fixed"),
    tilt_deg: z.number().default(0),
    swivel_deg: z.number().default(0),
  }),
  z.object({
    kind: z.literal("per_layer"),
    tilts_deg: z.array(z.number()).default([]),
    swivels_deg: z.array(z.number()).default([]),
  }),
]);

const recipeSchema = z.object({
  name: z.string().min(1),
  syringes: z.array(syringeSchema).min(1),
  slicing: slicingParamsSchema.default({} as never),
  print_orientation: printOrientationSchema.default({
    kind: "fixed",
    tilt_deg: 0,
    swivel_deg: 0,
  }),
  bath: z.null().default(null),
  notes: z.string().default(""),
});

/** Serialize a recipe to the same YAML shape the Python CLI consumes. */
export function exportRecipeYaml(recipe: Recipe): string {
  // js-yaml.dump prints lists indented and quotes only when needed —
  // matches the human-edited samples shipped in /samples/.
  return yaml.dump(recipe, {
    indent: 2,
    lineWidth: 100,
    noRefs: true,
    sortKeys: false,
  });
}

export class RecipeParseError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = "RecipeParseError";
  }
}

/** Parse a YAML string into a Recipe. Permissive about missing optional
 *  fields (zod fills defaults); strict about the required structure. */
export function importRecipeYaml(text: string): Recipe {
  let parsed: unknown;
  try {
    parsed = yaml.load(text);
  } catch (exc) {
    throw new RecipeParseError(
      `YAML syntax error: ${exc instanceof Error ? exc.message : String(exc)}`,
      exc
    );
  }
  if (parsed === null || typeof parsed !== "object") {
    throw new RecipeParseError(
      "Recipe YAML must be a mapping at the top level (got " +
        (parsed === null ? "null" : typeof parsed) +
        ")"
    );
  }
  const result = recipeSchema.safeParse(parsed);
  if (!result.success) {
    const firstIssue = result.error.issues[0];
    const path = firstIssue.path.join(".");
    throw new RecipeParseError(
      `Recipe validation failed at ${path || "<root>"}: ${firstIssue.message}`,
      result.error
    );
  }
  return result.data as Recipe;
}

/** Trigger a browser download of `recipe` as a `.yaml` file. */
export function downloadRecipeYaml(recipe: Recipe): void {
  const text = exportRecipeYaml(recipe);
  const blob = new Blob([text], { type: "text/yaml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${sanitizeFilename(recipe.name || "recipe")}.yaml`;
  a.click();
  URL.revokeObjectURL(url);
}

function sanitizeFilename(name: string): string {
  return name.replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 80) || "recipe";
}

/** Read the last-stored recipe out of localStorage, or return null. */
export function loadStoredRecipe(): Recipe | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const result = recipeSchema.safeParse(parsed);
    if (!result.success) return null;
    return result.data as Recipe;
  } catch {
    return null;
  }
}

/** Persist `recipe` to localStorage. Non-fatal on quota / private-mode errors. */
export function saveStoredRecipe(recipe: Recipe): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(recipe));
  } catch {
    // private mode or quota exceeded — silently no-op.
  }
}

/** Reset to the bundled default and clear stored state. */
export function clearStoredRecipe(): Recipe {
  if (typeof window !== "undefined") {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }
  return DEFAULT_RECIPE;
}
