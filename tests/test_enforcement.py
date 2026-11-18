"""Unit tests for scripts/_lib/enforcement.py and the get/delete scripts'
handling of the ListEnforcedGuardrailsConfiguration /
DeleteEnforcedGuardrailConfiguration API shapes.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _lib.enforcement import (  # noqa: E402
    config_ids,
    list_enforced_configs,
    parse_enforced_configs,
)

CONFIG = {
    "configId": "abc123",
    "guardrailId": "gr1",
    "guardrailArn": "arn:aws:bedrock:us-east-1:111111111111:guardrail/gr1",
    "guardrailVersion": "1",
    "modelEnforcement": {"includedModels": ["ALL"], "excludedModels": []},
}


class TestParseEnforcedConfigs:
    def test_reads_documented_guardrailsconfig_key(self):
        assert parse_enforced_configs({"guardrailsConfig": [CONFIG]}) == [CONFIG]

    def test_empty_list_when_no_enforcement(self):
        assert parse_enforced_configs({"guardrailsConfig": []}) == []

    def test_empty_list_on_unknown_shape(self):
        # Must not report enforcement based on guessed legacy keys.
        assert parse_enforced_configs({"enforcedGuardrailsConfiguration": [CONFIG]}) == []
        assert parse_enforced_configs({}) == []


class TestListEnforcedConfigs:
    def test_follows_pagination(self):
        client = MagicMock()
        client.list_enforced_guardrails_configuration.side_effect = [
            {"guardrailsConfig": [CONFIG], "nextToken": "t1"},
            {"guardrailsConfig": []},
        ]
        assert list_enforced_configs(client) == [CONFIG]
        calls = client.list_enforced_guardrails_configuration.call_args_list
        assert calls[0].kwargs == {}
        assert calls[1].kwargs == {"nextToken": "t1"}


class TestConfigIds:
    def test_extracts_ids(self):
        assert config_ids([CONFIG, {"configId": ""}, {}]) == ["abc123"]


class TestDeleteScript:
    def test_discovers_config_id_and_passes_it(self, monkeypatch):
        import delete_account_enforcement as dae

        bedrock = MagicMock()
        bedrock.list_enforced_guardrails_configuration.return_value = {
            "guardrailsConfig": [CONFIG]
        }
        sts = MagicMock()
        sts.get_caller_identity.return_value = {"Account": "111111111111"}

        def fake_client(service, **_):
            return {"bedrock": bedrock, "sts": sts}[service]

        monkeypatch.setattr(dae.boto3, "client", fake_client)
        monkeypatch.setattr(sys, "argv", ["delete", "--region", "us-east-1", "--yes"])
        assert dae.main() == 0
        bedrock.delete_enforced_guardrail_configuration.assert_called_once_with(
            configId="abc123"
        )

    def test_nothing_to_delete_when_no_config(self, monkeypatch):
        import delete_account_enforcement as dae

        bedrock = MagicMock()
        bedrock.list_enforced_guardrails_configuration.return_value = {"guardrailsConfig": []}
        sts = MagicMock()
        sts.get_caller_identity.return_value = {"Account": "111111111111"}
        monkeypatch.setattr(
            dae.boto3, "client", lambda s, **_: {"bedrock": bedrock, "sts": sts}[s]
        )
        monkeypatch.setattr(sys, "argv", ["delete", "--region", "us-east-1", "--yes"])
        assert dae.main() == 0
        bedrock.delete_enforced_guardrail_configuration.assert_not_called()


class TestGetScript:
    def test_reports_active_enforcement(self, monkeypatch, capsys):
        import get_account_enforcement as gae

        bedrock = MagicMock()
        bedrock.list_enforced_guardrails_configuration.return_value = {
            "guardrailsConfig": [CONFIG]
        }
        monkeypatch.setattr(gae.boto3, "client", lambda *a, **k: bedrock)
        monkeypatch.setattr(sys, "argv", ["get", "--region", "us-east-1"])
        assert gae.main() == 0
        out = capsys.readouterr().out
        assert "No account-level enforced guardrail configuration" not in out
        assert "configId         : abc123" in out
        assert "guardrailId      : gr1" in out
