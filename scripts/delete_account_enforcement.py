#!/usr/bin/env python3
"""Delete the account-level enforced guardrail configuration (reverse Layer 3).

Calls bedrock:DeleteEnforcedGuardrailConfiguration to stop applying an
account-wide guardrail. After this, InvokeModel / Converse calls are only
evaluated by whatever guardrail the caller attaches (Layer 4) or by an
org-level Bedrock policy (Layer 1) if one is in effect.

Unlike the other scripts, this one only needs a region. The API requires
the configuration's ``configId``, so the script first calls
ListEnforcedGuardrailsConfiguration to discover it (there is at most one
per account/region), or you can pass ``--config-id`` explicitly.

SAFETY (CSR-006): this is an account-wide, destructive change — it removes
the guardrail floor for every InvokeModel/Converse call in the account and
region that does not otherwise attach its own guardrail or fall under an
org-level Bedrock policy. By default this script requires either an
interactive confirmation or an explicit --yes flag; it will not silently
delete an enforced configuration in a non-interactive context without one.

Example
-------
python delete_account_enforcement.py --region eu-west-1
python delete_account_enforcement.py --region eu-west-1 --yes   # non-interactive / CI
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib.enforcement import config_ids, list_enforced_configs
from _lib.logging_setup import configure

DEFAULT_REGION = "us-east-1"


def _confirm(region: str, account_hint: str, config: dict) -> bool:
    """Interactive confirmation gate. Returns True if the operator confirms."""
    print()
    print("This will DELETE the account-level enforced guardrail configuration")
    print(f"  region    : {region}")
    print(f"  account   : {account_hint}")
    print(f"  configId  : {config.get('configId')}")
    print(f"  guardrail : {config.get('guardrailId')} v{config.get('guardrailVersion')}")
    print()
    print("Every InvokeModel / Converse call in this account and region will")
    print("stop being evaluated by this floor guardrail (unless an org-level")
    print("Bedrock policy or the caller's own guardrailIdentifier still applies).")
    reply = input("Type 'delete' to confirm, anything else to abort: ").strip()
    return reply == "delete"


def main() -> int:
    p = argparse.ArgumentParser(
        description="Delete the account-level enforced guardrail configuration"
    )
    p.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", DEFAULT_REGION),
        help=f"AWS region (default {DEFAULT_REGION} or $AWS_REGION)",
    )
    p.add_argument(
        "--config-id",
        default=os.environ.get("ENFORCED_CONFIG_ID"),
        help="configId to delete (default: discovered via ListEnforcedGuardrailsConfiguration "
             "or $ENFORCED_CONFIG_ID)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt (required for CI/non-interactive use).",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true", help="Enable DEBUG logging"
    )
    args = p.parse_args()
    log = configure(args.verbose)

    sts = boto3.client("sts")
    try:
        account_hint = sts.get_caller_identity().get("Account", "unknown")
    except ClientError:
        account_hint = "unknown (could not call sts:GetCallerIdentity)"

    client = boto3.client("bedrock", region_name=args.region)

    # DeleteEnforcedGuardrailConfiguration requires configId. Discover it
    # unless the operator supplied one.
    try:
        configs = list_enforced_configs(client)
    except AttributeError:
        log.error(
            "Your boto3 is too old to support the enforced-guardrail APIs. "
            "Upgrade with: pip install -U boto3"
        )
        return 3
    except ClientError as e:
        err = e.response["Error"]
        log.error("ListEnforcedGuardrailsConfiguration failed: %s: %s",
                  err.get("Code"), err.get("Message"))
        return 4

    if args.config_id:
        config_id = args.config_id
        config = next((c for c in configs if c.get("configId") == config_id),
                      {"configId": config_id})
    else:
        ids = config_ids(configs)
        if not ids:
            print(f"No enforced configuration found in {args.region} — nothing to delete.")
            return 0
        if len(ids) > 1:
            log.error(
                "Found %d enforced configurations (%s); pass --config-id to choose one.",
                len(ids), ", ".join(ids),
            )
            return 5
        config_id = ids[0]
        config = configs[0]

    if not args.yes:
        if not sys.stdin.isatty():
            log.error(
                "Refusing to delete account-level enforcement in a non-interactive "
                "context without --yes. Re-run with --yes if this is intentional "
                "(e.g. from CI)."
            )
            return 2
        if not _confirm(args.region, account_hint, config):
            print("Aborted — no changes made.")
            return 1

    log.info("Deleting enforced configuration %s in region %s (account %s)",
             config_id, args.region, account_hint)
    try:
        client.delete_enforced_guardrail_configuration(configId=config_id)
    except ClientError as e:
        err = e.response["Error"]
        code = err.get("Code")
        if code == "ResourceNotFoundException":
            print(f"Enforced configuration {config_id} not found in {args.region} — "
                  "nothing to delete.")
            return 0
        log.error("DeleteEnforcedGuardrailConfiguration failed: %s: %s",
                  code, err.get("Message"))
        return 4

    print()
    print(f"Account-level enforcement {config_id} cleared in {args.region}.")
    print("Calls are now governed only by any attached guardrail (Layer 4) or")
    print("an org-level Bedrock policy (Layer 1), if either is in effect.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
