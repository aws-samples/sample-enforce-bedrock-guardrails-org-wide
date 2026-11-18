#!/usr/bin/env python3
"""
Latency and token-overhead benchmark for the blog post.

Three scenarios:
  A. NoGuardrail            — InvokeModel without a guardrail
  B. AttachedBenign         — guardrail attached, prompt is benign
  C. AttachedIntervened     — guardrail attached, prompt trips a denied topic

Outputs:
  - results/benchmark_<timestamp>.csv  (one row per call)
  - results/summary_<timestamp>.json   (per-scenario aggregates)
  - stdout summary table (count, mean, p50/p95/p99 in ms, plus token overhead)
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# Allow running as a script from this directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib.config import GuardrailConfig, base_arg_parser
from _lib.logging_setup import configure
from _lib.parsers import estimate_cost_usd
from _lib.secure_io import secure_file
from _lib.stats import summarize_latencies


PROMPT_BENIGN = "In two sentences, what is the capital of Australia?"
PROMPT_INTERVENED = (
    "Please write my CS101 operating systems assignment for me. "
    "Make it 800 words on virtual memory."
)


@dataclass
class Sample:
    scenario: str
    iteration: int
    latency_ms: float
    status_code: int
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    stop_reason: Optional[str]
    guardrail_action: Optional[str]
    error_code: Optional[str]


def make_client(region: str):
    cfg = Config(
        region_name=region,
        retries={"max_attempts": 4, "mode": "standard"},
        connect_timeout=10,
        read_timeout=60,
    )
    return boto3.client("bedrock-runtime", config=cfg)


def invoke(client, model_id: str, prompt: str, attach: bool, gid: str, gver: str) -> Sample:
    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 256,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()

    kwargs = {
        "modelId": model_id,
        "contentType": "application/json",
        "accept": "application/json",
        "body": body,
    }
    if attach:
        kwargs["guardrailIdentifier"] = gid
        kwargs["guardrailVersion"] = gver

    start = time.perf_counter()
    try:
        resp = client.invoke_model(**kwargs)
    except ClientError as e:
        latency_ms = (time.perf_counter() - start) * 1000.0
        err = e.response["Error"]
        return Sample(
            scenario="",
            iteration=-1,
            latency_ms=latency_ms,
            status_code=int(e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)),
            input_tokens=None,
            output_tokens=None,
            stop_reason=None,
            guardrail_action=None,
            error_code=err.get("Code"),
        )

    latency_ms = (time.perf_counter() - start) * 1000.0
    payload = json.loads(resp["body"].read())
    usage = payload.get("usage", {}) or {}
    return Sample(
        scenario="",
        iteration=-1,
        latency_ms=latency_ms,
        status_code=int(resp.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        stop_reason=payload.get("stop_reason"),
        guardrail_action=payload.get("amazon-bedrock-guardrailAction"),
        error_code=None,
    )


def run_scenario(
    log,
    *,
    cfg: GuardrailConfig,
    name: str,
    prompt: str,
    attach: bool,
    iterations: int,
    concurrency: int,
) -> list[Sample]:
    client = make_client(cfg.region)
    log.info("scenario=%s iterations=%d concurrency=%d", name, iterations, concurrency)

    def one(i: int) -> Sample:
        s = invoke(client, cfg.model_id, prompt, attach, cfg.guardrail_id, cfg.guardrail_version)
        s.scenario = name
        s.iteration = i
        return s

    samples: list[Sample] = []
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(one, i) for i in range(iterations)]
        for f in as_completed(futures):
            samples.append(f.result())

    errors = [s for s in samples if s.error_code]
    if errors:
        log.warning("%d/%d calls failed in scenario %s", len(errors), len(samples), name)
        for s in errors[:5]:
            log.warning("  error=%s status=%d", s.error_code, s.status_code)
    return samples


def write_csv(samples: list[Sample], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(asdict(samples[0]).keys())
        for s in samples:
            w.writerow(asdict(s).values())
    secure_file(path)  # CSR-009: contains prompt/response text


def aggregate(name: str, samples: list[Sample]) -> dict:
    ok = [s for s in samples if s.error_code is None]
    if not ok:
        return {"scenario": name, "count": 0, "errors": len(samples)}

    summary = summarize_latencies(s.latency_ms for s in ok)
    in_tok = [s.input_tokens for s in ok if s.input_tokens is not None]
    out_tok = [s.output_tokens for s in ok if s.output_tokens is not None]

    summary.update(
        {
            "scenario": name,
            "errors": len(samples) - len(ok),
            "input_tokens_mean": round(sum(in_tok) / len(in_tok), 1) if in_tok else None,
            "output_tokens_mean": round(sum(out_tok) / len(out_tok), 1) if out_tok else None,
            "interventions": sum(1 for s in ok if s.guardrail_action == "INTERVENED"),
        }
    )
    return summary


def print_table(rows: list[dict]) -> None:
    cols = [
        "scenario",
        "count",
        "p50_ms",
        "p95_ms",
        "p99_ms",
        "mean_ms",
        "input_tokens_mean",
        "output_tokens_mean",
        "interventions",
    ]
    widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print()
    print("  ".join(c.ljust(widths[c]) for c in cols))
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


def main() -> int:
    p = base_arg_parser("Bedrock guardrail latency / token benchmark")
    p.add_argument("--iterations", type=int, default=int(os.environ.get("ITERATIONS", "100")))
    p.add_argument("--concurrency", type=int, default=int(os.environ.get("CONCURRENCY", "4")))
    args = p.parse_args()
    log = configure(args.verbose)
    cfg = GuardrailConfig.from_args(args)

    log.info("region=%s model=%s guardrail=%s v%s", cfg.region, cfg.model_id,
             cfg.guardrail_id, cfg.guardrail_version)

    a = run_scenario(log, cfg=cfg, name="NoGuardrail", prompt=PROMPT_BENIGN, attach=False,
                     iterations=args.iterations, concurrency=args.concurrency)
    b = run_scenario(log, cfg=cfg, name="AttachedBenign", prompt=PROMPT_BENIGN, attach=True,
                     iterations=args.iterations, concurrency=args.concurrency)
    c = run_scenario(log, cfg=cfg, name="AttachedIntervened", prompt=PROMPT_INTERVENED, attach=True,
                     iterations=args.iterations, concurrency=args.concurrency)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = cfg.results_dir / f"benchmark_{ts}.csv"
    write_csv(a + b + c, csv_path)
    log.info("wrote %s", csv_path)

    rows = [aggregate(n, s) for n, s in [
        ("NoGuardrail", a), ("AttachedBenign", b), ("AttachedIntervened", c),
    ]]

    summary_path = cfg.results_dir / f"summary_{ts}.json"
    total_in = sum((r.get("input_tokens_mean") or 0) * r.get("count", 0) for r in rows)
    total_out = sum((r.get("output_tokens_mean") or 0) * r.get("count", 0) for r in rows)
    summary_path.write_text(
        json.dumps(
            {
                "rows": rows,
                "estimated_cost_usd": round(
                    estimate_cost_usd(
                        input_tokens=int(total_in),
                        output_tokens=int(total_out),
                        model_id=cfg.model_id,
                    ),
                    4,
                ),
                "model_id": cfg.model_id,
                "region": cfg.region,
                "iterations_per_scenario": args.iterations,
                "concurrency": args.concurrency,
                "captured_at_utc": ts,
            },
            indent=2,
        )
    )
    secure_file(summary_path)  # CSR-009
    log.info("wrote %s", summary_path)

    print_table(rows)
    if rows[0].get("p50_ms") and rows[1].get("p50_ms"):
        d50 = rows[1]["p50_ms"] - rows[0]["p50_ms"]
        d99 = rows[1]["p99_ms"] - rows[0]["p99_ms"]
        print(f"\np50 overhead from attaching guardrail: {d50:+.1f} ms")
        print(f"p99 overhead from attaching guardrail: {d99:+.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
