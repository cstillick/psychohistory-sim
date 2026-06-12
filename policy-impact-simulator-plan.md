# Policy-Impact Simulator — Project Planning Backbone

*A research-grounded foundation for scoping and building. Hand this to Claude Code as context, then narrow to one engine + one geography + one policy domain for the MVP.*

---

## 0. The one decision that determines everything

"Policy-impact simulator" is not a single thing. It resolves into **four fundamentally different modeling engines**, each answering a different *kind* of question, each with its own data needs, math, and existing tooling. Before any code, you must pin down three axes:

1. **What policy?** (tax/transfer · minimum wage/labor · housing/zoning · public spending/investment · broad fiscal/growth)
2. **What outcome?** (revenue · jobs/employment · GDP/output · inequality/poverty · housing prices · migration · winners-and-losers by group)
3. **What geography?** (state · metro/MSA · city/sub-metro)

The policy + outcome pair selects the **engine**. The geography selects the **data layer** and caps how much resolution is even possible.

### Geography reality check (city vs. state — "whichever yields the best result")

> **Recommendation: build at the state or metro (MSA) level first. Pure city-level (sub-metro) is a data desert outside the largest cities.**

| Level | Data richness | Notes |
|---|---|---|
| **State** | Excellent | BEA state GDP & personal income, state I-O, ACS 1-year, QCEW by county→state. Most policy variation (tax codes, min wage) happens *at* the state level, which is ideal for calibration. |
| **Metro (MSA)** | Good | BEA metro GDP, RIMS II multipliers are county/MSA-based, ACS for larger metros. Best resolution for "city economy" questions in practice. |
| **City (sub-metro)** | Poor–patchy | Below ~65k population, ACS is 5-year pooled only; most economic series don't exist. Microdata bottoms out at PUMA (~100k people), which doesn't respect city boundaries. |

State-level also gives you the strongest **natural experiments** for calibration: 50 jurisdictions changing policies at different times is exactly what synthetic-control and diff-in-diff methods are built to exploit.

---

## 1. The four engines (the intellectual core)

### A. Microsimulation — household-level tax & benefit accounting
**What it is:** Encode tax and benefit *rules* as executable logic, run them over a representative sample of real households (microdata), change a rule, and recompute every household's outcome. "Static" = no behavioral response; "dynamic"/"behavioral" = households change labor supply etc. in response.

**Answers:** Who wins and who loses? Effect on poverty, inequality, government revenue, by income decile / age / geography.

**Stand on this, don't rebuild it:**
- **PolicyEngine-US** — open-source Python package + REST API + web app. Models federal **and all 50 states'** tax-benefit systems (55+ programs). Built on the OpenFisca framework. This is the single highest-leverage starting point if your policy is tax/transfer-shaped. (Used by researchers, nonprofits, and even No. 10 Downing Street's data team in the UK.)
- **Tax-Calculator (`taxcalc`)** from the **Policy Simulation Library (PSL)** — federal income/payroll taxes, ~200 parameterized policy levers, exhaustively unit-tested.
- **OpenFisca** — the general microsimulation framework underneath, if you want to model a *new* rule system from scratch.

**Data:** Census **ACS PUMS** or **CPS ASEC** microdata (via Census API or **IPUMS**); often statistically enhanced/calibrated to administrative totals.

**Core math:** budget constraint per household, **effective marginal tax rate** (Δtax / Δincome), poverty rate, Gini coefficient, distributional tables by decile.

**Best for:** EITC/CTC reforms, income tax changes, UBI/guaranteed income, benefit cliffs, state tax conformity. **Weak for:** macro feedback, prices, jobs created.

---

