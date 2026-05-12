"use client";

/**
 * BioSlice5X web — single-page slicer + viewer + recipe builder.
 *
 * Layout: header with repo + docs links, two-pane body (recipe left,
 * viewer right), footer with minimal citation. No marketing copy.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  SliceApiError,
  SliceCellViabilityError,
  fetchBioinks,
  fetchCells,
  fetchProfiles,
  slice,
} from "@/lib/api";
import { DEFAULT_RECIPE } from "@/lib/defaults";
import { computeLayerIndices, parseGcode } from "@/lib/gcode-parser";
import {
  RecipeParseError,
  downloadRecipeYaml,
  importRecipeYaml,
  loadStoredRecipe,
  saveStoredRecipe,
} from "@/lib/recipe-io";
import type {
  BioinkRecord,
  CellPayloadRecord,
  ProfileRecord,
  Recipe,
  SliceResponse,
} from "@/lib/types";
import { RecipeBuilder } from "@/components/RecipeBuilder";
import { ToolpathViewer, type ColorMode } from "@/components/ToolpathViewer";
import { ColorBarLegend, type LegendRange } from "@/components/ColorBarLegend";

const MAX_MESH_BYTES = 50 * 1024 * 1024;

const REPO_URL = "https://github.com/alphadi10/bioslice5x";
const DOCS_URL = "https://github.com/alphadi10/bioslice5x#readme";
const BIOPRINTING_NOTES_URL =
  "https://github.com/alphadi10/bioslice5x/blob/main/docs/BIOPRINTING_REQUIREMENTS.md";

interface LoadedMesh {
  name: string;
  format: "stl" | "obj";
  bytes: ArrayBuffer;
}

export default function HomePage() {
  const [bioinks, setBioinks] = useState<BioinkRecord[]>([]);
  const [cells, setCells] = useState<CellPayloadRecord[]>([]);
  const [profiles, setProfiles] = useState<ProfileRecord[]>([]);
  const [libraryError, setLibraryError] = useState<string | null>(null);

  const [recipe, setRecipe] = useState<Recipe>(DEFAULT_RECIPE);
  const [profile, setProfile] = useState<string>("hypothetical_3axis");
  const [mesh, setMesh] = useState<LoadedMesh | null>(null);

  const [slicing, setSlicing] = useState(false);
  const [sliceError, setSliceError] = useState<SliceApiError | string | null>(
    null
  );
  const [viabilityError, setViabilityError] =
    useState<SliceCellViabilityError | null>(null);
  const [sliceResult, setSliceResult] = useState<SliceResponse | null>(null);

  const [colorMode, setColorMode] = useState<ColorMode>("layer");
  const [showMeshOverlay, setShowMeshOverlay] = useState<boolean>(true);
  // Dual-thumb layer scrubber: inspect a [min, max] band of the print.
  const [clipMinFraction, setClipMinFraction] = useState<number>(0);
  const [clipMaxFraction, setClipMaxFraction] = useState<number>(1);
  const [legendRange, setLegendRange] = useState<LegendRange | null>(null);
  const [recipeIoMessage, setRecipeIoMessage] = useState<string | null>(null);
  const importInputRef = useRef<HTMLInputElement | null>(null);

  // Rehydrate the user's last-edited recipe on mount. Falls back to the
  // bundled default if storage is empty / malformed / private-mode.
  useEffect(() => {
    const stored = loadStoredRecipe();
    if (stored) setRecipe(stored);
  }, []);

  // Persist recipe edits opportunistically; safe to call on every render.
  useEffect(() => {
    saveStoredRecipe(recipe);
  }, [recipe]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchBioinks(), fetchCells(), fetchProfiles()])
      .then(([b, c, p]) => {
        if (cancelled) return;
        setBioinks(b);
        setCells(c);
        setProfiles(p);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setLibraryError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const parsed = useMemo(() => {
    if (!sliceResult) return null;
    return parseGcode(sliceResult.gcode);
  }, [sliceResult]);

  const layerIndices = useMemo(() => {
    if (!parsed) return new Int32Array();
    return computeLayerIndices(parsed.moves);
  }, [parsed]);

  const maxLayer =
    layerIndices.length > 0 ? layerIndices[layerIndices.length - 1] : 0;
  const clipRangeMin = Math.round(clipMinFraction * maxLayer);
  const clipRangeMaxRaw = Math.round(clipMaxFraction * maxLayer);
  // Guard against the user dragging max below min by enforcing min<=max.
  const clipRangeMax = Math.max(clipRangeMin, clipRangeMaxRaw);

  const buildVolume = useMemo(() => {
    const p = profiles.find((pp) => pp.name === profile);
    if (!p) return null;
    return {
      xMm: p.build_volume.x_mm,
      yMm: p.build_volume.y_mm,
      zMm: p.build_volume.z_mm,
    };
  }, [profiles, profile]);

  const cellShearThresholdPa = useMemo(() => {
    if (colorMode !== "shear" || !sliceResult) return null;
    const thresholds = Object.values(sliceResult.stats.threshold_by_syringe);
    if (thresholds.length === 0) return null;
    return Math.min(...thresholds);
  }, [colorMode, sliceResult]);

  async function onFilePicked(file: File) {
    if (file.size > MAX_MESH_BYTES) {
      setSliceError(
        `Mesh too large: ${(file.size / 1024 / 1024).toFixed(1)} MB exceeds the ` +
          `50 MB API limit. Decimate the mesh (Meshmixer / Blender) or split ` +
          `into smaller regions before uploading.`
      );
      return;
    }
    setSliceError(null);
    const fmt: "stl" | "obj" = file.name.toLowerCase().endsWith(".obj")
      ? "obj"
      : "stl";
    const bytes = await file.arrayBuffer();
    setMesh({ name: file.name, format: fmt, bytes });
  }

  async function onSlice() {
    if (!mesh) {
      setSliceError("Pick an STL file first.");
      return;
    }
    setSlicing(true);
    setSliceError(null);
    setViabilityError(null);
    setSliceResult(null);
    try {
      const res = await slice({
        mesh: { format: mesh.format, bytes: mesh.bytes },
        profile,
        recipe,
      });
      setSliceResult(res);
      setClipMinFraction(0);
      setClipMaxFraction(1);
    } catch (e) {
      if (e instanceof SliceCellViabilityError) {
        setViabilityError(e);
      } else if (e instanceof SliceApiError) {
        setSliceError(e);
      } else {
        setSliceError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setSlicing(false);
    }
  }

  const onImportRecipe = useCallback(async (file: File) => {
    setRecipeIoMessage(null);
    try {
      const text = await file.text();
      const parsed = importRecipeYaml(text);
      setRecipe(parsed);
      setRecipeIoMessage(`Loaded recipe "${parsed.name}" from ${file.name}.`);
    } catch (exc) {
      const msg =
        exc instanceof RecipeParseError
          ? exc.message
          : exc instanceof Error
            ? exc.message
            : String(exc);
      setRecipeIoMessage(`Import failed — ${msg}`);
    }
  }, []);

  function onExportRecipe() {
    downloadRecipeYaml(recipe);
    setRecipeIoMessage(`Exported ${recipe.name || "recipe"}.yaml.`);
  }

  function onDownloadGcode() {
    if (!sliceResult) return;
    const blob = new Blob([sliceResult.gcode], {
      type: "text/plain;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${recipe.name || "bioslice5x"}.gcode`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-neutral-200">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3">
          <div className="flex items-baseline gap-3">
            <span className="text-base font-semibold tracking-tight">
              BioSlice5X
            </span>
            <span className="text-xs text-neutral-500">
              5-axis slicer for FRESH bioprinting
            </span>
          </div>
          <nav className="flex items-center gap-4 text-sm text-neutral-700">
            <a
              href={DOCS_URL}
              target="_blank"
              rel="noreferrer"
              className="hover:underline"
            >
              Docs
            </a>
            <a
              href={BIOPRINTING_NOTES_URL}
              target="_blank"
              rel="noreferrer"
              className="hover:underline"
            >
              Notes on bioprinting
            </a>
            <a
              href={REPO_URL}
              target="_blank"
              rel="noreferrer"
              className="hover:underline"
            >
              GitHub
            </a>
          </nav>
        </div>
      </header>

      {libraryError && (
        <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
          Library failed to load: {libraryError}
        </div>
      )}

      <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 px-4 py-6 lg:flex-row">
        <section className="flex w-full flex-col gap-5 lg:w-[420px] lg:shrink-0">
          <MeshAndProfile
            mesh={mesh}
            profile={profile}
            profiles={profiles}
            onFile={onFilePicked}
            onProfile={setProfile}
          />

          <div className="flex items-center justify-between gap-2 text-xs">
            <div className="font-medium tracking-tight text-neutral-700">
              Recipe
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => importInputRef.current?.click()}
                className="rounded-sm border border-neutral-300 px-2 py-0.5 text-[11px] hover:bg-neutral-100"
              >
                Import YAML
              </button>
              <button
                type="button"
                onClick={onExportRecipe}
                className="rounded-sm border border-neutral-300 px-2 py-0.5 text-[11px] hover:bg-neutral-100"
              >
                Export YAML
              </button>
              <input
                ref={importInputRef}
                type="file"
                accept=".yaml,.yml,application/x-yaml,text/yaml"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void onImportRecipe(f);
                  // Reset so the same file can be re-picked.
                  e.target.value = "";
                }}
              />
            </div>
          </div>
          {recipeIoMessage && (
            <p className="text-[11px] text-neutral-600">{recipeIoMessage}</p>
          )}

          <RecipeBuilder
            recipe={recipe}
            bioinks={bioinks}
            cells={cells}
            onChange={setRecipe}
          />

          <div className="space-y-2">
            <button
              type="button"
              onClick={onSlice}
              disabled={!mesh || slicing}
              className="w-full rounded-sm bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
            >
              {slicing ? "Slicing…" : "Slice"}
            </button>
            {sliceResult && (
              <button
                type="button"
                onClick={onDownloadGcode}
                className="w-full rounded-sm border border-neutral-300 px-4 py-2 text-sm hover:bg-neutral-100"
              >
                Download G-code
              </button>
            )}
            {sliceError && <SliceErrorNotice err={sliceError} />}
            {viabilityError && (
              <CellViabilityNotice err={viabilityError} />
            )}
          </div>
        </section>

        <section className="flex min-h-[60vh] flex-1 flex-col gap-3 lg:min-h-[600px]">
          <ViewerControls
            sliceResult={sliceResult}
            colorMode={colorMode}
            setColorMode={setColorMode}
            showMeshOverlay={showMeshOverlay}
            setShowMeshOverlay={setShowMeshOverlay}
            clipMinFraction={clipMinFraction}
            setClipMinFraction={setClipMinFraction}
            clipMaxFraction={clipMaxFraction}
            setClipMaxFraction={setClipMaxFraction}
            maxLayer={maxLayer}
            clipRangeMin={clipRangeMin}
            clipRangeMax={clipRangeMax}
          />

          <div className="relative flex-1 border border-neutral-200">
            {parsed ? (
              <>
                <ToolpathViewer
                  moves={parsed.moves}
                  layerIndices={layerIndices}
                  clipRangeMin={clipRangeMin}
                  clipRangeMax={clipRangeMax}
                  colorMode={colorMode}
                  cellShearThresholdPa={cellShearThresholdPa}
                  meshSTL={showMeshOverlay && mesh ? mesh.bytes : null}
                  buildVolume={buildVolume}
                  chain={parsed.chain}
                  onScalarRange={setLegendRange}
                  className="absolute inset-0"
                />
                <ColorBarLegend
                  range={legendRange}
                  colormap={colorMode === "shear" ? "hot" : "viridis"}
                  thresholdPa={cellShearThresholdPa}
                />
              </>
            ) : (
              <ViewerPlaceholder slicing={slicing} />
            )}
          </div>

          {sliceResult && (
            <StressReportPanel result={sliceResult} cells={cells} />
          )}
        </section>
      </main>

      <footer className="border-t border-neutral-200 px-4 py-3 text-xs text-neutral-500">
        <div className="mx-auto max-w-7xl">
          MIT licensed. Cite Lee et al. (Science 2019) and Shiwarski et al.
          (Science Advances 2025) when publishing work that uses this tool.
        </div>
      </footer>
    </div>
  );
}

function MeshAndProfile({
  mesh,
  profile,
  profiles,
  onFile,
  onProfile,
}: {
  mesh: LoadedMesh | null;
  profile: string;
  profiles: ProfileRecord[];
  onFile: (f: File) => void;
  onProfile: (p: string) => void;
}) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium tracking-tight">Input</h2>
      <label className="block">
        <span className="block text-xs text-neutral-600">Mesh</span>
        <input
          type="file"
          accept=".stl,.obj"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void onFile(f);
          }}
          className="mt-1 block w-full text-sm"
        />
        {mesh && (
          <span className="mt-1 block text-xs text-neutral-500">
            {mesh.name} · {(mesh.bytes.byteLength / 1024).toFixed(1)} kB
          </span>
        )}
      </label>
      <label className="block">
        <span className="block text-xs text-neutral-600">Machine profile</span>
        <select
          value={profile}
          onChange={(e) => onProfile(e.target.value)}
          className="mt-1 w-full rounded-sm border border-neutral-300 px-2 py-1 text-sm"
        >
          {profiles.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name} ({p.kinematic_chain.kind})
            </option>
          ))}
        </select>
      </label>
    </section>
  );
}

function ViewerControls({
  sliceResult,
  colorMode,
  setColorMode,
  showMeshOverlay,
  setShowMeshOverlay,
  clipMinFraction,
  setClipMinFraction,
  clipMaxFraction,
  setClipMaxFraction,
  maxLayer,
  clipRangeMin,
  clipRangeMax,
}: {
  sliceResult: SliceResponse | null;
  colorMode: ColorMode;
  setColorMode: (m: ColorMode) => void;
  showMeshOverlay: boolean;
  setShowMeshOverlay: (v: boolean) => void;
  clipMinFraction: number;
  setClipMinFraction: (v: number) => void;
  clipMaxFraction: number;
  setClipMaxFraction: (v: number) => void;
  maxLayer: number;
  clipRangeMin: number;
  clipRangeMax: number;
}) {
  return (
    <div className="flex flex-wrap items-center gap-4 border border-neutral-200 px-4 py-2 text-sm">
      <fieldset className="flex items-center gap-3">
        <legend className="sr-only">Color mode</legend>
        <label className="flex items-center gap-1">
          <input
            type="radio"
            checked={colorMode === "layer"}
            onChange={() => setColorMode("layer")}
            aria-label="Color by layer index"
          />
          <span>Layer</span>
        </label>
        <label className="flex items-center gap-1">
          <input
            type="radio"
            checked={colorMode === "z"}
            onChange={() => setColorMode("z")}
            aria-label="Color by Z height"
          />
          <span>Z height</span>
        </label>
        <label className="flex items-center gap-1">
          <input
            type="radio"
            checked={colorMode === "shear"}
            onChange={() => setColorMode("shear")}
            aria-label="Color by wall shear stress"
          />
          <span>Wall shear</span>
        </label>
      </fieldset>
      <label className="flex items-center gap-1">
        <input
          type="checkbox"
          checked={showMeshOverlay}
          onChange={(e) => setShowMeshOverlay(e.target.checked)}
        />
        <span>Mesh overlay</span>
      </label>
      {sliceResult && maxLayer > 0 && (
        <div className="flex flex-1 items-center gap-2 text-xs">
          <span className="text-neutral-600">Layers</span>
          <div className="flex flex-1 items-center gap-1">
            <input
              type="range"
              min={0}
              max={1}
              step={1 / Math.max(1, maxLayer)}
              value={clipMinFraction}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                setClipMinFraction(Math.min(v, clipMaxFraction));
              }}
              aria-label="First visible layer"
              className="flex-1"
            />
            <input
              type="range"
              min={0}
              max={1}
              step={1 / Math.max(1, maxLayer)}
              value={clipMaxFraction}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                setClipMaxFraction(Math.max(v, clipMinFraction));
              }}
              aria-label="Last visible layer"
              className="flex-1"
            />
          </div>
          <span className="font-mono tabular-nums">
            {clipRangeMin + 1}–{clipRangeMax + 1}/{maxLayer + 1}
          </span>
        </div>
      )}
    </div>
  );
}

function SliceErrorNotice({ err }: { err: SliceApiError | string }) {
  if (typeof err === "string") {
    return (
      <div className="border border-red-200 bg-red-50 p-3 text-sm text-red-800">
        {err}
      </div>
    );
  }
  return (
    <div className="border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      <div className="font-medium">
        Slice failed
        {err.status > 0 ? ` (HTTP ${err.status})` : ""}
        {err.type && err.type !== "server_error" ? ` — ${err.type}` : ""}
      </div>
      <div className="mt-1 break-words">{err.message}</div>
      {err.field && (
        <div className="mt-1 text-xs">
          Field: <span className="font-mono">{err.field}</span>
        </div>
      )}
      {err.detail && err.detail !== err.message && (
        <details className="mt-1 text-xs">
          <summary className="cursor-pointer text-red-700">Details</summary>
          <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap font-mono text-[11px]">
            {err.detail}
          </pre>
        </details>
      )}
    </div>
  );
}

function ViewerPlaceholder({ slicing }: { slicing: boolean }) {
  if (slicing) {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
        <div className="relative h-1 w-48 overflow-hidden rounded-full bg-neutral-200">
          <div className="absolute inset-y-0 w-1/3 animate-[slicing-pulse_1.4s_ease-in-out_infinite] bg-neutral-700" />
        </div>
        <div className="text-xs text-neutral-500">
          Slicing — this can take 10–60 s on large meshes.
        </div>
        <style jsx>{`
          @keyframes slicing-pulse {
            0% { left: -33%; }
            100% { left: 100%; }
          }
        `}</style>
      </div>
    );
  }
  return (
    <div className="absolute inset-0 flex items-center justify-center text-center text-sm text-neutral-500">
      Upload an STL, configure the recipe, then click Slice.
    </div>
  );
}

function StressReportPanel({
  result,
  cells,
}: {
  result: SliceResponse;
  cells: CellPayloadRecord[];
}) {
  const { stats } = result;
  const anyUncalibrated = cells.some((c) => !c.calibrated);
  return (
    <div className="border border-neutral-200 p-4 text-sm">
      <h3 className="text-sm font-medium tracking-tight">Slice report</h3>
      <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Total moves" value={String(stats.total_moves)} />
        <Stat
          label="Est. print time"
          value={formatDuration(stats.estimated_seconds)}
        />
        <Stat
          label="Max wall shear"
          value={`${stats.max_wall_shear_pa.toFixed(1)} Pa`}
        />
        <Stat label="Syringes" value={String(stats.syringe_count)} />
      </div>
      <table className="mt-3 w-full text-xs">
        <thead className="text-neutral-500">
          <tr>
            <th className="text-left font-normal">Syringe</th>
            <th className="text-right font-normal">Max shear</th>
            <th className="text-right font-normal">Threshold</th>
            <th className="text-right font-normal">Bioink</th>
          </tr>
        </thead>
        <tbody>
          {Object.keys(stats.threshold_by_syringe).map((sid) => {
            const shear = stats.max_wall_shear_by_syringe[sid] ?? 0;
            const threshold = stats.threshold_by_syringe[sid] ?? 0;
            const vol = stats.total_bioink_uL_by_syringe[sid] ?? 0;
            const safe = shear <= threshold;
            return (
              <tr key={sid} className="border-t border-neutral-100">
                <td className="py-1">{sid}</td>
                <td className="py-1 text-right font-mono">
                  {shear.toFixed(1)} Pa
                </td>
                <td
                  className={`py-1 text-right font-mono ${
                    safe ? "" : "text-red-700"
                  }`}
                >
                  {threshold.toFixed(1)} Pa
                </td>
                <td className="py-1 text-right font-mono">
                  {vol.toFixed(2)} µL
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {anyUncalibrated && (
        <p className="mt-2 text-xs text-neutral-500">
          Thresholds are uncalibrated literature defaults. Verify against your
          own viability assays.
        </p>
      )}
    </div>
  );
}

function CellViabilityNotice({ err }: { err: SliceCellViabilityError }) {
  return (
    <div className="border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      <div className="font-medium">Refused: cell-viability violation</div>
      <div className="mt-1">
        Segment <span className="font-mono">{err.segmentId}</span> would
        experience <span className="font-mono">{err.computedWallShearPa.toFixed(1)} Pa</span>{" "}
        wall shear; the threshold for{" "}
        <span className="font-mono">{err.bioinkName}</span> /{" "}
        <span className="font-mono">{err.cellType}</span> is{" "}
        <span className="font-mono">{err.thresholdPa.toFixed(1)} Pa</span>.
      </div>
      {err.remediation && (
        <div className="mt-1 italic">{err.remediation}</div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="font-mono text-sm">{value}</div>
    </div>
  );
}

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0 s";
  if (seconds < 60) return `${seconds.toFixed(0)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds - m * 60);
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  const mm = m - h * 60;
  return `${h}h ${mm}m`;
}
