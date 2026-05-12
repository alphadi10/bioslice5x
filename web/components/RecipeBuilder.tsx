"use client";

/**
 * Forms-driven recipe editor — every input maps to a field in the
 * pydantic Recipe schema. No surrounding marketing copy; the bioink
 * dropdown labels surface calibration status inline.
 *
 * Section order intentional: slicing params first (they set the rest of
 * the print), then per-syringe panels. Adding a syringe defaults to the
 * previous one's needle/bioink so multi-material setups don't require
 * re-typing every field.
 */

import { useId } from "react";
import type {
  BioinkRecord,
  CellPayloadRecord,
  Recipe,
  Region,
  Syringe,
} from "@/lib/types";
import { NEEDLE_GAUGES } from "@/lib/defaults";

interface Props {
  recipe: Recipe;
  bioinks: BioinkRecord[];
  cells: CellPayloadRecord[];
  onChange: (r: Recipe) => void;
}

export function RecipeBuilder({ recipe, bioinks, cells, onChange }: Props) {
  function updateSyringe(i: number, patch: Partial<Syringe>) {
    const next = recipe.syringes.map((s, idx) =>
      idx === i ? { ...s, ...patch } : s
    );
    onChange({ ...recipe, syringes: next });
  }

  function addSyringe() {
    const nextId = Math.max(-1, ...recipe.syringes.map((s) => s.id)) + 1;
    const template = recipe.syringes[recipe.syringes.length - 1];
    const newSyringe: Syringe = {
      ...template,
      id: nextId,
      region: { kind: "all" },
    };
    onChange({ ...recipe, syringes: [...recipe.syringes, newSyringe] });
  }

  function removeSyringe(i: number) {
    if (recipe.syringes.length <= 1) return;
    onChange({
      ...recipe,
      syringes: recipe.syringes.filter((_, idx) => idx !== i),
    });
  }

  return (
    <div className="space-y-5">
      <Section title="Slicing parameters">
        <SlicingParamsEditor recipe={recipe} onChange={onChange} />
      </Section>

      {recipe.syringes.map((syringe, i) => (
        <Section
          key={syringe.id}
          title={`Syringe ${syringe.id}`}
          right={
            recipe.syringes.length > 1 ? (
              <button
                type="button"
                onClick={() => removeSyringe(i)}
                className="text-xs text-neutral-500 hover:text-red-700 hover:underline"
              >
                Remove
              </button>
            ) : null
          }
        >
          <SyringeEditor
            syringe={syringe}
            recipe={recipe}
            bioinks={bioinks}
            cells={cells}
            onChange={(patch) => updateSyringe(i, patch)}
          />
        </Section>
      ))}

      <button
        type="button"
        onClick={addSyringe}
        className="text-xs text-neutral-600 hover:underline"
      >
        + Add syringe
      </button>
    </div>
  );
}

