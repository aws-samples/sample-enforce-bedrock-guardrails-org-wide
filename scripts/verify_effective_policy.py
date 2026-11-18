#!/usr/bin/env python3
"""Capture the effective Bedrock Organizations policy for a target.

Requires organizations:DescribeEffectivePolicy permission — typically
runs from the management account or a delegated administrator.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib.config import base_arg_parser
from _lib.logging_setup import configure
from _lib.secure_io import secure_file, secure_results_dir


def main() -> int:
    p = base_arg_parser("Capture DescribeEffectivePolicy output for BEDROCK_POLICY")
    p.add_argument(
        "--target",
        default=os.environ.get("TARGET_ACCOUNT_ID"),
        help="12-digit account id or OU id (also TARGET_ACCOUNT_ID env)",
    )
    args = p.parse_args()
    log = configure(args.verbose)

    if not args.target:
        log.error("--target (or TARGET_ACCOUNT_ID) is required")
        return 2

    out_dir = Path(__file__).resolve().parent.parent / "results"
    secure_results_dir(out_dir)

    client = boto3.client("organizations")
    try:
        resp = client.describe_effective_policy(
            PolicyType="BEDROCK_POLICY",
            TargetId=args.target,
        )
    except ClientError as e:
        err = e.response["Error"]
        log.error("DescribeEffectivePolicy failed: %s: %s", err.get("Code"), err.get("Message"))
        return 3

    ep = resp.get("EffectivePolicy", {}) or {}
    raw_content = ep.get("PolicyContent", "{}")
    try:
        content = json.loads(raw_content)
    except json.JSONDecodeError:
        content = raw_content

    payload = {
        "target_id": args.target,
        "policy_type": ep.get("PolicyType"),
        "last_updated_timestamp": str(ep.get("LastUpdatedTimestamp")),
        "content": content,
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"effective_policy_{ts}.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True))
    secure_file(out)  # CSR-009: policy content includes guardrail ARNs
    log.info("wrote %s", out)

    print()
    print("Effective guardrails:")
    bedrock = (content.get("bedrock") if isinstance(content, dict) else {}) or {}
    gi = bedrock.get("guardrail_inference", {}) or {}
    if not gi:
        print("  (no Bedrock policy effective for this target)")
    for region, configs in gi.items():
        for cfg_name, cfg in (configs or {}).items():
            ident = (cfg or {}).get("identifier", {})
            value = ident.get("@@assign") if isinstance(ident, dict) else None
            print(f"  region={region}  config={cfg_name}  guardrail={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
