# Scoped Build Spec — Two-Engine Fiscal Policy Simulator

*Companion to `policy-impact-simulator-plan.md` (the backbone). This is the actionable spec for the chosen configuration. Hand both to Claude Code.*

**Configuration locked:**
- **Engines:** Microsimulation (tax & transfers) **+** Input–Output multipliers (spending/jobs), unified into one pipeline.
- **Geography:** Flexible → **state-level primary, metro/MSA for the spending side** (data-driven choice, explained in §4).
- **Goal:** Personal learning, **architected so it can become a public advocacy tool without an engine rewrite.**

---

## 1. What you're building (the unification)

Not two apps — **one reform, two linked engines, one result page with two panels.**

```
                       ┌────────────────────────────────────────┐
   ONE reform spec ───▶│  ENGINE 1: Microsimulation             │
   (declarative JSON)  │  PolicyEngine-US                       │
                       │  → distributional table (deciles)      │
                       │  → poverty & inequality change         │
                       │  → NET BUDGET Δ  ◀── the linkage        │
                       └───────────────┬────────────────────────┘
                                       │ budget Δ (or an explicit
                                       │ spending program vector)
                                       ▼
                       ┌────────────────────────────────────────┐
                       │  ENGINE 2: Input–Output multipliers    │
                       │  BEA RIMS II (free) [/ IMPLAN later]    │
                       │  → jobs supported/lost                  │
                       │  → output & earnings effect            │
                       │  → by industry, by region              │
                       └────────────────────────────────────────┘
```

**Result page:** left panel = "who is affected & what it costs" (microsim); right panel = "what the money does in the regional economy" (I-O). The number that connects them — the net fiscal cost/saving — is shown explicitly as the bridge.

---

## 2. Engine 1 — Microsimulation (tax & transfers)

| | |
|---|---|
| **Tool** | `policyengine-us` (Python package) and/or PolicyEngine REST API |
| **Why** | Models federal **and all 50 states'** tax-benefit systems out of the box; ~55+ programs; vectorized over thousands of households; actively maintained. |
| **Input** | A reform = a set of parameter changes (rates, brackets, credit amounts, eligibility) |
| **Outputs** | Net income by household; distributional impact by income decile; poverty rate change; Gini change; **aggregate budgetary impact (the linkage value)** |
| **Data** | Enhanced ACS/CPS microdata ships with the package; no separate data build needed for v1 |
| **Fallback** | `Tax-Calculator` (taxcalc) for federal-only, if you want a second independent estimate |

**Static first, behavioral later.** v1 = static (no labor-supply response). Note the caveat in outputs; add behavioral elasticities in a later phase.

---

## 3. Engine 2 — Input–Output multipliers (spending → jobs/output)

| | |
|---|---|
| **Tool** | BEA **RIMS II** multiplier tables + a small numpy/pandas multiplier engine |
| **Why free-first** | RIMS II is government-vetted, costs little, and covers output / earnings / employment / value-added multipliers |
| **Input** | A spending vector by industry (from the budget Δ, or an explicit program e.g. "$200M to highways & residential construction") |
| **Outputs** | Jobs supported, output effect, earnings effect — **Type I** (direct+indirect) and **Type II** (+induced) reported **separately** |
| **Geography** | RIMS II is **county / MSA / county-group** based — aggregate a state's counties for a state view, or run per-MSA |
| **Upgrade path** | IMPLAN (paid, ~540 sectors, gravity-model trade flows, less multiplier overstatement) if it becomes an advocacy tool |

**Honesty rule baked into the engine:** always emit Type I and Type II side by side, never just the bigger number.

---

## 4. Geography strategy ("flexible — whatever the data supports best")

The two engines have different native resolutions, so use each at its best and reconcile at the state line:

- **Microsim:** state + federal is the sweet spot. PolicyEngine handles state tax/benefit code natively.
- **I-O:** RIMS II is MSA/county-native, so do the spending side at **MSA level** and aggregate counties up to the state for a statewide figure.
- **Flagship pattern:** pick **one state**, with its **main metros** as the I-O drill-down. State is a parameter, so adding states later is config, not code.

**Recommended flagship states** — choose one with a *recent, real, well-documented reform* so you get a free validation case (PolicyEngine has already published analyses you can check against):
- **South Carolina** — H.4216 (Act 110) income-tax restructuring.
- **Missouri** — HJR 173/174 income-tax-elimination paths.

Starting with one of these means Phase 4 validation is "reproduce a known published result," not "invent ground truth." Default to one of these unless you have a state you care about more — it's a one-line config swap.

---

## 5. The linkage — and its honest caveats

Connecting a microsim distributional result to I-O job effects is powerful but has a methodological seam: the two models rest on different assumptions and you **cannot naively add their dollar figures**. Handle it like this:

