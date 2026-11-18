"""Unit tests for scripts/_lib/parsers.py."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _lib.parsers import (  # noqa: E402
    Finding,
    estimate_cost_usd,
    parse_apply_guardrail,
    parse_invoke_trace,
)


class TestParseApplyGuardrail:
    def test_no_findings_when_action_is_none(self) -> None:
        resp = {
            "action": "NONE",
            "assessments": [
                {
                    "topicPolicy": {"topics": [{"name": "X", "action": "NONE"}]},
                }
            ],
        }
        assert parse_apply_guardrail(resp) == []

    def test_picks_up_topic_policy(self) -> None:
        resp = {
            "action": "GUARDRAIL_INTERVENED",
            "assessments": [
                {
                    "topicPolicy": {
                        "topics": [
                            {"name": "AcademicDishonesty", "action": "BLOCKED"},
                        ]
                    },
                }
            ],
        }
        findings = parse_apply_guardrail(resp)
        assert findings == [Finding("apply", "topicPolicy", "AcademicDishonesty")]

    def test_picks_up_pii(self) -> None:
        resp = {
            "assessments": [
                {
                    "sensitiveInformationPolicy": {
                        "piiEntities": [
                            {"type": "EMAIL", "action": "BLOCKED"},
                        ]
                    },
                }
            ],
        }
        findings = parse_apply_guardrail(resp)
        assert findings == [
            Finding("apply", "sensitiveInformationPolicy", "EMAIL(BLOCKED)"),
        ]

    def test_picks_up_content_filter(self) -> None:
        resp = {
            "assessments": [
                {
                    "contentPolicy": {
                        "filters": [{"type": "HATE", "action": "BLOCKED"}],
                    },
                }
            ],
        }
        assert parse_apply_guardrail(resp) == [
            Finding("apply", "contentPolicy", "HATE")
        ]


class TestParseInvokeTrace:
    def test_input_and_output_assessments(self) -> None:
        resp = {
            "amazon-bedrock-trace": {
                "guardrail": {
                    "input": {
                        "assessments": [
                            {
                                "topicPolicy": {
                                    "topics": [{"name": "T", "action": "BLOCKED"}]
                                }
                            }
                        ]
                    },
                    "output": {
                        "assessments": [
                            {
                                "contentPolicy": {
                                    "filters": [{"type": "HATE", "action": "BLOCKED"}]
                                }
                            }
                        ]
                    },
                }
            }
        }
        findings = parse_invoke_trace(resp)
        assert Finding("input", "topicPolicy", "T") in findings
        assert Finding("output", "contentPolicy", "HATE") in findings


class TestEstimateCost:
    def test_haiku_pricing(self) -> None:
        cost = estimate_cost_usd(
            input_tokens=1_000_000,
            output_tokens=0,
            model_id="anthropic.claude-3-haiku-20240307-v1:0",
        )
        assert cost == 0.25

    def test_unknown_model_uses_safe_fallback(self) -> None:
        cost = estimate_cost_usd(
            input_tokens=1_000_000,
            output_tokens=0,
            model_id="something.unknown",
        )
        assert cost > 0
