// TS mirrors of the API result models (engines/pipeline.py, engines/microsim.py,
// engines/io_model.py, ingestion/extract.py).

export interface DecileRow {
  decile: number;
  avg_pct_change: number;
  total_change_usd: number;
  avg_change_usd: number;
}

export interface StateImpact {
  total_change_usd: number;
  pct_change: number;
  avg_change_per_household_usd: number;
}

export interface MicrosimResult {
  baseline_year: number;
  state: string;
  budget_delta_usd: number;
  in_state_household_gain_usd: number;
  decile_table: DecileRow[];
  households_better_off: number;
  households_worse_off: number;
  households_unchanged: number;
  poverty_rate_baseline: number;
  poverty_rate_reform: number;
  gini_baseline: number;
  gini_reform: number;
  state_breakdown: Record<string, StateImpact>;
  assumptions: string[];
}

export interface TypeScenarioEffect {
  output_usd: number;
  earnings_usd: number;
  jobs: number;
  output_multiplier: number;
}

export interface IndustryEffect {
  sector: string;
  sector_name: string;
  output_usd: number;
  earnings_usd: number;
  jobs: number;
}

export interface IOResult {
  state: string;
  io_year: string;
  shock_kind: "industry_spending" | "household_income";
  shock_total_usd: number;
  spending_vector: Record<string, number>;
  effects: Record<string, Record<string, TypeScenarioEffect>>;
  by_industry: Record<string, IndustryEffect[]>;
  assumptions: string[];
}

export interface StateJobs {
  shock_usd: number;
  jobs_type1: number;
  jobs_type2: number;
  jobs_type2_low: number;
  jobs_type2_high: number;
  output_type2_usd: number;
  earnings_type2_usd: number;
}

export interface Bridge {
  budget_delta_usd: number | null;
  io_shock_usd: number | null;
  io_shock_source: string | null;
  note: string;
}

export interface SpendingItem {
  industry: string;
  amount_usd: number;
}

export interface ReformSpec {
  name: string;
  geography: { state: string; metros?: string[] };
  tax_transfer?: {
    engine?: string;
    baseline_year: number;
    reforms: Record<string, number>;
  } | null;
  spending?: {
    engine?: string;
    source: "budget_delta" | "explicit_program";
    explicit_program?: SpendingItem[];
  } | null;
  options?: {
    behavioral?: boolean;
    multiplier_types?: string[];
    scenarios?: string[];
  };
}

export interface SimulationResult {
  spec: ReformSpec;
  microsim: MicrosimResult | null;
  io: IOResult | null;
  io_by_state: Record<string, StateJobs> | null;
  bridge: Bridge;
  assumptions: string[];
  warnings: string[];
}

export interface Provision {
  description: string;
  mapping_type: "policyengine_parameter" | "industry_spending" | "unmapped";
  confidence: "high" | "medium" | "low";
  rationale: string;
  parameter_path: string | null;
  value: number | null;
  industry: string | null;
  amount_usd: number | null;
}

export interface Extraction {
  name: string;
  state: string | null;
  provisions: Provision[];
}

export interface InterpretResponse {
  extraction: Extraction;
  spec: ReformSpec | null;
  result: SimulationResult | null;
  warnings: string[];
  ran: boolean;
  message: string | null;
}