1. **The bridge is the net budget Δ**, not the household-income changes. Take the aggregate fiscal cost/saving from the microsim and treat it as the fiscal injection/withdrawal the I-O engine analyzes.
2. **Present, don't merge.** Two panels, one shared bridge number. Don't compute a single blended "total impact" dollar figure — that's where credibility dies.
3. **Show uncertainty by default** — ranges/scenario bands on both sides, never bare point estimates.
4. **Label assumptions** on screen: static microsim, fixed-coefficient I-O, multiplier type. For a learning tool this transparency is a feature; for an advocacy tool it's what makes it defensible.

---

## 6. Reform spec (one declarative input drives both engines)

```jsonc
{
  "name": "SC EITC expansion + transit investment",
  "geography": { "state": "SC", "metros": ["Charleston", "Columbia"] },
  "tax_transfer": {
    "engine": "policyengine-us",
    "baseline_year": 2026,
    "reforms": {
      "gov.states.sc.tax.income.eitc.match": 0.20,   // example param path
      "gov.irs.credits.ctc.amount": 2200
    }
  },
  "spending": {
    "engine": "rims2",
    // either derive from the microsim net budget delta…
    "source": "budget_delta",
    // …or specify an explicit program:
    "explicit_program": [
      { "industry": "Transit and ground passenger transportation", "amount_usd": 200000000 }
    ]
  },
  "options": { "behavioral": false, "multiplier_types": ["I", "II"], "scenarios": ["central", "low", "high"] }
}
```

One spec → microsim runs → budget Δ extracted → I-O runs → both panels render. (Param paths above are illustrative; pull exact ones from PolicyEngine's parameter tree.)

---

## 7. Architecture: learning now, advocacy-ready later

The only thing that makes the advocacy version a *front-end swap* instead of a *rewrite* is a clean boundary. Enforce it from day one.

```
repo/
├── data/                 # cached RIMS II tables, fetch scripts (versioned)
├── engines/
│   ├── microsim.py       # wrap PolicyEngine; pure: reform -> result
│   ├── io_model.py       # RIMS II Leontief multiplier engine
│   └── pipeline.py       # reform -> microsim -> budgetΔ -> io -> combined result
├── calibration/
│   └── validate.py       # back-test vs a real reform (synthetic control / published #s)
├── api/
│   └── app.py            # FastAPI: POST /simulate {reform spec} -> {results}
├── ui/                   # Phase 5 — React (or Streamlit MVP)
├── notebooks/            # learning/exploration lives here in early phases
└── tests/
```

**Rule:** the engines never know whether they're called from a notebook, a CLI, or a web request. Learning happens in `notebooks/` calling `pipeline.py` directly; the public tool is just `ui/` calling `api/` calling the same `pipeline.py`.

**Stack:** Python 3.12, `uv`, pandas/Polars, DuckDB+Parquet for cached data, FastAPI, pytest. UI later: React + Recharts (charts) + deck.gl/Mapbox (choropleth maps), or Streamlit for a fast first public demo.

---

## 8. Phased build plan (with acceptance checks)

| Phase | Deliverable | Done when… |
|---|---|---|
| **0. Scope lock** | Pick flagship state; pick one real reform to model | Reform written as a spec (§6) |
| **1. Microsim** | `engines/microsim.py` wrapping PolicyEngine | Reproduces PolicyEngine's own published distributional + budget numbers for that reform |
| **2. I-O** | `engines/io_model.py` + RIMS II ingestion | Hand-checks a known multiplier; emits Type I & II separately |
| **3. Pipeline** | `pipeline.py` linking budget Δ → I-O | One spec produces both panels end to end |
| **4. Validation** | `calibration/validate.py` | Back-test reproduces a real reform's known effect within a sane band (synthetic control or published figures) |
| **5. Surface** | FastAPI endpoint + Streamlit/React UI with uncertainty ranges | A non-coder can run a reform and read both panels |

**Principle: wrap, don't rebuild.** Phases 1–2 are integration, not modeling-from-scratch. That's the whole reason this is buildable solo.

---

## 9. First moves for Claude Code

1. Scaffold the repo skeleton in §7; init with `uv`.
2. `uv add policyengine-us fastapi pandas duckdb pytest`.
3. Implement `engines/microsim.py` → run the chosen state reform → print the distributional table and the aggregate budget Δ. **Validate against PolicyEngine's published result before moving on.**
4. Download the relevant RIMS II tables; implement the Leontief multiplier engine; unit-test one multiplier by hand.
5. Wire `pipeline.py`; feed budget Δ into the I-O engine; render both panels in a notebook.
6. Only then add the FastAPI layer and a Streamlit front end.

---

*Engines and data referenced: PolicyEngine-US, BEA RIMS II (with IMPLAN as the paid upgrade path), and synthetic-control / difference-in-differences for validation. See the backbone doc for the full landscape, equations, and pitfalls.*
