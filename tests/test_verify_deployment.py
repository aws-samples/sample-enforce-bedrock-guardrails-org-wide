"""Unit tests for the verify_deployment release-gate script.

We don't exercise the actual AWS calls — those happen in the live pipeline.
Instead we cover the deterministic surfaces: argument parsing, the report
schema, and assertion behaviour given mocked Bedrock responses.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import verify_deployment as vd  # noqa: E402
from _lib.config import GuardrailConfig  # noqa: E402


def _cfg(tmp_path: Path) -> GuardrailConfig:
    return GuardrailConfig(
        region="us-east-1",
        model_id="anthropic.claude-3-haiku-20240307-v1:0",
        guardrail_id="abcd1234",
        guardrail_version="1",
        results_dir=tmp_path,
    )


def _benign_response() -> dict:
    body = MagicMock()
    body.read.return_value = json.dumps(
        {
            "content": [{"type": "text", "text": "4"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 1},
        }
    ).encode()
    return {"body": body, "ResponseMetadata": {"HTTPStatusCode": 200}}


def _intervened_response(
    *,
    guardrail_id: str = "abcd1234",
    guardrail_version: str = "1",
    include_applied_details: bool = True,
) -> dict:
    assessment: dict = {
        "topicPolicy": {
            "topics": [
                {
                    "name": "BenchmarkDeniedTopic",
                    "action": "BLOCKED",
                }
            ]
        }
    }
    if include_applied_details:
        assessment["appliedGuardrailDetails"] = {
            "guardrailId": guardrail_id,
            "guardrailArn": f"arn:aws:bedrock:us-east-1:111111111111:guardrail/{guardrail_id}",
            "guardrailVersion": guardrail_version,
            "guardrailOrigin": ["REQUEST"],
            "guardrailOwnership": "SELF",
        }
    body = MagicMock()
    body.read.return_value = json.dumps(
        {
            "content": [{"type": "text", "text": "[blocked]"}],
            "stop_reason": "guardrail_intervened",
            "amazon-bedrock-guardrailAction": "INTERVENED",
            "amazon-bedrock-trace": {
                "guardrail": {
                    "input": {
                        "assessments": [assessment]
                    }
                }
            },
        }
    ).encode()
    return {"body": body, "ResponseMetadata": {"HTTPStatusCode": 200}}


def _multi_assessment_response(assessments: list[dict]) -> dict:
    body = MagicMock()
    body.read.return_value = json.dumps(
        {
            "stop_reason": "guardrail_intervened",
            "amazon-bedrock-guardrailAction": "INTERVENED",
            "amazon-bedrock-trace": {"guardrail": {"input": {"assessments": assessments}}},
        }
    ).encode()
    return {"body": body, "ResponseMetadata": {"HTTPStatusCode": 200}}


def _client_error(code: str, message: str = "test error") -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": message}},
        operation_name="InvokeModel",
    )


class TestCheckLatency:
    def test_passes_when_under_threshold(self, tmp_path, caplog, monkeypatch):
        monkeypatch.setattr(vd, "ITERATIONS", 3)
        monkeypatch.setattr(vd, "P99_THRESHOLD_MS", 10_000.0)
        client = MagicMock()
        client.invoke_model.return_value = _benign_response()
        log = MagicMock()
        result = vd.check_latency(client, _cfg(tmp_path), log)
        assert "p99_ms" in result
        assert result["iterations"] == 3
        assert client.invoke_model.call_count == 3

    def test_fails_when_over_threshold(self, tmp_path, monkeypatch):
        # Force a very low threshold so any real call exceeds it.
        monkeypatch.setattr(vd, "ITERATIONS", 1)
        monkeypatch.setattr(vd, "P99_THRESHOLD_MS", 0.001)
        client = MagicMock()
        client.invoke_model.return_value = _benign_response()
        with pytest.raises(vd.VerifyFailure, match="p99 latency"):
            vd.check_latency(client, _cfg(tmp_path), MagicMock())


class TestCheckIntervention:
    def test_pass_on_intervened(self, tmp_path):
        client = MagicMock()
        client.invoke_model.return_value = _intervened_response(
            guardrail_id="abcd1234", guardrail_version="1"
        )
        result = vd.check_intervention(client, _cfg(tmp_path), MagicMock())
        assert result["action"] == "INTERVENED"
        assert result["identity_confirmed"] is True
        assert result["findings"]
        assert any(f["policy_type"] == "topicPolicy" for f in result["findings"])

    def test_fail_on_action_none(self, tmp_path):
        body = MagicMock()
        body.read.return_value = json.dumps(
            {"amazon-bedrock-guardrailAction": "NONE", "stop_reason": "end_turn"}
        ).encode()
        client = MagicMock()
        client.invoke_model.return_value = {
            "body": body,
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }
        with pytest.raises(vd.VerifyFailure, match="INTERVENED"):
            vd.check_intervention(client, _cfg(tmp_path), MagicMock())

    def test_fail_when_wrong_guardrail_intervened(self, tmp_path):
        """CSR-004: a DIFFERENT guardrail (wrong id/version) intervening on
        the test prompt must fail the gate, not pass it."""
        client = MagicMock()
        client.invoke_model.return_value = _intervened_response(
            guardrail_id="some-other-guardrail", guardrail_version="3"
        )
        with pytest.raises(vd.VerifyFailure, match="do not match the deployed guardrail"):
            vd.check_intervention(client, _cfg(tmp_path), MagicMock())

    def test_fail_when_version_mismatch_same_id(self, tmp_path):
        """Same guardrail id but wrong version must also fail — proves the
        assertion checks version, not just id."""
        client = MagicMock()
        client.invoke_model.return_value = _intervened_response(
            guardrail_id="abcd1234", guardrail_version="2"
        )
        with pytest.raises(vd.VerifyFailure, match="do not match the deployed guardrail"):
            vd.check_intervention(client, _cfg(tmp_path), MagicMock())

    def test_fail_by_default_when_no_applied_details(self, tmp_path, monkeypatch):
        """When Bedrock doesn't return appliedGuardrailDetails for the
        assessment that blocked, identity cannot be proven, so the gate must
        FAIL by default rather than pass on a warning."""
        monkeypatch.setattr(vd, "ALLOW_UNCONFIRMED_IDENTITY", False)
        client = MagicMock()
        client.invoke_model.return_value = _intervened_response(
            include_applied_details=False
        )
        with pytest.raises(vd.VerifyFailure, match="no appliedGuardrailDetails"):
            vd.check_intervention(client, _cfg(tmp_path), MagicMock())

    def test_pass_unconfirmed_when_explicitly_allowed(self, tmp_path, monkeypatch):
        """Operators can opt in to accepting unattributed interventions; the
        report must then say identity_confirmed=False explicitly."""
        monkeypatch.setattr(vd, "ALLOW_UNCONFIRMED_IDENTITY", True)
        client = MagicMock()
        client.invoke_model.return_value = _intervened_response(
            include_applied_details=False
        )
        result = vd.check_intervention(client, _cfg(tmp_path), MagicMock())
        assert result["action"] == "INTERVENED"
        assert result["identity_confirmed"] is False
        assert result["blocking_guardrails"] == ["unattributed"]

    def test_fail_when_ours_in_scope_but_other_guardrail_blocked(self, tmp_path):
        """The deployed guardrail evaluated the prompt but found nothing;
        a different guardrail is the one that BLOCKED. Previously this passed
        because 'any applied guardrail matched'. It must fail."""
        ours_clean = {
            "topicPolicy": {"topics": [{"name": "BenchmarkDeniedTopic", "action": "NONE"}]},
            "appliedGuardrailDetails": {
                "guardrailId": "abcd1234",
                "guardrailArn": "arn:aws:bedrock:us-east-1:111111111111:guardrail/abcd1234",
                "guardrailVersion": "1",
                "guardrailOrigin": ["REQUEST"],
                "guardrailOwnership": "SELF",
            },
        }
        other_blocked = {
            "topicPolicy": {"topics": [{"name": "OrgDeniedTopic", "action": "BLOCKED"}]},
            "appliedGuardrailDetails": {
                "guardrailId": "orgguard99",
                "guardrailArn": "arn:aws:bedrock:us-east-1:222222222222:guardrail/orgguard99",
                "guardrailVersion": "4",
                "guardrailOrigin": ["ORGANIZATION_ENFORCED"],
                "guardrailOwnership": "CROSS_ACCOUNT",
            },
        }
        client = MagicMock()
        client.invoke_model.return_value = _multi_assessment_response([ours_clean, other_blocked])
        with pytest.raises(vd.VerifyFailure, match="orgguard99:4"):
            vd.check_intervention(client, _cfg(tmp_path), MagicMock())

    def test_pass_when_ours_and_another_both_block(self, tmp_path):
        """Union semantics: if the deployed guardrail blocked AND an org
        guardrail also blocked, that is a valid PASS with both reported."""
        ours = {
            "topicPolicy": {"topics": [{"name": "BenchmarkDeniedTopic", "action": "BLOCKED"}]},
            "appliedGuardrailDetails": {
                "guardrailId": "abcd1234",
                "guardrailVersion": "1",
                "guardrailOrigin": ["REQUEST"],
            },
        }
        other = {
            "contentPolicy": {"filters": [{"type": "PROMPT_ATTACK", "action": "BLOCKED"}]},
            "appliedGuardrailDetails": {
                "guardrailId": "orgguard99",
                "guardrailVersion": "4",
                "guardrailOrigin": ["ORGANIZATION_ENFORCED"],
            },
        }
        client = MagicMock()
        client.invoke_model.return_value = _multi_assessment_response([ours, other])
        result = vd.check_intervention(client, _cfg(tmp_path), MagicMock())
        assert result["identity_confirmed"] is True
        assert set(result["blocking_guardrails"]) == {"abcd1234:1", "orgguard99:4"}

    def test_pass_on_inference_profile_trace_layout(self, tmp_path):
        """Inference profiles return the trace under
        amazon-bedrock-guardrail-trace with inputAssessment as a single
        object; identity must still be attributed."""
        assessment = {
            "topicPolicy": {"topics": [{"name": "BenchmarkDeniedTopic", "action": "BLOCKED"}]},
            "appliedGuardrailDetails": {"guardrailId": "abcd1234", "guardrailVersion": "1"},
        }
        body = MagicMock()
        body.read.return_value = json.dumps(
            {
                "amazon-bedrock-guardrailAction": "INTERVENED",
                "amazon-bedrock-guardrail-trace": {"inputAssessment": assessment},
            }
        ).encode()
        client = MagicMock()
        client.invoke_model.return_value = {"body": body, "ResponseMetadata": {}}
        result = vd.check_intervention(client, _cfg(tmp_path), MagicMock())
        assert result["identity_confirmed"] is True

    def test_fail_when_intervened_but_no_blocked_findings(self, tmp_path):
        body = MagicMock()
        body.read.return_value = json.dumps(
            {
                "amazon-bedrock-guardrailAction": "INTERVENED",
                "amazon-bedrock-trace": {"guardrail": {"input": {"assessments": [{}]}}},
            }
        ).encode()
        client = MagicMock()
        client.invoke_model.return_value = {"body": body, "ResponseMetadata": {}}
        with pytest.raises(vd.VerifyFailure, match="no BLOCKED findings"):
            vd.check_intervention(client, _cfg(tmp_path), MagicMock())


class TestCheckDraftRejection:
    def test_pass_when_validation_exception(self, tmp_path):
        client = MagicMock()
        client.invoke_model.side_effect = _client_error(
            "ValidationException", "guardrail version DRAFT is not allowed"
        )
        result = vd.check_draft_rejection(client, _cfg(tmp_path), MagicMock())
        assert result["error_code"] == "ValidationException"
        assert "DRAFT" in result["message_excerpt"]

    def test_fail_when_wrong_error(self, tmp_path):
        client = MagicMock()
        client.invoke_model.side_effect = _client_error("AccessDeniedException")
        with pytest.raises(vd.VerifyFailure, match="ValidationException"):
            vd.check_draft_rejection(client, _cfg(tmp_path), MagicMock())

    def test_pass_when_no_error_org_policy_active(self, tmp_path):
        # When an org policy is active, DRAFT calls succeed (org guardrail takes over).
        # This should PASS, not fail.
        client = MagicMock()
        client.invoke_model.return_value = _benign_response()
        result = vd.check_draft_rejection(client, _cfg(tmp_path), MagicMock())
        assert result["mode"] == "org_policy_takeover"
