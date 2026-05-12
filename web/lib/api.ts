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

export class SliceApiError extends Error {
  /** HTTP status; 0 means the request failed before reaching the server. */
  status: number;
  /** Backend `error.type` token, e.g. "validation_error", "internal_error". */
  type: string;
  /** Optional dotted field path for validation errors (e.g. `slicing.layer_height_mm`). */
  field: string | null;
  /** Long-form detail / pydantic traceback summary when the backend provides one. */
  detail: string | null;
  constructor(args: {
    status: number;
    type: string;
    message: string;
    field?: string | null;
    detail?: string | null;
  }) {
    super(args.message);
    this.name = "SliceApiError";
    this.status = args.status;
    this.type = args.type;
    this.field = args.field ?? null;
    this.detail = args.detail ?? null;
  }
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "GET" });
  if (!res.ok) {
    const text = await res.text();
    throw new SliceApiError({
      status: res.status,
      type: "http_error",
      message: `${res.status} ${res.statusText}`,
      detail: text || null,
    });
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
    throw new SliceApiError({
      status: res.status,
      type: "non_json_response",
      message: `API returned non-JSON (${res.status})`,
      detail: text.slice(0, 500),
    });
  }
  if (!res.ok) {
    const err = body as ApiError;
    if (
      err &&
      typeof err === "object" &&
      "error" in err &&
      err.error &&
      "kind" in err.error &&
      err.error.kind === "cell_viability"
    ) {
      throw new SliceCellViabilityError(err.error);
    }
    if (
      err &&
      typeof err === "object" &&
      "error" in err &&
      err.error &&
      typeof err.error === "object" &&
      "message" in err.error
    ) {
      const payload = err.error as {
        message: string;
        type?: string;
        detail?: string;
        field?: string;
      };
      throw new SliceApiError({
        status: res.status,
        type: payload.type ?? "server_error",
        message: payload.message,
        field: payload.field ?? null,
        detail: payload.detail ?? null,
      });
    }
    throw new SliceApiError({
      status: res.status,
      type: "server_error",
      message: `${res.status} ${res.statusText}`,
    });
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
