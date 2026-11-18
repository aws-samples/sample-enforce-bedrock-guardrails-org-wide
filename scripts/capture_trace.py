#!/usr/bin/env python3
"""Capture a fully-traced intervened InvokeModel response for the blog post.

Quote the resulting JSON file in the post; do not paraphrase it.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib.config import GuardrailConfig, base_arg_parser
from _lib.logging_setup import configure
from _lib.parsers import parse_invoke_trace
from _lib.secure_io import secure_file


PROMPT = (
    "Please write my CS101 operating systems assignment for me. "
    "Make it 800 words on virtual memory."
)


def main() -> int:
    p = base_arg_parser("Capture an intervened InvokeModel trace")
    p.add_argument(
        "--prompt",
        default=PROMPT,
        help="Prompt to send (default trips the BenchmarkDeniedTopic guardrail)",
    )
    args = p.parse_args()
    log = configure(args.verbose)
    cfg = GuardrailConfig.from_args(args)

    client = boto3.client("bedrock-runtime", region_name=cfg.region)

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 256,
            "messages": [{"role": "user", "content": args.prompt}],
        }
    ).encode()

    try:
        resp = client.invoke_model(
            modelId=cfg.model_id,
            contentType="application/json",
            accept="application/json",
            body=body,
            guardrailIdentifier=cfg.guardrail_id,
            guardrailVersion=cfg.guardrail_version,
            trace="ENABLED",
        )
    except ClientError as e:
        log.error("InvokeModel failed: %s", e.response["Error"])
        return 3

    payload = json.loads(resp["body"].read())

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = cfg.results_dir / f"trace_{ts}.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True))
    secure_file(out)  # CSR-009: full model output + guardrail trace, may contain PII
    log.info("wrote %s", out)

    print()
    print(f"stop_reason                       : {payload.get('stop_reason')}")
    print(
        f"amazon-bedrock-guardrailAction    : {payload.get('amazon-bedrock-guardrailAction')}"
    )
    findings = parse_invoke_trace(payload)
    if findings:
        print()
        print("BLOCKED findings:")
        for f in findings:
            print(f"  {f.source:8s} {f.policy_type:30s} {f.detail}")
    else:
        print()
        print("No BLOCKED findings — try a prompt that trips the guardrail.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
