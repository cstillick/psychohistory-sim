# Psychohistory — Policy Impact Terminal

**Psychohistory** is a fiscal-policy simulator. Describe a policy in plain
English and instantly see its impact two ways at once:

- **Who it affects** — household winners/losers, poverty, inequality, and net
  budget cost (microsimulation via [PolicyEngine-US](https://policyengine.org)).
- **What it does to the economy** — jobs, output, and earnings by state
  (input–output multipliers, RIMS II-style, built from free BEA + BLS data).

The two halves are linked by one number — the **net budget delta** — shown
explicitly as the bridge. The two panels are never blended into a single
"total impact" figure: they rest on different models and assumptions.

Works for **all 50 states + DC**: PolicyEngine models every state's
tax-benefit code natively, and the I-O engine builds per-state multipliers
from public APIs on demand (cached locally).

## Why "Psychohistory"?

The name is a nod to Isaac Asimov's **Foundation** series. In those novels,
mathematician **Hari Seldon** invents *psychohistory* — "that branch of
mathematics which deals with the reactions of human conglomerates to fixed
social and economic stimuli." It uses the statistical laws of mass action to
predict, in probabilistic terms, how vast populations respond to economic and
social forces — never individuals, only the aggregate.

That is exactly the spirit of this tool: it won't tell you what *you* will do,
but by running real microsimulation over census microdata and regional
input–output models, it estimates how millions of households and a whole
state's economy shift in response to a change in policy. Same ambition as
Seldon's — applied to actual tax-and-transfer code instead of a galactic
empire, and with its assumptions and uncertainty bands shown honestly rather
than hidden in a Vault.

## Quick start

```bash
uv sync                                  # Python 3.12 env + deps

# Terminal web app — one command (starts/repairs both servers):
./run.sh                                 # -> http://localhost:5173

# ...or the two processes by hand:
uv run uvicorn api.app:app --port 8000   # backend
cd ui && npm install && npm run dev      # frontend -> http://localhost:5173

# Headless / CLI:
uv run python cli.py --io-only-demo SC   # fast: $200M transit demo, I-O only
uv run python cli.py examples/ctc_3000.json   # full two-engine run (slow first time)
uv run python cli.py --interpret "raise the CTC to \$3,000" --state OK  # AI ingestion

# Tests & validation:
uv run pytest                            # fast tests
uv run pytest -m slow                    # full microsim acceptance tests
uv run python -m calibration.validate    # anchor both engines to published numbers
```

In the app: type a policy in plain English (needs `ANTHROPIC_API_KEY`), paste a
`{...}` reform-spec JSON, or hit an example button. Click any state on the map
(or use the dropdown) to re-focus the analysis there; toggle map layers between
distributional and jobs views; edit any mapped value in the Interpretation
panel to re-run. Press `/` to focus the command bar.

The first microsim run downloads PolicyEngine's enhanced CPS microdata
(~minutes). The first I-O run downloads BEA I-O tables and BLS QCEW
employment (no API keys required) and caches them under `data/cache/`.

## Reform spec

One declarative JSON drives both engines (see `engines/spec.py`):

```jsonc
{
  "name": "CTC to $3,000",
  "geography": { "state": "SC" },
  "tax_transfer": {
    "baseline_year": 2026,
    "reforms": { "gov.irs.credits.ctc.amount.base[0].amount": 3000 }
  },
  "spending": { "source": "budget_delta" }   // or an explicit_program list
}
```

## AI policy ingestion (optional)

Paste legislation or plain English; Claude maps it to a reform spec and runs
it. Requires `ANTHROPIC_API_KEY` in the environment. **Everything else works
without it** — manually-written specs run fine.

## Architecture

```
engines/   microsim.py (PolicyEngine wrapper) · io_model.py (LQ-regionalized
           Leontief) · pipeline.py (reform -> microsim -> budget Δ -> I-O)
data/      fetch.py — BEA/BLS fetchers + Parquet cache
calibration/ validate.py — acceptance checks vs published numbers
api/       FastAPI POST /simulate (Phase 3)
ui/        React terminal UI (Phases 3-5)
```

Engines are pure functions and never know whether they're called from a
notebook, the CLI, or a web request.

## Methodology honesty rails (baked in, not optional)

- **Static microsim** — no behavioral response; labeled on every result.
- **Type I and Type II** multipliers always reported separately.
- **Low/central/high bands** on the I-O side — heuristic sensitivity bands
  (MPC and leakage assumptions), not confidence intervals.
- **LQ overstatement warning** ships with every I-O result: location-quotient
  regionalization ignores cross-hauling and tends to overstate multipliers.
- The AI extractor **never fabricates a run** — anything it can't map is
  surfaced as a warning, not guessed.
- PolicyEngine's microdata is calibrated to **national** totals: state-level
  aggregates carry extra noise (small states especially), and state tax totals
  can run ~1.5x administrative collections. Treat state numbers as indicative.
