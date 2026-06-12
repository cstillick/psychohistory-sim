"""AI policy ingestion: legislation/plain English -> validated reform spec.

Flow: text or document -> Claude (Sonnet, strict JSON structured output) ->
provisions with per-mapping confidence -> validate against the reform-spec
schema and the PolicyEngine parameter tree -> runnable spec + warnings.

Honesty rails:
- NEVER fabricates a run. If nothing extractable is runnable, build_spec
  returns None and the caller shows what WAS extracted instead.
- Invalid PolicyEngine parameter paths are demoted to unmapped warnings,
  not silently guessed.
- Degrades gracefully without ANTHROPIC_API_KEY (raises IngestionUnavailable
  with a readable message; the rest of the app keeps working).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from data.fetch import BEA_SECTOR_NAMES
from engines.spec import US_STATES, ReformSpec

EXTRACTION_MODEL = "claude-sonnet-4-6"


class IngestionUnavailable(RuntimeError):
    pass


class ExtractionFailed(RuntimeError):
    """Extraction produced nothing runnable. Carries what WAS found."""

    def __init__(self, message: str, extraction: Optional["Extraction"] = None):
        super().__init__(message)
        self.extraction = extraction


class Provision(BaseModel):
    description: str
    mapping_type: Literal["policyengine_parameter", "industry_spending", "unmapped"]
    confidence: Literal["high", "medium", "low"]
    rationale: str
    # policyengine_parameter fields
    parameter_path: Optional[str] = None
    value: Optional[float] = None
    # industry_spending fields
    industry: Optional[str] = None
    amount_usd: Optional[float] = None


class Extraction(BaseModel):
    name: str
    state: Optional[str] = None
    provisions: list[Provision] = Field(default_factory=list)
    # Set by extract_provisions when the input was cut at the length limit —
    # provisions past the cutoff were never seen by the model.
    truncated: bool = False


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Short name for the policy package"},
        "state": {
            "type": ["string", "null"],
            "description": "Two-letter US state code if the policy is state-specific, else null",
        },
        "provisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "mapping_type": {
                        "type": "string",
                        "enum": ["policyengine_parameter", "industry_spending", "unmapped"],
                    },
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "rationale": {"type": "string"},
                    "parameter_path": {"type": ["string", "null"]},
                    "value": {"type": ["number", "null"]},
                    "industry": {"type": ["string", "null"]},
                    "amount_usd": {"type": ["number", "null"]},
                },
                "required": [
                    "description", "mapping_type", "confidence", "rationale",
                    "parameter_path", "value", "industry", "amount_usd",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["name", "state", "provisions"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = f"""You translate fiscal policy text into machine-readable economic levers
for a two-engine simulator (PolicyEngine-US microsimulation + regional input-output model).

For each distinct provision in the input, emit one entry:

1. mapping_type "policyengine_parameter" — tax/transfer rule changes. Set parameter_path to a
   PolicyEngine-US parameter tree path (e.g. "gov.irs.credits.ctc.amount.base[0].amount",
   "gov.irs.credits.eitc.max[0].amount", "gov.usda.snap.income.deductions.standard.amount") and
   value to the new numeric value. Rates are decimals (20% match -> 0.20). Use confidence "high"
   only when you are sure the exact path exists in policyengine-us; "medium" if the lever clearly
   exists but the path may differ; "low" if guessing.

2. mapping_type "industry_spending" — direct spending programs. Set industry to the closest of
   these BEA sectors: {", ".join(BEA_SECTOR_NAMES.values())}.
   Set amount_usd to ANNUAL dollars (negative for cuts). Multi-year totals: divide by the period.

3. mapping_type "unmapped" — real provisions this simulator cannot model (regulations, eligibility
   rules without a parameter, non-fiscal mandates). Explain why in rationale.

