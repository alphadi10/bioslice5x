"use client";

/**
 * Overlay color-bar legend for the toolpath viewer.
 *
 * Renders a 12-stop gradient strip with min / max tick labels in the
 * active scalar's unit (mm for "Z height", Pa for "Wall shear"). A
 * red over-threshold tick highlights values above the cell-viability
 * cap when shear-mode is active so a lab reader instantly sees which
 * stretch of the print would exceed the configured threshold.
 *
 * The legend is purely declarative — colors come from the same
 * colormap utilities the viewer uses, so the canvas and legend stay
 * in lockstep automatically.
 */

import { sample as sampleColormap } from "@/lib/colormaps";

export type LegendRange = {
  lo: number;
  hi: number;
  unit: string;
  label: string;
};

const STOPS = 12;

export interface ColorBarLegendProps {
  range: LegendRange | null;
  /** Active colormap kind — must match the viewer. */
  colormap: "viridis" | "hot";
  /** Optional shear-violation threshold to mark with a red tick. */
  thresholdPa?: number | null;
  className?: string;
}

function fmtValue(v: number, unit: string): string {
  const abs = Math.abs(v);
  if (unit === "Pa") {
    if (abs >= 1000) return `${(v / 1000).toFixed(2)} kPa`;
    return `${v.toFixed(0)} ${unit}`;
  }
  if (abs >= 100) return `${v.toFixed(0)} ${unit}`;
  if (abs >= 10) return `${v.toFixed(1)} ${unit}`;
  return `${v.toFixed(2)} ${unit}`;
}

export function ColorBarLegend({
  range,
  colormap,
  thresholdPa,
  className,
}: ColorBarLegendProps) {
  if (!range) return null;
  const span = range.hi - range.lo;
  const ticks = Array.from({ length: STOPS }, (_, i) => i / (STOPS - 1));
  const showThreshold =
    range.unit === "Pa" && thresholdPa !== null && thresholdPa !== undefined;
  const thresholdT =
    showThreshold && span > 0
      ? Math.max(0, Math.min(1, ((thresholdPa as number) - range.lo) / span))
      : null;
  return (
    <div
      className={
        "pointer-events-none absolute bottom-3 right-3 w-44 select-none " +
        "border border-neutral-200 bg-white/90 px-3 py-2 text-[11px] " +
        "shadow-sm backdrop-blur-sm " +
        (className ?? "")
      }
      aria-label={`${range.label} color legend, ${fmtValue(range.lo, range.unit)} to ${fmtValue(range.hi, range.unit)}`}
    >
      <div className="flex items-baseline justify-between font-medium tracking-tight text-neutral-700">
        <span>{range.label}</span>
        <span className="font-mono text-[10px] text-neutral-500">
          {range.unit}
        </span>
      </div>
      <div className="relative mt-1 h-2 w-full overflow-hidden rounded-[1px]">
        <div className="flex h-2 w-full">
          {ticks.map((t, i) => {
            const [r, g, b] = sampleColormap(colormap, t);
            const color = `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)})`;
            return (
              <div
                key={i}
                style={{ background: color, flex: 1 }}
                aria-hidden="true"
              />
            );
          })}
        </div>
        {thresholdT !== null && (
          <div
            aria-hidden="true"
            style={{ left: `${thresholdT * 100}%` }}
            className="absolute top-0 h-2 w-px bg-red-600"
            title="Cell-viability threshold"
          />
        )}
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-neutral-600">
        <span>{fmtValue(range.lo, range.unit)}</span>
        <span>{fmtValue(range.hi, range.unit)}</span>
      </div>
      {thresholdT !== null && (
        <div className="mt-0.5 text-[10px] text-red-700">
          ━ threshold {fmtValue(thresholdPa as number, range.unit)}
        </div>
      )}
    </div>
  );
}
