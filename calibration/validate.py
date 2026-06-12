"""Phase 1 acceptance checks: anchor both engines to known published numbers.

Microsim anchors (administrative/published program totals):
- Federal EITC outlays   ~$64bn (IRS SOI 2023; CBO baseline ~$60-75bn)
- Total CTC              ~$120bn (JCT current-law estimates)
- SNAP benefits          ~$94bn (USDA FY2024)

I-O anchors (published RIMS II-style ranges, state level):
- Construction final-demand output multipliers: Type I ~1.4-1.8, Type II ~1.7-2.3
- Jobs per $1M construction spending: roughly 5-15 (2023 dollars)

Run: uv run python -m calibration.validate
"""
from __future__ import annotations

import sys

CHECKS = []


def check(name: str, value: float, lo: float, hi: float, fmt: str = ",.1f") -> bool:
    ok = lo <= value <= hi
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}: {value:{fmt}} (expected {lo:{fmt}} - {hi:{fmt}})")
    CHECKS.append(ok)
    return ok


def validate_microsim() -> None:
    from engines.microsim import _baseline_sim

    print("\nMicrosim baseline vs administrative totals (2026, $bn):")
    sim = _baseline_sim()
    check("EITC aggregate", sim.calculate("eitc", period=2026).sum() / 1e9, 45, 95)
    check("CTC aggregate", sim.calculate("ctc", period=2026).sum() / 1e9, 80, 160)
    check("SNAP aggregate", sim.calculate("snap", period=2026).sum() / 1e9, 60, 140)
    # SC individual income tax: RFA collections are ~$6.5bn/yr. PolicyEngine's
    # microdata is calibrated to NATIONAL totals, so state tax aggregates run
    # high (observed ~1.5x). This check catches wrapper bugs (wrong variable,
    # units), not that calibration gap — hence the wide band.
    sc_tax = sim.calculate("sc_income_tax", period=2026)
    check("SC income tax aggregate (order of magnitude)", sc_tax.sum() / 1e9, 3.5, 13.0)


def validate_io(state: str = "SC") -> None:
    from engines.io_model import RegionalIOModel

    print(f"\nI-O multipliers vs published RIMS II ranges ({state}, construction):")
    model = RegionalIOModel(state)
    res = model.run_shock(
        spending_by_sector={"23": 100_000_000.0},
        shock_kind="industry_spending",
        shock_total_usd=100_000_000.0,
        scenarios=["central"],
        multiplier_types=["I", "II"],
    )
    check("Type I output multiplier", res.effects["I"]["central"].output_multiplier, 1.2, 1.9, ".2f")
    check("Type II output multiplier", res.effects["II"]["central"].output_multiplier, 1.5, 2.4, ".2f")
    check("Jobs per $1M (Type II)", res.effects["II"]["central"].jobs / 100, 4, 20, ".1f")


def main() -> None:
    validate_io()
    validate_microsim()
    failed = CHECKS.count(False)
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
