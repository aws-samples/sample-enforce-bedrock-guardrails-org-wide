"""Shared configuration loader.

Resolution order: explicit argparse arg > environment variable > default.
Centralised here so each script doesn't reinvent the precedence.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .secure_io import secure_results_dir


DEFAULT_REGION = "us-east-1"
DEFAULT_MODEL = "anthropic.claude-3-haiku-20240307-v1:0"
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent.parent.parent / "results"


@dataclass
class GuardrailConfig:
    region: str
    model_id: str
    guardrail_id: str
    guardrail_version: str
    results_dir: Path

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "GuardrailConfig":
        gid = args.guardrail_id or os.environ.get("GUARDRAIL_ID")
        gver = args.guardrail_version or os.environ.get("GUARDRAIL_VERSION")
        if not gid or not gver:
            raise SystemExit(
                "ERROR: --guardrail-id and --guardrail-version (or GUARDRAIL_ID / "
                "GUARDRAIL_VERSION env vars) are required. They come from the CDK "
                "stack outputs."
            )
        results = Path(args.results_dir or os.environ.get("RESULTS_DIR", DEFAULT_RESULTS_DIR))
        secure_results_dir(results)  # CSR-009: owner-only (0700) results dir
        return cls(
            region=args.region or os.environ.get("AWS_REGION", DEFAULT_REGION),
            model_id=args.model_id or os.environ.get("MODEL_ID", DEFAULT_MODEL),
            guardrail_id=gid,
            guardrail_version=gver,
            results_dir=results,
        )


def base_arg_parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--guardrail-id", help="Bedrock guardrail id (or env GUARDRAIL_ID)")
    p.add_argument(
        "--guardrail-version",
        help="Numeric guardrail version (or env GUARDRAIL_VERSION). DRAFT is rejected by Bedrock.",
    )
    p.add_argument("--region", help=f"AWS region (default {DEFAULT_REGION})")
    p.add_argument("--model-id", help=f"Bedrock model id (default {DEFAULT_MODEL})")
    p.add_argument(
        "--results-dir",
        help=f"Output directory (default {DEFAULT_RESULTS_DIR})",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    return p
