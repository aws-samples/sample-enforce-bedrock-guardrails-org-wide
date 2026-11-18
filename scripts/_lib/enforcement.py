"""Helpers for the account-level enforced guardrail configuration APIs.

The Bedrock control-plane API surface (see
https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListEnforcedGuardrailsConfiguration.html
and
https://docs.aws.amazon.com/bedrock/latest/APIReference/API_DeleteEnforcedGuardrailConfiguration.html):

- ``ListEnforcedGuardrailsConfiguration`` returns ``{"guardrailsConfig": [...]}``
  with at most one item per account/region; each item carries ``configId``,
  ``guardrailId``, ``guardrailArn``, ``guardrailVersion``, ``modelEnforcement``
  and audit fields.
- ``DeleteEnforcedGuardrailConfiguration`` requires that ``configId``.

These functions are pure over an already-constructed response/client so the
parsing is unit-testable without AWS.
"""
from __future__ import annotations

from typing import Any, Iterable

RESPONSE_KEY = "guardrailsConfig"


def parse_enforced_configs(resp: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the list of enforced configurations from a List* response.

    Accepts the documented ``guardrailsConfig`` key. Any other shape yields
    an empty list rather than guessing.
    """
    configs = resp.get(RESPONSE_KEY)
    if not isinstance(configs, list):
        return []
    return [c for c in configs if isinstance(c, dict)]


def list_enforced_configs(client) -> list[dict[str, Any]]:
    """Call ListEnforcedGuardrailsConfiguration and follow pagination."""
    configs: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {}
    while True:
        resp = client.list_enforced_guardrails_configuration(**kwargs)
        configs.extend(parse_enforced_configs(resp))
        token = resp.get("nextToken")
        if not token:
            return configs
        kwargs = {"nextToken": token}


def config_ids(configs: Iterable[dict[str, Any]]) -> list[str]:
    """Extract the non-empty ``configId`` values from parsed configs."""
    return [c["configId"] for c in configs if c.get("configId")]