NEVER invent numbers that are not in (or directly computable from) the text. If a provision has
no defensible numeric value, mark it unmapped. Output JSON only."""


def read_document(path: str | Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix == ".docx":
        import docx

        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    return path.read_text(errors="replace")


def extract_provisions(text: str) -> Extraction:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise IngestionUnavailable(
            "ANTHROPIC_API_KEY is not set. AI policy ingestion is disabled; "
            "you can still run manually-written reform specs."
        )
    import anthropic

    client = anthropic.Anthropic()
    MAX_CHARS = 150_000
    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text[:MAX_CHARS]}],
        output_config={"format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
    )
    raw = next((b.text for b in response.content if b.type == "text"), None)
    if raw is None:
        raise ExtractionFailed(
            f"Model returned no extraction (stop_reason={response.stop_reason})."
        )
    try:
        extraction = Extraction.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as e:
        raise ExtractionFailed(f"Model returned unparseable extraction: {e}") from e
    extraction.truncated = len(text) > MAX_CHARS
    return extraction


def build_spec(
    extraction: Extraction, state_override: Optional[str] = None, baseline_year: int = 2026
) -> tuple[Optional[ReformSpec], list[str]]:
    """Turn an extraction into a runnable, schema-valid reform spec.

    Returns (spec_or_None, warnings). None means nothing runnable was found —
    the caller must NOT run anything and should surface the warnings.
    """
    from engines.io_model import match_industry
    from engines.microsim import validate_parameter_paths

    warnings: list[str] = []
    reforms: dict[str, float] = {}
    program: list[dict] = []
    if extraction.truncated:
        warnings.append(
            "The input exceeded the extraction length limit and was truncated — "
            "provisions near the end of the document may be missing."
        )

    param_provisions = [
        p for p in extraction.provisions
        if p.mapping_type == "policyengine_parameter" and p.parameter_path and p.value is not None
    ]
    validity = validate_parameter_paths([p.parameter_path for p in param_provisions])

    for p in extraction.provisions:
        if p.mapping_type == "policyengine_parameter":
            if not p.parameter_path or p.value is None:
                warnings.append(f"Provision lacks a parameter/value, skipped: {p.description}")
                continue
            if not validity.get(p.parameter_path, False):
                warnings.append(
                    f"Unknown PolicyEngine parameter {p.parameter_path!r} "
                    f"({p.description}) — needs manual mapping, not run."
                )
                continue
            if p.confidence == "low":
                warnings.append(f"LOW CONFIDENCE mapping included: {p.parameter_path} = {p.value}")
            if p.parameter_path in reforms:
                warnings.append(
                    f"Multiple provisions map to {p.parameter_path}; "
                    f"using the last value ({p.value})."
                )
            reforms[p.parameter_path] = p.value
        elif p.mapping_type == "industry_spending":
            if p.industry is None or p.amount_usd is None:
                warnings.append(f"Spending provision lacks industry/amount, skipped: {p.description}")
                continue
            try:
                match_industry(p.industry)
            except ValueError as e:
                warnings.append(str(e))
                continue
            if p.confidence == "low":
                warnings.append(
                    f"LOW CONFIDENCE spending mapping included: {p.industry} ${p.amount_usd:,.0f}"
                )
            program.append({"industry": p.industry, "amount_usd": p.amount_usd})
        else:
            warnings.append(f"Unmapped provision (not modeled): {p.description} — {p.rationale}")

    state = (state_override or extraction.state or "").upper()
    if state not in US_STATES:
        if program:
            warnings.append(
                "Spending provisions need a state for the regional I-O model; none identified. "
                "Specify a state to run the spending side."
            )
            program = []
        if reforms:
            # Tax/transfer provisions are still runnable nationally
            state = "US"
            warnings.append("No state identified; running the microsim nationally (no I-O panel).")

    if not reforms and not program:
        return None, warnings

    body: dict = {"name": extraction.name, "geography": {"state": state}}
    if reforms:
        body["tax_transfer"] = {"baseline_year": baseline_year, "reforms": reforms}
    if program:
        body["spending"] = {"source": "explicit_program", "explicit_program": program}
    elif reforms and state != "US":
        body["spending"] = {"source": "budget_delta"}

    try:
        return ReformSpec.model_validate(body), warnings
    except ValidationError as e:
        warnings.append(f"Assembled spec failed schema validation: {e}")
        return None, warnings


def interpret_and_run(text: str, state_override: Optional[str] = None):
    """Full auto-run flow: extract -> validate -> run. Raises ExtractionFailed
    (carrying the extraction) instead of ever fabricating a run."""
    from engines.pipeline import run_pipeline

    extraction = extract_provisions(text)
    spec, warnings = build_spec(extraction, state_override)
    if spec is None:
        raise ExtractionFailed(
            "No runnable provisions could be mapped. Extracted provisions are attached — "
            "supply the missing lever (a PolicyEngine parameter or an industry + amount) and retry.",
            extraction=extraction,
        )
    result = run_pipeline(spec)
    result.warnings.extend(warnings)
    return extraction, result