### B. Input–Output / multiplier analysis — regional ripple effects
**What it is:** A demand shock (a new factory, a tax incentive, infrastructure spending, an industry's decline) ripples through inter-industry supply linkages and household re-spending. Built on a region's inter-industry transaction table.

**Answers:** "If $X is spent / Y jobs appear in industry Z, what's the total regional effect on output, earnings, employment, value-added?"

**Core math:**
- Technical-coefficients matrix **A** (industry inputs per dollar of output)
- **Leontief inverse** `L = (I − A)⁻¹` → total requirements
- **Type I** multipliers = direct + indirect (inter-industry); **Type II** = + induced (household spending). Type II is larger and easier to overstate.

**Tools / data:**
- **BEA RIMS II** — cheap, government-vetted multipliers for output, earnings, employment, value-added, at **county / MSA / county-group** level (not whole-state). Based on national I-O benchmark + regional accounts.
- **IMPLAN** — proprietary, ~540 NAICS sectors, gravity-model trade flows (more accurate inter-regional, less multiplier overstatement), user-friendly. Paid.
- **REMI** — proprietary, dynamic econometric + I-O hybrid; forecasts over time. Expensive, expert-level.
- **Open-source:** `pymrio` (multi-regional I-O in Python), EPA's **USEEIO** model.

**Best for:** economic-impact studies of spending, incentives, infrastructure, plant openings/closings. **Weak for:** price changes, behavioral response, anything where the multiplier assumptions (fixed coefficients, no capacity limits) break.

---

### C. Computable General Equilibrium (CGE) / Overlapping Generations (OLG)
**What it is:** A full economy-wide model where optimizing households and firms interact, markets clear, and **prices adjust**. Captures feedback loops and resource reallocation that I-O and static microsim miss. OLG variants add demographic/lifecycle dynamics for long-run analysis.

**Tools:**
- **OG-Core / OG-USA** (PSL, Python) — large-scale **overlapping-generations dynamic general-equilibrium** model of U.S. fiscal policy; outputs macro aggregates, wages, interest rates, revenue streams; can interface with a microsim (e.g. Tax-Calculator) for household detail. Regional/country variants exist via the OG framework.
- **GTAP** (trade-focused), academic regional-CGE setups.

**Core math:** CES/Cobb-Douglas production functions, household utility maximization, market-clearing conditions, calibration to a **Social Accounting Matrix (SAM)**.

**Best for:** large fiscal reforms, long-run growth/welfare, when prices *and* behavior matter. **Cost:** heaviest to build, calibrate, and validate; steep economics expertise required. Usually overkill for a v1.

---

### D. Agent-Based Modeling (ABM) — bottom-up emergence
**What it is:** Heterogeneous autonomous agents (households, firms, workers) follow behavioral rules and interact in space; macro patterns *emerge* rather than being assumed. Naturally spatial and out-of-equilibrium.

**Tools:**
- **Mesa 3** (Python, 2025; Mesa 4 in alpha) — the standard Python ABM framework: agents, spatial grids, schedulers, browser-based visualization, built-in data collection.
- **Agents.jl** (Julia) — fastest option if performance bites.
- **NetLogo** — fastest to prototype, weaker for production integration.

**Best for:** housing/zoning, gentrification, segregation (Schelling), local labor-market matching, spatial distributional effects, "what emerges from these micro-rules?" **Weak for:** precise revenue/quantitative point estimates; harder to calibrate and validate rigorously.

---

### E. (Cross-cutting) Empirical causal calibration & validation
This is what separates a credible simulator from a toy. Use **real historical policy changes** across states/cities to estimate the elasticities your engine needs, and to validate that the engine reproduces known effects.

- **Difference-in-Differences (DiD)** — compares treated vs. control jurisdictions before/after; the workhorse. Modern staggered-adoption estimators (Callaway–Sant'Anna) matter when policies roll out at different times. Packages: `diff-diff` (13+ estimators), `pyfixest`, `linearmodels`, `statsmodels`.
- **Synthetic Control** — builds a weighted "synthetic" comparison region from a donor pool; the canonical tool for single-jurisdiction policy effects (the classic California Prop 99 tobacco-tax study). Packages: `SyntheticControlMethods`, `mlsynth`, Microsoft `SparseSC`.
- **Synthetic DiD** — merges both; more robust to non-parallel pre-trends. Package: `synthdid`.

**Use it twice:** (1) to *estimate parameters* feeding the simulator, and (2) to *back-test* the simulator against a held-out historical reform.

---

## 2. Decision matrix — question → engine

| If the core question is… | …use this engine | Existing tool to start from |
|---|---|---|
| Who wins/loses from a tax or benefit change? | Microsimulation | **PolicyEngine-US** / Tax-Calculator |
| Revenue / poverty / inequality effect of a transfer | Microsimulation | PolicyEngine-US |
| Jobs & output from spending/incentive/investment | Input–Output | **RIMS II** (free) or IMPLAN |
| Long-run growth/welfare of a big fiscal reform | CGE / OLG | **OG-USA** |
| Housing, zoning, gentrification, spatial sorting | Agent-Based | **Mesa 3** |
| "Did this real policy actually work?" (evaluate) | Causal inference | synthetic control / DiD |
| Minimum-wage employment effect | Causal inference → feeds microsim/ABM | DiD + PolicyEngine |

**Hybrid is normal:** e.g. microsim for household detail + I-O for regional jobs, with elasticities calibrated by DiD. PolicyEngine↔OG-USA already interoperate.

---

## 3. Data layer — sources & APIs

| Source | Has an API | Gives you | Geography |
|---|---|---|---|
| **BEA** (Regional) | Yes | GDP, personal income, RIMS II multipliers | State, MSA, county |
| **Census** | Yes | **ACS** (incl. **PUMS microdata**), County Business Patterns, building permits | Nation→PUMA |
| **BLS** | Yes | **QCEW** (employment/wages by industry), LAUS (local unemployment), CPS | County, state |
| **FRED** (St. Louis Fed) | Yes | Almost every macro time series, harmonized | Varies |
| **IPUMS** | Extract/API | Harmonized ACS/CPS microdata (best for microsim) | PUMA up |
| **IRS SOI** | Bulk files | Income & **migration** flows | County, ZIP |
| **HUD / Zillow (ZHVI/ZORI)** | Yes/bulk | Housing prices, rents, permits | Metro, ZIP |

**Geography gotchas to design around:**
- **PUMA** is the floor for public microdata (~100k people) — it won't align to city lines.
- **MAUP** (Modifiable Areal Unit Problem): results shift when you change the spatial unit. Pick units deliberately and stick to them.
- **Ecological fallacy:** aggregate relationships ≠ individual ones. Keep microdata where you can.

---

## 4. Reference architecture

Design the engine as a **pure function**: `simulate(baseline, reform_params) → outcomes`. Everything else is plumbing around it.

```
┌─────────────────────────────────────────────────────────────┐
│  FRONTEND  (React)                                           │
│  • Reform builder (set policy parameters)                    │
│  • Result views: distributional charts, choropleth maps,     │
│    revenue/jobs cards, uncertainty ranges                    │
│  • Model PolicyEngine's web app as the UX gold standard      │
└───────────────▲─────────────────────────────────────────────┘
                │  JSON
┌───────────────┴─────────────────────────────────────────────┐
│  API LAYER  (FastAPI)  — engine-as-a-service, cached         │
└───────────────▲─────────────────────────────────────────────┘
                │
┌───────────────┴─────────────────────────────────────────────┐
│  SIMULATION ENGINE  (one paradigm, or hybrid)                │
│  baseline + reform_params  →  outcomes   [pure, seeded]      │
└───────────────▲─────────────────────────────────────────────┘
                │
┌───────────────┴─────────────────────────────────────────────┐
│  CALIBRATION LAYER                                           │
│  • elasticities/effect sizes from DiD / synthetic control    │
│  • baseline calibrated to known administrative totals        │
└───────────────▲─────────────────────────────────────────────┘
                │
┌───────────────┴─────────────────────────────────────────────┐
│  DATA / ETL LAYER                                            │
│  API pulls → tidy panel store (DuckDB + Parquet, or Postgres)│
│  versioned, cached, reproducible                             │
└─────────────────────────────────────────────────────────────┘
```

**Stack defaults:** Python 3.12+, `uv` for env/deps, pandas/Polars, DuckDB+Parquet (or Postgres), the relevant engine package (PolicyEngine / taxcalc / Mesa / OG-USA), FastAPI, React + a charting lib (Recharts/Plotly) + a maps lib (deck.gl/Mapbox) for choropleths, pytest, and a data-version strategy (DVC or just content-hashed Parquet).

---

## 5. Equations & methods cheat-sheet

- **Leontief inverse / multipliers:** `X = (I − A)⁻¹ · F` ; total effect of final-demand vector F.
- **Effective marginal tax rate:** `EMTR = 1 − (Δ net income / Δ gross income)`.
- **Gini:** area between Lorenz curve and equality line, ×2.
- **Poverty rate:** share of units below threshold (absolute or relative).
- **DiD (2×2):** `(Ȳ_treat,post − Ȳ_treat,pre) − (Ȳ_ctrl,post − Ȳ_ctrl,pre)`; generalize to two-way fixed effects, then to staggered estimators.
- **Synthetic control:** choose donor weights `w` minimizing pre-treatment outcome gap subject to `wᵢ ≥ 0, Σwᵢ = 1`; effect = treated − synthetic in post period.
- **Shift-share:** decompose regional industry growth into national + industry-mix + local-competitive components.
- **Location quotient:** `LQ = (local industry share) / (national industry share)`; >1 = local specialization.
- **CES production:** `Y = A·[α·Kᵖ + (1−α)·Lᵖ]^(1/p)`.

---

## 6. Recommended build path (phased)

**Guiding principle: do *not* build the engine from scratch first.** Wrap PolicyEngine / RIMS II / Mesa, prove the loop end-to-end, then deepen.

- **Phase 0 — Scope lock.** One policy domain × one geography level × one engine. Write the single concrete question the MVP must answer.
- **Phase 1 — Data pipeline + baseline.** Stand up ETL for 2–3 sources; reproduce a published baseline number to prove your data is right.
- **Phase 2 — Engine integration.** Wrap the chosen existing model; expose `simulate(reform)`; verify against the tool's own published examples.
- **Phase 3 — Calibration & back-test.** Estimate one key elasticity via DiD/synthetic control on a real historical reform; confirm the engine reproduces the known effect within a sane range.
- **Phase 4 — API + UI.** FastAPI wrapper, a reform-builder front end, distributional + map visualizations, **uncertainty ranges shown by default**.
- **Phase 5 — Broaden.** More policies, more geographies, or a second engine for hybrid analysis.

---

## 7. Credibility traps to design against

1. **Static vs. behavioral (Lucas critique):** static microsim ignores that people respond to incentives. Be explicit about which you're doing.
2. **Multiplier overstatement:** Type II induced effects and RIMS II's location-quotient method (no cross-haul correction) tend to *inflate* impacts. Report Type I and Type II separately.
3. **Garbage calibration → confident wrongness:** an uncalibrated engine produces precise, plausible-looking, wrong numbers. Calibration is not optional.
4. **Spatial fallacies:** MAUP + ecological fallacy. Fix your units; keep microdata.
5. **City-level sparsity:** don't promise sub-metro resolution the data can't support.
6. **Synthetic control / DiD assumptions:** parallel pre-trends, no spillover to controls, donor-pool validity, placebo tests. Overfitting the pre-period is a classic failure.
7. **Communicating uncertainty:** ship ranges and scenario bands, never bare point estimates. This is the difference between a credible tool and a misleading one.

---

## 8. Tech-stack summary

| Layer | Default choice | Alternatives |
|---|---|---|
| Language | Python 3.12+ | Julia (for ABM/CGE perf) |
| Env/deps | `uv` | poetry, conda |
| Data store | DuckDB + Parquet | Postgres, SQLite |
| Microsim engine | PolicyEngine-US | Tax-Calculator, OpenFisca |
| I-O engine | RIMS II tables + numpy | IMPLAN/REMI (paid), pymrio |
| CGE/OLG | OG-USA / OG-Core | GTAP |
| ABM | Mesa 3 | Agents.jl, NetLogo |
| Causal/calibration | pyfixest, diff-diff, mlsynth | statsmodels, SparseSC, synthdid |
| API | FastAPI | Flask |
| Frontend | React + Recharts/Plotly + deck.gl | Streamlit (fast MVP) |
| Tests/repro | pytest + seeds + data versioning | DVC |

---

## 9. Open scoping questions (answer before Phase 0)

1. **Primary policy domain?** → selects the engine.
2. **Primary outcome metric(s)?** → revenue / jobs / inequality / prices / migration.
3. **Geography level?** → state vs. metro vs. city (see §0).
4. **Audience & rigor bar?** → personal learning / research-grade / public advocacy tool / commercial product. Drives how much calibration & UX you invest.
5. **Build vs. wrap appetite?** → strongly recommend wrap-first.
6. **Static or behavioral responses** in v1?
7. **One jurisdiction deep, or many jurisdictions comparable?**

---

*Sources grounding this plan: PolicyEngine (US/UK), the Policy Simulation Library (Tax-Calculator, OG-USA/OG-Core), BEA RIMS II and the IMPLAN/REMI comparison literature, the Mesa 3 ABM framework, and the synthetic-control / difference-in-differences policy-evaluation literature. All current as of mid-2026.*
