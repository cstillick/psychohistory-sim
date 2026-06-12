"""Run a reform spec from the command line.

Usage:
    uv run python cli.py path/to/spec.json
    uv run python cli.py --io-only-demo SC   # quick I-O sanity run, no microsim
"""
from __future__ import annotations

import argparse
import json
import sys

from engines.pipeline import SimulationResult, run_pipeline
from engines.spec import ReformSpec


def fmt_usd(x: float) -> str:
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1e9:
        return f"{sign}${x / 1e9:,.2f}bn"
    if x >= 1e6:
        return f"{sign}${x / 1e6:,.1f}mn"
    return f"{sign}${x:,.0f}"


def print_result(res: SimulationResult) -> None:
    spec = res.spec
    print(f"\n=== {spec.name} ===  [{spec.geography.state}]")

    if res.microsim:
        m = res.microsim
        print("\n-- WHO IT AFFECTS (microsimulation) --")
        print(f"  Budget delta (gov balance): {fmt_usd(m.budget_delta_usd)}"
              f"  ({'cost' if m.budget_delta_usd < 0 else 'saving'})")
        print(f"  In-state household net gain: {fmt_usd(m.in_state_household_gain_usd)}")
        print(f"  Households better off: {m.households_better_off:,.0f}   "
              f"worse off: {m.households_worse_off:,.0f}")
        print(f"  Poverty rate: {m.poverty_rate_baseline:.2%} -> {m.poverty_rate_reform:.2%}")
        print(f"  Gini:         {m.gini_baseline:.4f} -> {m.gini_reform:.4f}")
        print("  Decile  avg %chg   avg $chg")
        for r in m.decile_table:
            print(f"    {r.decile:>4}  {r.avg_pct_change:>+7.2f}%  {r.avg_change_usd:>+9,.0f}")

    if res.bridge.io_shock_usd is not None:
        print(f"\n-- BRIDGE: {fmt_usd(res.bridge.io_shock_usd)} "
              f"({res.bridge.io_shock_source}) feeds the I-O engine --")

    if res.io:
        print("\n-- WHAT IT DOES TO THE ECONOMY (input-output) --")
        for mtype, scens in res.io.effects.items():
            label = "Type I (direct+indirect)" if mtype == "I" else "Type II (+induced)"
            print(f"  {label}:")
            for scen in ("low", "central", "high"):
                if scen in scens:
                    e = scens[scen]
                    print(f"    {scen:>8}: jobs {e.jobs:>+9,.0f}   output {fmt_usd(e.output_usd):>11}"
                          f"   earnings {fmt_usd(e.earnings_usd):>11}"
                          f"   (x{e.output_multiplier:.2f})")

    if res.warnings:
        print("\n  WARNINGS:")
        for w in res.warnings:
            print(f"   ! {w}")
    print("\n  ASSUMPTIONS:")
    for a in res.assumptions:
        print(f"   * {a}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", nargs="?", help="Path to a reform spec JSON file")
    ap.add_argument("--io-only-demo", metavar="STATE", help="Run a $200mn transit demo in STATE")
    ap.add_argument("--interpret", metavar="TEXT", help="Natural language / pasted policy text -> AI extraction -> auto-run")
    ap.add_argument("--interpret-file", metavar="PATH", help="PDF/DOCX/TXT bill -> AI extraction -> auto-run")
    ap.add_argument("--state", metavar="ST", help="State override for --interpret/--interpret-file")
    args = ap.parse_args()

    if args.interpret or args.interpret_file:
        from ingestion.extract import ExtractionFailed, IngestionUnavailable, interpret_and_run, read_document

        text = args.interpret or read_document(args.interpret_file)
        try:
            extraction, res = interpret_and_run(text, state_override=args.state)
        except IngestionUnavailable as e:
            print(f"AI ingestion unavailable: {e}", file=sys.stderr)
            sys.exit(2)
        except ExtractionFailed as e:
            print(f"\nNOT RUN: {e}\n", file=sys.stderr)
            if e.extraction:
                print("Extracted provisions:", file=sys.stderr)
                for p in e.extraction.provisions:
                    print(f"  [{p.mapping_type}/{p.confidence}] {p.description}", file=sys.stderr)
            sys.exit(1)
        print("\n-- INTERPRETATION --")
        for p in extraction.provisions:
            target = p.parameter_path or (f"{p.industry} ${p.amount_usd:,.0f}/yr" if p.industry else "(not modeled)")
            flag = "  ⚠ LOW CONFIDENCE" if p.confidence == "low" else ""
            print(f"  [{p.mapping_type}/{p.confidence}] {p.description}\n      -> {target}{flag}")
        print_result(res)
        return

    if args.io_only_demo:
        spec = ReformSpec.model_validate(
            {
                "name": f"$200mn transit investment demo ({args.io_only_demo})",
                "geography": {"state": args.io_only_demo},
                "spending": {
                    "source": "explicit_program",
                    "explicit_program": [
                        {"industry": "Transit and ground passenger transportation",
                         "amount_usd": 200_000_000}
                    ],
                },
            }
        )
    elif args.spec:
        with open(args.spec) as f:
            spec = ReformSpec.model_validate(json.load(f))
    else:
        print("Provide a spec file or --io-only-demo STATE", file=sys.stderr)
        sys.exit(2)

    print_result(run_pipeline(spec))


if __name__ == "__main__":
    main()
