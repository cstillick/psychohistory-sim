import type { Extraction, Provision, ReformSpec } from "./types";

/* Editable mapping model for the Interpretation panel: the bridge between
   AI-extracted provisions and the runnable spec's levers. */

export interface EditableMapping {
  kind: "parameter" | "spending";
  key: string;             // parameter path, or industry name
  value: number;           // parameter value, or annual USD
  provision?: Provision;   // matched extraction provision (confidence etc.)
}

export function mappingsFromSpec(spec: ReformSpec, extraction: Extraction | null): EditableMapping[] {
  const out: EditableMapping[] = [];
  const provs = extraction?.provisions ?? [];
  for (const [path, value] of Object.entries(spec.tax_transfer?.reforms ?? {})) {
    out.push({
      kind: "parameter",
      key: path,
      value: Number(value),
      provision: provs.find((p) => p.parameter_path === path),
    });
  }
  for (const item of spec.spending?.explicit_program ?? []) {
    out.push({
      kind: "spending",
      key: item.industry,
      value: item.amount_usd,
      provision: provs.find((p) => p.industry === item.industry),
    });
  }
  return out;
}

export function specWithMappings(spec: ReformSpec, mappings: EditableMapping[]): ReformSpec {
  const next: ReformSpec = JSON.parse(JSON.stringify(spec));
  const reforms: Record<string, number> = {};
  const program: { industry: string; amount_usd: number }[] = [];
  for (const m of mappings) {
    if (m.kind === "parameter") reforms[m.key] = m.value;
    else program.push({ industry: m.key, amount_usd: m.value });
  }
  if (Object.keys(reforms).length > 0 && next.tax_transfer) next.tax_transfer.reforms = reforms;
  if (program.length > 0 && next.spending) next.spending.explicit_program = program;
  return next;
}
