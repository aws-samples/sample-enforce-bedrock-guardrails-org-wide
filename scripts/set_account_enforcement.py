#!/usr/bin/env python3
"""Set the account-level enforced guardrail configuration (Layer 3).

Calls bedrock:PutEnforcedGuardrailConfiguration so that EVERY InvokeModel /
Converse call in this account and region is evaluated by the named guardrail,
regardless of whether the caller attaches a guardrailIdentifier.

This is the "Option B" mechanism from the blog — an account-wide floor that
does not depend on individual applications opting in.

Contrast with per-app attachment (Option A / Layer 4), where each call must
pass guardrailIdentifier itself (see run_benchmark.py / capture_trace.py).

Examples
--------
# Enforce on all models
python set_account_enforcement.py \
    --guardrail-id abcd1234 --guardrail-version 1 --region eu-west-1

# Enforce on all models except embeddings (recommended — guardrails do not
# apply to embedding models, so excluding them avoids wasted evaluation)
python set_account_enforcement.py \
    --guardrail-id abcd1234 --guardrail-version 1 --region eu-west-1 \
    --exclude-models amazon.titan-embed-text-v2:0 cohere.embed-english-v3

Reverse with: delete_account_enforcement.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib.config import GuardrailConfig, base_arg_parser
from _lib.logging_setup import configure


def build_inference_config(
    guardrail_id: str,
    guardrail_version: str,
    included_models: list[str],
    excluded_models: list[str],
    system_guarding: str,
    messages_guarding: str,
) -> dict:
    """Assemble the guardrailInferenceConfig structure for the API.

    Matches the shape documented by:
      aws bedrock put-enforced-guardrail-configuration help
    """
    cfg: dict = {
        "guardrailIdentifier": guardrail_id,
        "guardrailVersion": guardrail_version,
        "modelEnforcement": {
            "includedModels": included_models,
            "excludedModels": excluded_models,
        },
    }
    # selectiveContentGuarding is optional; only include when explicitly set
    if system_guarding or messages_guarding:
        cfg["selectiveContentGuarding"] = {}
        if system_guarding:
            cfg["selectiveContentGuarding"]["system"] = system_guarding
        if messages_guarding:
            cfg["selectiveContentGuarding"]["messages"] = messages_guarding
    return cfg


def main() -> int:
    p = base_arg_parser(
        "Set the account-level enforced guardrail configuration (Layer 3)"
    )
    p.add_argument(
        "--included-models",
        nargs="*",
        default=["ALL"],
        help="Model ids to enforce on, or ALL (default: ALL).",
    )
    p.add_argument(
        "--exclude-models",
        nargs="*",
        default=[],
        help="Model ids to exclude from enforcement (e.g. embedding models).",
    )
    p.add_argument(
        "--system-guarding",
        choices=["SELECTIVE", "COMPREHENSIVE"],
        default=None,
        help="How system prompts are guarded (default: API default COMPREHENSIVE).",
    )
    p.add_argument(
        "--messages-guarding",
        choices=["SELECTIVE", "COMPREHENSIVE"],
        default=None,
        help="How user messages are guarded (default: API default COMPREHENSIVE).",
    )
    args = p.parse_args()
    log = configure(args.verbose)
    cfg = GuardrailConfig.from_args(args)

    # The account-level enforcement API lives on the bedrock control plane,
    # not bedrock-runtime.
    client = boto3.client("bedrock", region_name=cfg.region)

    inference_config = build_inference_config(
        guardrail_id=cfg.guardrail_id,
        guardrail_version=cfg.guardrail_version,
        included_models=args.included_models,
        excluded_models=args.exclude_models,
        system_guarding=args.system_guarding,
        messages_guarding=args.messages_guarding,
    )

    log.info(
        "Setting account-level enforcement: guardrail=%s v%s region=%s",
        cfg.guardrail_id,
        cfg.guardrail_version,
        cfg.region,
    )
    log.debug("guardrailInferenceConfig=%s", json.dumps(inference_config))

    try:
        resp = client.put_enforced_guardrail_configuration(
            guardrailInferenceConfig=inference_config
        )
    except AttributeError:
        log.error(
            "Your boto3 is too old to support put_enforced_guardrail_configuration. "
            "Upgrade with: pip install -U boto3"
        )
        return 3
    except ClientError as e:
        err = e.response["Error"]
        log.error("PutEnforcedGuardrailConfiguration failed: %s: %s",
                  err.get("Code"), err.get("Message"))
        return 4

    config_id = resp.get("configId")
    updated_at = resp.get("updatedAt")
    print()
    print("Account-level enforcement is now ACTIVE.")
    print(f"  configId  : {config_id}")
    print(f"  updatedAt : {updated_at}")
    print(f"  guardrail : {cfg.guardrail_id} v{cfg.guardrail_version}")
    print(f"  region    : {cfg.region}")
    print(f"  included  : {args.included_models}")
    print(f"  excluded  : {args.exclude_models or '(none)'}")
    print()
    print("Every InvokeModel / Converse call in this account and region is now")
    print("evaluated by this guardrail, even calls that pass no guardrailIdentifier.")
    print("Reverse with: python delete_account_enforcement.py --region", cfg.region)
    return 0


if __name__ == "__main__":
    sys.exit(main())
