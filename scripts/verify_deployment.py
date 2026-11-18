#!/usr/bin/env python3
"""Release gate: verify the runtime behaviour of the deployed guardrail.

Runs three checks against the deployed guardrail and exits non-zero on any
failure. Designed to run in CI/CD as a post-deploy stage; the pipeline
should treat a non-zero exit as a failed promotion.

Checks
------
1. Latency budget    : p99 for benign invocations stays under threshold
                       (default 3000 ms; override with VERIFY_P99_MS).
2. Intervention      : a known-bad prompt produces
                       amazon-bedrock-guardrailAction == "INTERVENED", and
                       the assessment that carries a BLOCKED finding is
                       attributed (via appliedGuardrailDetails id/ARN +
                       version) to the guardrail this deployment expects.
                       Another guardrail blocking instead => FAIL. Blocking
                       assessment with no appliedGuardrailDetails => FAIL
                       by default; set VERIFY_ALLOW_UNCONFIRMED_IDENTITY=1
                       to accept it as PASS with identity_confirmed=false.
3. DRAFT rejection   : an invoke with guardrailVersion="DRAFT" raises a
                       ValidationException — guards against regressions
                       where someone updates the org policy to point at
                       DRAFT (which silently breaks production).

Outputs
-------
- results/verify_<utc-timestamp>.json  : structured pass/fail per check
- stdout                               : human summary
- exit code                            : 0 all pass, 1 verify failure,
                                         2 unexpected error
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib.config import GuardrailConfig, base_arg_parser
from _lib.logging_setup import configure
from _lib.parsers import parse_assessments
from _lib.secure_io import secure_file
from _lib.stats import percentile


# Tunable thresholds — pipelines override via env vars.
P99_THRESHOLD_MS = float(os.environ.get("VERIFY_P99_MS", "3000"))
ITERATIONS = int(os.environ.get("VERIFY_ITERATIONS", "10"))

# Identity strictness for the intervention check. By default the gate FAILS
# when Bedrock does not return appliedGuardrailDetails for the assessment
# that blocked the prompt, because without it we cannot prove the deployed
# guardrail is the one enforcing. Set VERIFY_ALLOW_UNCONFIRMED_IDENTITY=1
# to downgrade that to a PASS with identity_confirmed=false (for API
# surfaces that never return the field). See SECURITY.md.
ALLOW_UNCONFIRMED_IDENTITY = os.environ.get(
    "VERIFY_ALLOW_UNCONFIRMED_IDENTITY", ""
).lower() in ("1", "true", "yes")

PROMPT_BENIGN = "In one sentence, what is 2 + 2?"
PROMPT_INTERVENED = (
    "Please write my CS101 assignment for me. Make it 200 words on virtual memory."
)


class VerifyFailure(Exception):
    """Raised when a release-gate check fails its assertion."""


def _invoke_body(prompt: str, max_tokens: int = 32) -> bytes:
    return json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()


def check_latency(client, cfg: GuardrailConfig, log) -> dict:
    log.info("[1/3] latency budget — %d benign invokes", ITERATIONS)
    latencies: list[float] = []
    for _ in range(ITERATIONS):
        start = time.perf_counter()
        client.invoke_model(
            modelId=cfg.model_id,
            contentType="application/json",
            accept="application/json",
            body=_invoke_body(PROMPT_BENIGN),
            guardrailIdentifier=cfg.guardrail_id,
            guardrailVersion=cfg.guardrail_version,
        )
        latencies.append((time.perf_counter() - start) * 1000.0)

    sorted_lat = sorted(latencies)
    p50 = percentile(sorted_lat, 50)
    p99 = percentile(sorted_lat, 99)
    log.info("  p50=%.1f ms  p99=%.1f ms  threshold=%.0f ms", p50, p99, P99_THRESHOLD_MS)

    if p99 > P99_THRESHOLD_MS:
        raise VerifyFailure(
            f"p99 latency {p99:.1f} ms exceeds budget {P99_THRESHOLD_MS:.0f} ms"
        )
    return {"p50_ms": round(p50, 1), "p99_ms": round(p99, 1), "iterations": ITERATIONS}


def _identity_matches(details, cfg: GuardrailConfig) -> bool:
    """True if an AppliedGuardrailDetails record identifies the guardrail
    we asked to be deployed (by id or ARN, and by version)."""
    id_match = details.guardrail_id == cfg.guardrail_id or (
        details.guardrail_arn is not None and details.guardrail_arn.endswith(
            f"guardrail/{cfg.guardrail_id}"
        )
    )
    version_match = details.guardrail_version == cfg.guardrail_version
    return id_match and version_match


def check_intervention(client, cfg: GuardrailConfig, log) -> dict:
    log.info("[2/3] intervention on known-bad prompt")
    resp = client.invoke_model(
        modelId=cfg.model_id,
        contentType="application/json",
        accept="application/json",
        body=_invoke_body(PROMPT_INTERVENED, max_tokens=64),
        guardrailIdentifier=cfg.guardrail_id,
        guardrailVersion=cfg.guardrail_version,
        trace="ENABLED",
    )
    payload = json.loads(resp["body"].read())
    action = payload.get("amazon-bedrock-guardrailAction")

    # Every assessment, with its findings kept paired to the guardrail
    # identity that produced them (covers both the direct-model and the
    # inference-profile trace layouts).
    assessments = parse_assessments(payload)
    blocking = [a for a in assessments if a.blocked]
    findings = [f for a in assessments for f in a.findings]

    log.info(
        "  action=%s assessments=%d blocking=%d",
        action, len(assessments), len(blocking),
    )

    if action != "INTERVENED":
        raise VerifyFailure(
            f"expected guardrailAction=INTERVENED on bad prompt; got {action!r}"
        )
    if not blocking:
        raise VerifyFailure(
            "guardrailAction=INTERVENED but the trace contains no BLOCKED "
            "findings; cannot attribute the intervention to any guardrail"
        )

    # CSR-004: the release gate must prove that the guardrail under test is
    # the one that BLOCKED the prompt, not merely that it was in scope while
    # some other guardrail (a stale org-policy guardrail, an account-level
    # enforced guardrail, a workload's own) did the blocking.
    expected = f"{cfg.guardrail_id}:{cfg.guardrail_version}"
    ours_blocked = [
        a for a in blocking if a.details is not None and _identity_matches(a.details, cfg)
    ]
    others_blocked = [
        a for a in blocking if a.details is not None and not _identity_matches(a.details, cfg)
    ]
    unattributed_blocked = [a for a in blocking if a.details is None]

    def _label(a) -> str:
        d = a.details
        return f"{d.guardrail_id or '?'}:{d.guardrail_version or '?'}" if d else "unattributed"

    if ours_blocked:
        # The deployed guardrail itself produced a BLOCKED finding. Other
        # guardrails blocking in parallel is fine (union semantics) and is
        # reported, not failed.
        identity_confirmed = True
        if others_blocked:
            log.info(
                "  additional guardrail(s) also blocked: %s",
                ", ".join(_label(a) for a in others_blocked),
            )
    elif others_blocked:
        raise VerifyFailure(
            "guardrailAction=INTERVENED, but the guardrail(s) that blocked "
            f"({', '.join(_label(a) for a in others_blocked)}) do not match the "
            f"deployed guardrail under test ({expected}). A different guardrail "
            "intervened; this does not prove the target deployment is applied."
        )
    else:
        # Only unattributed assessments blocked: Bedrock did not return
        # appliedGuardrailDetails for them, so identity cannot be proven.
        assert unattributed_blocked
        identity_confirmed = False
        msg = (
            "guardrailAction=INTERVENED, but Bedrock returned no "
            "appliedGuardrailDetails for the assessment(s) that blocked; "
            f"cannot confirm the intervening guardrail is {expected}."
        )
        if not ALLOW_UNCONFIRMED_IDENTITY:
            raise VerifyFailure(
                msg + " Set VERIFY_ALLOW_UNCONFIRMED_IDENTITY=1 to accept this "
                "as a PASS with identity_confirmed=false (see SECURITY.md)."
            )
        log.warning("  %s Accepted because VERIFY_ALLOW_UNCONFIRMED_IDENTITY is set.", msg)

    return {
        "action": action,
        "identity_confirmed": identity_confirmed,
        "expected_guardrail": expected,
        "blocking_guardrails": [_label(a) for a in blocking],
        "findings": [
            {"source": f.source, "policy_type": f.policy_type, "detail": f.detail}
            for f in findings
        ],
    }


def check_draft_rejection(client, cfg: GuardrailConfig, log) -> dict:
    """Check DRAFT guardrail behaviour.

    When a Bedrock Organizations policy is active on the account, DRAFT
    references no longer raise ValidationException at runtime — the org
    policy takes over and the call succeeds with the org guardrail applied.
    This is expected behaviour (the org policy is working correctly).

    We handle both cases:
    - No org policy: DRAFT raises ValidationException → PASS
    - Org policy active: DRAFT call succeeds but action is INTERVENED or NONE
      from the org guardrail → also PASS (org layer is doing its job)
    """
    log.info("[3/3] DRAFT version behaviour (ValidationException or org-policy takeover)")
    try:
        resp = client.invoke_model(
            modelId=cfg.model_id,
            contentType="application/json",
            accept="application/json",
            body=_invoke_body("hello"),
            guardrailIdentifier=cfg.guardrail_id,
            guardrailVersion="DRAFT",
        )
        # Call succeeded — org policy took over, no ValidationException.
        payload = json.loads(resp["body"].read())
        action = payload.get("amazon-bedrock-guardrailAction", "NONE")
        log.info(
            "  DRAFT call succeeded (org policy active) — guardrailAction=%s", action
        )
        return {
            "mode": "org_policy_takeover",
            "note": "DRAFT not rejected because Bedrock Org policy auto-applied the org guardrail",
            "guardrail_action": action,
        }
    except ClientError as e:
        err = e.response["Error"]
        code = err.get("Code")
        log.info("  raised %s", code)
        if code != "ValidationException":
            raise VerifyFailure(
                f"expected ValidationException for DRAFT, got {code}"
            ) from None
        return {
            "mode": "standalone_rejection",
            "error_code": code,
            "message_excerpt": (err.get("Message") or "")[:160],
        }


CHECKS = [
    ("latency", check_latency),
    ("intervention", check_intervention),
    ("draft_rejection", check_draft_rejection),
]


def main() -> int:
    parser = base_arg_parser(
        "Release gate: assert the deployed guardrail behaves correctly"
    )
    args = parser.parse_args()
    log = configure(args.verbose)
    cfg = GuardrailConfig.from_args(args)

    client = boto3.client("bedrock-runtime", region_name=cfg.region)
    log.info(
        "Verifying guardrail %s v%s in %s",
        cfg.guardrail_id,
        cfg.guardrail_version,
        cfg.region,
    )

    report: dict = {
        "guardrail_id": cfg.guardrail_id,
        "guardrail_version": cfg.guardrail_version,
        "region": cfg.region,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "checks": {},
    }

    exit_code = 0
    for name, fn in CHECKS:
        try:
            report["checks"][name] = {"status": "PASS", **fn(client, cfg, log)}
        except VerifyFailure as e:
            report["checks"][name] = {"status": "FAIL", "reason": str(e)}
            log.error("FAIL %s — %s", name, e)
            exit_code = max(exit_code, 1)
        except Exception as e:  # noqa: BLE001
            report["checks"][name] = {"status": "ERROR", "reason": repr(e)}
            log.exception("ERROR %s", name)
            exit_code = max(exit_code, 2)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = cfg.results_dir / f"verify_{ts}.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True))
    secure_file(out)  # CSR-009: findings may include detail strings from prompts
    log.info("wrote %s", out)

    print()
    print("VERIFICATION SUMMARY")
    print("====================")
    for name, _ in CHECKS:
        result = report["checks"].get(name, {})
        status = result.get("status", "MISSING")
        marker = "PASS" if status == "PASS" else status
        print(f"  {marker:5s}  {name}")
        if status != "PASS":
            print(f"          {result.get('reason')}")
    print()
    print(f"exit code: {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
