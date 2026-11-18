#!/usr/bin/env python3
"""Show the current account-level enforced guardrail configuration (Layer 3).

Calls bedrock:ListEnforcedGuardrailsConfiguration and prints what is active
in the account/region. Use it to verify set_account_enforcement.py worked,
or to check state before deleting.

Example
-------
python get_account_enforcement.py --region eu-west-1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib.enforcement import list_enforced_configs
from _lib.logging_setup import configure

DEFAULT_REGION = "us-east-1"


def main() -> int:
    p = argparse.ArgumentParser(
        description="Show the account-level enforced guardrail configuration"
    )
    p.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", DEFAULT_REGION),
        help=f"AWS region (default {DEFAULT_REGION} or $AWS_REGION)",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true", help="Enable DEBUG logging"
    )
    args = p.parse_args()
    log = configure(args.verbose)

    client = boto3.client("bedrock", region_name=args.region)

    try:
        configs = list_enforced_configs(client)
    except AttributeError:
        log.error(
            "Your boto3 does not expose list_enforced_guardrails_configuration. "
            "Upgrade with: pip install -U boto3"
        )
        return 3
    except ClientError as e:
        err = e.response["Error"]
        log.error("List call failed: %s: %s", err.get("Code"), err.get("Message"))
        return 4

    print()
    if not configs:
        print(f"No account-level enforced guardrail configuration in {args.region}.")
        print("Calls are governed only by attached guardrails (Layer 4) or an")
        print("org-level Bedrock policy (Layer 1), if either is in effect.")
        return 0

    print(f"Account-level enforced guardrail configuration in {args.region}:")
    for c in configs:
        print(f"  configId         : {c.get('configId')}")
        print(f"  guardrailId      : {c.get('guardrailId')}")
        print(f"  guardrailVersion : {c.get('guardrailVersion')}")
        print(f"  guardrailArn     : {c.get('guardrailArn')}")
        me = c.get("modelEnforcement") or {}
        print(f"  includedModels   : {me.get('includedModels')}")
        print(f"  excludedModels   : {me.get('excludedModels')}")
        print(f"  updatedAt        : {c.get('updatedAt')}  by {c.get('updatedBy')}")
    if args.verbose:
        print()
        print(json.dumps(configs, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
