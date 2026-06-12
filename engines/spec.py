"""Reform spec schema — the one declarative input that drives both engines.

See fiscal-simulator-build-spec.md §6. A spec validates here before any engine
runs; AI-extracted specs MUST pass this validation or the run is refused.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}


class Geography(BaseModel):
    state: str = Field(description="Two-letter state code, or 'US' for national")
    metros: list[str] = Field(default_factory=list)

    @field_validator("state")
    @classmethod
    def _check_state(cls, v: str) -> str:
        v = v.upper()
        if v != "US" and v not in US_STATES:
            raise ValueError(f"Unknown state code: {v!r}")
        return v


class TaxTransfer(BaseModel):
    engine: Literal["policyengine-us"] = "policyengine-us"
    baseline_year: int = 2026
    # PolicyEngine parameter path -> new value. Values may be scalars
    # (applied for baseline_year onward) or {"YYYY-01-01.YYYY-12-31": value}.
    reforms: dict[str, Any]

    @field_validator("reforms")
    @classmethod
    def _non_empty(cls, v: dict) -> dict:
        if not v:
            raise ValueError("tax_transfer.reforms must contain at least one parameter change")
        return v


class SpendingItem(BaseModel):
    industry: str = Field(description="BEA summary industry name (fuzzy-matched by the engine)")
    amount_usd: float = Field(description="Annual spending in dollars; negative = withdrawal")


class Spending(BaseModel):
    engine: Literal["lq-io", "rims2"] = "lq-io"
    # budget_delta: the microsim's net fiscal delta becomes a household-spending
    # shock. explicit_program: spend directly in the listed industries.
    source: Literal["budget_delta", "explicit_program"] = "budget_delta"
    explicit_program: list[SpendingItem] = Field(default_factory=list)

    @field_validator("explicit_program")
    @classmethod
    def _program_if_explicit(cls, v, info):
        if info.data.get("source") == "explicit_program" and not v:
            raise ValueError("source='explicit_program' requires at least one spending item")
        return v


class Options(BaseModel):
    behavioral: bool = False  # v1 is static-only; True is rejected downstream
    multiplier_types: list[Literal["I", "II"]] = Field(default=["I", "II"])
    scenarios: list[Literal["central", "low", "high"]] = Field(
        default=["central", "low", "high"]
    )


class ReformSpec(BaseModel):
    """One reform, two engines. At least one engine section must be present."""

    name: str
    geography: Geography
    tax_transfer: Optional[TaxTransfer] = None
    spending: Optional[Spending] = None
    options: Options = Field(default_factory=Options)

    def model_post_init(self, __context: Any) -> None:
        if self.tax_transfer is None and self.spending is None:
            raise ValueError("Spec must include tax_transfer and/or spending")
        if (
            self.spending is not None
            and self.spending.source == "budget_delta"
            and self.tax_transfer is None
        ):
            raise ValueError(
                "spending.source='budget_delta' requires a tax_transfer section "
                "to produce the budget delta"
            )
