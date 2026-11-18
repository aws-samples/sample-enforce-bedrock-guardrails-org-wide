#!/usr/bin/env python3
"""Reproduce four documented failure modes.

The blog's "What we hit during deployment" section quotes the exact error
codes and messages this script captures.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib.config import GuardrailConfig, base_arg_parser
from _lib.logging_setup import configure
from _lib.secure_io import secure_file


@dataclass
class Outcome:
    name: str
    expected: str
    actual_code: Optional[str]
    actual_message: Optional[str]
    raised: bool


def _body(prompt: str = "hi") -> bytes:
    return json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 8,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()


def f1_draft_guardrail(cfg: GuardrailConfig) -> Outcome:
    name = "F1: invoke with DRAFT guardrail"
    expected = "ValidationException — DRAFT not allowed for runtime invoke"
    client = boto3.client("bedrock-runtime", region_name=cfg.region)
    try:
        client.invoke_model(
            modelId=cfg.model_id,
            contentType="application/json",
            accept="application/json",
            body=_body(),
            guardrailIdentifier=cfg.guardrail_id,
            guardrailVersion="DRAFT",
        )
        return Outcome(name, expected, None, "no error raised", False)
    except ClientError as e:
        err = e.response["Error"]
        return Outcome(name, expected, err.get("Code"), err.get("Message"), True)


def f2_cross_region(cfg: GuardrailConfig, alt_region: str) -> Outcome:
    name = "F2: cross-region guardrail attach"
    expected = "ValidationException — guardrail region mismatch"
    client = boto3.client("bedrock-runtime", region_name=alt_region)
    try:
        client.invoke_model(
            modelId=cfg.model_id,
            contentType="application/json",
            accept="application/json",
            body=_body(),
            guardrailIdentifier=cfg.guardrail_id,
            guardrailVersion=cfg.guardrail_version,
        )
        return Outcome(name, expected, None, "no error raised", False)
    except ClientError as e:
        err = e.response["Error"]
        return Outcome(name, expected, err.get("Code"), err.get("Message"), True)


def f3_missing_version(cfg: GuardrailConfig) -> Outcome:
    name = "F3: guardrailIdentifier without guardrailVersion"
    expected = "ValidationException — guardrailVersion required"
    client = boto3.client("bedrock-runtime", region_name=cfg.region)
    try:
        client.invoke_model(
            modelId=cfg.model_id,
            contentType="application/json",
            accept="application/json",
            body=_body(),
            guardrailIdentifier=cfg.guardrail_id,
        )
        return Outcome(name, expected, None, "no error raised", False)
    except ClientError as e:
        err = e.response["Error"]
        return Outcome(name, expected, err.get("Code"), err.get("Message"), True)


def f4_nonexistent(cfg: GuardrailConfig) -> Outcome:
    name = "F4: ApplyGuardrail to non-existent id"
    expected = "ResourceNotFoundException"
    client = boto3.client("bedrock-runtime", region_name=cfg.region)
    try:
        client.apply_guardrail(
            guardrailIdentifier="nonexistent12345",
            guardrailVersion="1",
            source="INPUT",
            content=[{"text": {"text": "hello"}}],
        )
        return Outcome(name, expected, None, "no error raised", False)
    except ClientError as e:
        err = e.response["Error"]
        return Outcome(name, expected, err.get("Code"), err.get("Message"), True)


def main() -> int:
    p = base_arg_parser("Reproduce four documented failure modes")
    p.add_argument(
        "--alt-region",
        default=os.environ.get("ALT_REGION", "us-west-2"),
        help="Alternate region used for the cross-region failure test",
    )
    args = p.parse_args()
    log = configure(args.verbose)
    cfg = GuardrailConfig.from_args(args)

    outcomes = [
        f1_draft_guardrail(cfg),
        f2_cross_region(cfg, args.alt_region),
        f3_missing_version(cfg),
        f4_nonexistent(cfg),
    ]

    print()
    for o in outcomes:
        print(f"{o.name}")
        print(f"  expected   : {o.expected}")
        if o.raised:
            print(f"  error code : {o.actual_code}")
            first_line = (o.actual_message or "").splitlines()[0]
            print(f"  message    : {first_line}")
        else:
            print(f"  UNEXPECTED : {o.actual_message}")
        print()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = cfg.results_dir / f"failure_modes_{ts}.log"
    with out.open("w") as f:
        for o in outcomes:
            f.write(f"=== {o.name} ===\n")
            f.write(f"expected   : {o.expected}\n")
            f.write(f"raised     : {o.raised}\n")
            f.write(f"error code : {o.actual_code}\n")
            f.write(f"message    : {o.actual_message}\n\n")
    secure_file(out)  # CSR-009: error messages may echo back request content
    log.info("wrote %s", out)
    return 0 if all(o.raised for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
