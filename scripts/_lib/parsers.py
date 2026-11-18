"""Parsers for Bedrock InvokeModel and ApplyGuardrail responses.

Pure functions. No I/O. Unit tested in tests/test_parsers.py.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    source: str  # 'input' | 'output' | 'guardrail' (top-level)
    policy_type: str  # 'topicPolicy' | 'contentPolicy' | 'sensitiveInformationPolicy' | 'wordPolicy'
    detail: str  # human-readable detail of which rule fired


def parse_apply_guardrail(response: dict) -> list[Finding]:
    """Extract every BLOCKED/ANONYMIZED finding from an ApplyGuardrail response."""
    findings: list[Finding] = []
    for assessment in response.get("assessments", []) or []:
        findings.extend(_findings_from_assessment("apply", assessment))
    return findings


def parse_invoke_trace(response: dict) -> list[Finding]:
    """Extract findings from an InvokeModel response that requested trace=ENABLED."""
    findings: list[Finding] = []
    trace = response.get("amazon-bedrock-trace", {}) or {}
    guardrail = trace.get("guardrail", {}) or {}
    for source in ("input", "output"):
        for assessment in guardrail.get(source, {}).get("assessments") or []:
            findings.extend(_findings_from_assessment(source, assessment))
    return findings


@dataclass(frozen=True)
class AppliedGuardrailDetails:
    """Identity of the specific guardrail that produced an assessment.

    Bedrock returns this per-assessment (not just a top-level action flag)
    so a caller can verify WHICH guardrail intervened, not just that some
    guardrail did. See:
    https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_AppliedGuardrailDetails.html
    """

    guardrail_id: str | None
    guardrail_arn: str | None
    guardrail_version: str | None
    guardrail_origin: tuple[str, ...]  # REQUEST | ACCOUNT_ENFORCED | ORGANIZATION_ENFORCED
    guardrail_ownership: str | None  # SELF | CROSS_ACCOUNT


def extract_applied_guardrail_details(assessment: dict) -> AppliedGuardrailDetails | None:
    """Pull appliedGuardrailDetails out of a single GuardrailAssessment object.

    Returns None if the field is absent (older API responses / some
    inference-profile paths may not populate it).
    """
    details = assessment.get("appliedGuardrailDetails")
    if not details:
        return None
    origin = details.get("guardrailOrigin") or []
    if isinstance(origin, str):
        origin = [origin]
    return AppliedGuardrailDetails(
        guardrail_id=details.get("guardrailId"),
        guardrail_arn=details.get("guardrailArn"),
        guardrail_version=details.get("guardrailVersion"),
        guardrail_origin=tuple(origin),
        guardrail_ownership=details.get("guardrailOwnership"),
    )


def extract_all_applied_guardrail_details(response: dict) -> list["AppliedGuardrailDetails"]:
    """Collect appliedGuardrailDetails from every assessment in an InvokeModel
    trace response (standard amazon-bedrock-trace path)."""
    out: list[AppliedGuardrailDetails] = []
    trace = response.get("amazon-bedrock-trace", {}) or {}
    guardrail = trace.get("guardrail", {}) or {}
    for source in ("input", "output"):
        for assessment in guardrail.get(source, {}).get("assessments") or []:
            details = extract_applied_guardrail_details(assessment)
            if details:
                out.append(details)
    return out


@dataclass(frozen=True)
class AssessmentRecord:
    """One GuardrailAssessment with its findings kept next to its identity.

    ``parse_invoke_trace`` / ``extract_all_applied_guardrail_details`` flatten
    the response and lose the pairing between *which guardrail* produced an
    assessment and *what it blocked*. The release gate needs that pairing to
    prove the guardrail under test is the one that intervened, rather than
    some other guardrail that happened to be in scope.
    """

    source: str  # 'input' | 'output'
    details: AppliedGuardrailDetails | None
    findings: tuple[Finding, ...]

    @property
    def blocked(self) -> bool:
        return bool(self.findings)


def _iter_assessments(response: dict):
    """Yield (source, assessment) for every assessment in an InvokeModel
    trace, covering both trace layouts Bedrock uses:

    - ``amazon-bedrock-trace.guardrail.{input,output}.assessments`` for
      direct model IDs;
    - ``amazon-bedrock-guardrail-trace.{inputAssessment,outputAssessments}``
      for inference profiles (``us.``/``eu.``/``global.`` prefixes). The
      ``inputAssessment`` member is a single object in some responses and a
      list in others.
    """
    trace = response.get("amazon-bedrock-trace", {}) or {}
    guardrail = trace.get("guardrail", {}) or {}
    for source in ("input", "output"):
        for a in guardrail.get(source, {}).get("assessments") or []:
            if isinstance(a, dict):
                yield source, a

    alt = response.get("amazon-bedrock-guardrail-trace", {}) or {}
    for key, source in (("inputAssessment", "input"), ("outputAssessments", "output")):
        val = alt.get(key)
        if isinstance(val, dict):
            yield source, val
        elif isinstance(val, list):
            for a in val:
                if isinstance(a, dict):
                    yield source, a


def parse_assessments(response: dict) -> list[AssessmentRecord]:
    """Return every assessment in an InvokeModel trace with identity and
    BLOCKED/ANONYMIZED findings paired per assessment."""
    return [
        AssessmentRecord(
            source=source,
            details=extract_applied_guardrail_details(a),
            findings=tuple(_findings_from_assessment(source, a)),
        )
        for source, a in _iter_assessments(response)
    ]


def _findings_from_assessment(source: str, assessment: dict) -> list[Finding]:
    out: list[Finding] = []

    cp = assessment.get("contentPolicy", {})
    for f in cp.get("filters", []) or []:
        if f.get("action") == "BLOCKED":
            out.append(Finding(source, "contentPolicy", f.get("type", "?")))

    tp = assessment.get("topicPolicy", {})
    for t in tp.get("topics", []) or []:
        if t.get("action") == "BLOCKED":
            out.append(Finding(source, "topicPolicy", t.get("name", "?")))

    sp = assessment.get("sensitiveInformationPolicy", {})
    for p in sp.get("piiEntities", []) or []:
        if p.get("action") in ("BLOCKED", "ANONYMIZED"):
            out.append(
                Finding(
                    source,
                    "sensitiveInformationPolicy",
                    f"{p.get('type', '?')}({p.get('action')})",
                )
            )

    wp = assessment.get("wordPolicy", {})
    for w in wp.get("customWords", []) or []:
        if w.get("action") == "BLOCKED":
            out.append(Finding(source, "wordPolicy", w.get("match", "?")))

    return out


def estimate_cost_usd(
    *,
    input_tokens: int,
    output_tokens: int,
    model_id: str,
) -> float:
    """Rough cost estimate based on Anthropic-on-Bedrock list pricing.

    Pricing here is conservative: it tends to be slightly higher than the
    actual billed rate. Suitable for blog narrative ("the entire experiment
    cost approximately $X") not for invoicing.

    Update the table when AWS publishes price changes.
    """
    pricing = {
        # USD per 1M tokens, (input, output) — Anthropic on Bedrock list pricing.
        "anthropic.claude-3-haiku-20240307-v1:0": (0.25, 1.25),
        "anthropic.claude-3-5-haiku-20241022-v1:0": (0.80, 4.00),
        "anthropic.claude-3-sonnet-20240229-v1:0": (3.00, 15.00),
        "anthropic.claude-3-5-sonnet-20240620-v1:0": (3.00, 15.00),
        "anthropic.claude-3-opus-20240229-v1:0": (15.00, 75.00),
    }
    in_rate, out_rate = pricing.get(model_id, (1.0, 5.0))  # safe-ish fallback
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