function Section({
  title,
  children,
  right,
}: {
  title: string;
  children: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between border-b border-neutral-200 pb-1">
        <h2 className="text-sm font-medium tracking-tight">{title}</h2>
        {right}
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function SlicingParamsEditor({
  recipe,
  onChange,
}: {
  recipe: Recipe;
  onChange: (r: Recipe) => void;
}) {
  const s = recipe.slicing;
  function patch(p: Partial<typeof s>) {
    onChange({ ...recipe, slicing: { ...s, ...p } });
  }
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <NumberField
        label="Layer height (mm)"
        value={s.layer_height_mm}
        step={0.05}
        min={0.05}
        onChange={(v) => patch({ layer_height_mm: v })}
      />
      <NumberField
        label="Line width (mm)"
        value={s.line_width_mm}
        step={0.05}
        min={0.05}
        onChange={(v) => patch({ line_width_mm: v })}
      />
      <NumberField
        label="Print feed (mm/min)"
        value={s.print_speed_mm_per_min}
        step={50}
        min={1}
        onChange={(v) => patch({ print_speed_mm_per_min: v })}
      />
      <NumberField
        label="Travel feed (mm/min)"
        value={s.travel_speed_mm_per_min}
        step={100}
        min={1}
        onChange={(v) => patch({ travel_speed_mm_per_min: v })}
      />
      <NumberField
        label="Infill density"
        value={s.infill_density}
        step={0.05}
        min={0}
        max={1}
        onChange={(v) => patch({ infill_density: v })}
      />
      <SelectField
        label="Slicing mode"
        value={s.mode.kind}
        onChange={(v) =>
          patch({
            mode:
              v === "flat"
                ? { kind: "flat" }
                : {
                    kind: "wrap_around_axis",
                    wrap_axis: "z",
                    cylinder_radius_mm: 5,
                    arc_start_deg: -180,
                    arc_end_deg: 180,
                    conformal_arc_sampling_mm: null,
                    allow_tilt_arc_split: false,
                    arc_split_count: 1,
                  },
          })
        }
        options={[
          { value: "flat", label: "Flat (planar layers)" },
          {
            value: "wrap_around_axis",
            label: "Wrap around axis (conformal)",
          },
        ]}
      />
    </div>
  );
}

function SyringeEditor({
  syringe,
  recipe,
  bioinks,
  cells,
  onChange,
}: {
  syringe: Syringe;
  recipe: Recipe;
  bioinks: BioinkRecord[];
  cells: CellPayloadRecord[];
  onChange: (patch: Partial<Syringe>) => void;
}) {
  // Soft sanity check on the deposition ratio (line_width / needle_ID).
  // The bath supports the deposited filament so FRESH tolerates a wider
  // range than air FDM, but extreme ratios still misbehave: under ~0.7
  // the line thins as the bath drags more than the needle extrudes;
  // over ~1.6 the line piles up and adjacent passes overlap. Only the
  // out-of-range case shows a hint — in-range stays silent.
  const ratio =
    syringe.needle.inner_diameter_mm > 0
      ? recipe.slicing.line_width_mm / syringe.needle.inner_diameter_mm
      : 0;
  let depositionHint: string | null = null;
  if (ratio > 0 && ratio < 0.7) {
    depositionHint = `line width is ${(ratio * 100).toFixed(0)}% of needle ID — filament may thin in the bath`;
  } else if (ratio > 1.6) {
    depositionHint = `line width is ${ratio.toFixed(1)}× needle ID — adjacent passes may overlap`;
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <SelectField
          label="Bioink"
          value={syringe.bioink}
          onChange={(v) => onChange({ bioink: v })}
          options={bioinks.map((b) => ({
            value: b.name,
            label: b.calibrated ? b.name : `${b.name} (uncalibrated)`,
          }))}
        />
        <SelectField
          label="Cell payload"
          value={syringe.cell_payload}
          onChange={(v) => onChange({ cell_payload: v })}
          options={cells.map((c) => ({
            value: c.name,
            label: `${c.name} (${c.max_wall_shear_stress_pa.toFixed(0)} Pa max)`,
          }))}
        />
        <SelectField
          label="Needle"
          value={String(syringe.needle.inner_diameter_mm)}
          onChange={(v) => {
            const idMm = parseFloat(v);
            const match = NEEDLE_GAUGES.find((g) => g.idMm === idMm);
            onChange({
              needle: {
                ...syringe.needle,
                inner_diameter_mm: idMm,
                gauge_label: match?.label.split(" ")[0] ?? "",
              },
            });
          }}
          options={NEEDLE_GAUGES.map((g) => ({
            value: String(g.idMm),
            label: g.label,
          }))}
        />
        <RegionEditor
          region={syringe.region}
          onChange={(region) => onChange({ region })}
        />
      </div>
      {depositionHint && (
        <p className="text-xs text-amber-700">{depositionHint}</p>
      )}
    </div>
  );
}

function RegionEditor({
  region,
  onChange,
}: {
  region: Region;
  onChange: (r: Region) => void;
}) {
  return (
    <div className="space-y-2">
      <SelectField
        label="Region"
        value={region.kind}
        onChange={(v) =>
          onChange(
            v === "all"
              ? { kind: "all" }
              : {
                  kind: "bbox",
                  min: region.kind === "bbox" ? region.min : [-10, -10, 0],
                  max: region.kind === "bbox" ? region.max : [10, 10, 10],
                }
          )
        }
        options={[
          { value: "all", label: "All (whole mesh)" },
          { value: "bbox", label: "Bounding box" },
        ]}
      />
      {region.kind === "bbox" && (
        <div className="grid grid-cols-3 gap-2">
          {(["x", "y", "z"] as const).map((axis, i) => (
            <div key={axis} className="border border-neutral-200 p-2">
              <div className="text-[10px] font-medium uppercase tracking-wide text-neutral-500">
                {axis}
              </div>
              <NumberField
                label="min"
                value={region.min[i]}
                step={0.5}
                onChange={(v) => {
                  const min: [number, number, number] = [...region.min];
                  min[i] = v;
                  onChange({ ...region, min });
                }}
              />
              <NumberField
                label="max"
                value={region.max[i]}
                step={0.5}
                onChange={(v) => {
                  const max: [number, number, number] = [...region.max];
                  max[i] = v;
                  onChange({ ...region, max });
                }}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function NumberField({
  label,
  value,
  step,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  step?: number;
  min?: number;
  max?: number;
  onChange: (v: number) => void;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="block">
      <span className="block text-xs text-neutral-600">{label}</span>
      <input
        id={id}
        type="number"
        value={Number.isFinite(value) ? value : 0}
        step={step}
        min={min}
        max={max}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          onChange(Number.isFinite(v) ? v : 0);
        }}
        className="mt-1 w-full rounded-sm border border-neutral-300 px-2 py-1 font-mono text-sm"
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (v: string) => void;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="block">
      <span className="block text-xs text-neutral-600">{label}</span>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-sm border border-neutral-300 px-2 py-1 text-sm"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
