/**
 * Tiny typed wrapper around the BioSlice5X Python serverless API.
 * Centralized so the UI can swap endpoints / handle CORS / etc. in one place.
 */

import type {
  ApiError,
  BioinkRecord,
  CellPayloadRecord,
  ProfileRecord,
  Recipe,
  SliceResponse,
} from "@/lib/types";

const API_BASE = "/api";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "GET" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return (await res.json()) as T;
}

export async function fetchBioinks(): Promise<BioinkRecord[]> {
  const data = await getJSON<{ bioinks: BioinkRecord[] }>("/bioinks");
  return data.bioinks;
}

export async function fetchCells(): Promise<CellPayloadRecord[]> {
  const data = await getJSON<{ cells: CellPayloadRecord[] }>("/cells");
  return data.cells;
}

export async function fetchProfiles(): Promise<ProfileRecord[]> {
  const data = await getJSON<{ profiles: ProfileRecord[] }>("/profiles");
  return data.profiles;
}

export interface SliceArgs {
  mesh: { format: "stl" | "obj"; bytes: ArrayBuffer };
  profile: string;
  recipe: Recipe;
}

export async function slice(args: SliceArgs): Promise<SliceResponse> {
  const dataB64 = arrayBufferToBase64(args.mesh.bytes);
  const res = await fetch(`${API_BASE}/slice`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mesh: { format: args.mesh.format, data_base64: dataB64 },
      profile: args.profile,
      recipe: args.recipe,
    }),
  });
  const text = await res.text();
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    throw new Error(`API returned non-JSON (${res.status}): ${text.slice(0, 500)}`);
  }
  if (!res.ok) {
    const err = body as ApiError;
    if ("error" in err && "kind" in err.error && err.error.kind === "cell_viability") {
      throw new SliceCellViabilityError(err.error);
    }
    const message =
      (err && typeof err === "object" && "error" in err && err.error && "message" in err.error
        ? err.error.message
        : `${res.status} ${res.statusText}`);
    throw new Error(String(message));
  }
  return body as SliceResponse;
}

export class SliceCellViabilityError extends Error {
  segmentId: string;
  computedWallShearPa: number;
  thresholdPa: number;
  bioinkName: string;
  cellType: string;
  remediation: string;

  constructor(payload: import("@/lib/types").CellViabilityError) {
    super(
      `cell viability violation at segment ${payload.segment_id}: ` +
        `${payload.computed_wall_shear_pa.toFixed(1)} Pa > ${payload.threshold_pa.toFixed(1)} Pa`
    );
    this.name = "SliceCellViabilityError";
    this.segmentId = payload.segment_id;
    this.computedWallShearPa = payload.computed_wall_shear_pa;
    this.thresholdPa = payload.threshold_pa;
    this.bioinkName = payload.bioink_name;
    this.cellType = payload.cell_type;
    this.remediation = payload.remediation;
  }
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  // Chunk to avoid maximum-call-stack-size on huge meshes.
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(
      null,
      Array.from(bytes.subarray(i, i + CHUNK))
    );
  }
  return btoa(binary);
}
