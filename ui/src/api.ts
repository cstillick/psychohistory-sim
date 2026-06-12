import type { InterpretResponse, ReformSpec, SimulationResult } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* keep default detail */
    }
    throw new Error(detail);
  }
  return res.json();
}

export function simulate(spec: ReformSpec): Promise<SimulationResult> {
  return post<SimulationResult>("/simulate", spec);
}

export function interpret(text: string, state?: string | null): Promise<InterpretResponse> {
  return post<InterpretResponse>("/interpret", { text, state: state ?? null });
}

export interface MSAEffect {
  area: string;
  title: string;
  employment_share: number;
  shock_usd: number;
  jobs_type1: number;
  jobs_type2: number;
  output_type2_usd: number;
  earnings_type2_usd: number;
}

export function msaBreakdown(req: {
  state: string;
  shock_kind: string;
  shock_total_usd: number;
  spending_vector: Record<string, number>;
}): Promise<MSAEffect[]> {
  return post<MSAEffect[]>("/msa_breakdown", req);
}

export async function health(): Promise<{ ok: boolean; ai_ingestion: boolean }> {
  const res = await fetch(`${BASE}/health`);
  if (!res.ok) throw new Error("API unreachable");
  return res.json();
}
