"""
Generate a layout draft of the architecture diagram: images/architecture-draft.png

The canonical, published diagram is images/bedrock-guardrails-architecture-v2.svg,
hand-finished from this layout. Keep the labels here in step with the SVG.

The diagram shows only what this repository actually builds or documents:

  Management / delegated-admin account
    - CDK stack Blog-Benchmark-Guardrail  (CfnGuardrail + CfnGuardrailVersion,
      resource-based policy scoped to aws:PrincipalOrgID when AWS_ORG_ID is set)
    - CDK stack Blog-Benchmark-Dashboard  (CloudWatch dashboard + alarms)
    - CDK stack Blog-Benchmark-StackSet   (optional per-region replicas)
    - Layer 1: Bedrock Organizations policy (artifacts/bedrock-organizations-policy.json)
    - Layer 2: SCP backstop  — OPTIONAL, described in the blog, NOT shipped here
  Workload account(s)
    - Layer 3: account-level enforced configuration (scripts/*_account_enforcement.py)
    - Layer 4: per-app attachment (scripts/run_benchmark.py, capture_trace.py)
  Delivery & evidence
    - GitLab CI pipeline (.gitlab-ci.yml) with verify_deployment.py as release gate
    - CloudTrail + Logs Insights queries, CloudWatch metrics

Deliberately absent (not built by this repo): IAM Identity Center permission
sets, AWS Config rules, CodePipeline / GitHub Actions.

Run:
    .venv/bin/python tools/generate_architecture_diagram.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.patches as patches
import matplotlib.pyplot as plt

AWS_DARK = "#232F3E"
AWS_ORANGE = "#FF9900"
TEXT_DARK = "#1F1F1F"
PLANE_FILL = "#FAFBFC"
MGMT_BORDER = "#8C1D40"
WL_BORDER = "#1F6F43"
CI_BORDER = "#4A4A4A"
LAYER_FILL = "#E8F0FE"
LAYER_BORDER = "#1F3A5F"
OPT_FILL = "#FFFFFF"
OPT_BORDER = "#B03A2E"
RUNTIME_FILL = "#E8F8F0"
TOOL_FILL = "#F4F4F4"


def _plane(ax, x, y, w, h, title, border):
    ax.add_patch(patches.FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.06",
        edgecolor=border, facecolor=PLANE_FILL, linewidth=1.6))
    ax.text(x + 0.2, y + h - 0.28, title, fontsize=10, fontweight="bold", color=border)


def _box(ax, x, y, w, h, title, sub, *, fill=LAYER_FILL, border=LAYER_BORDER,
         dashed=False, title_size=9.2, sub_size=7.4, badge=None):
    ax.add_patch(patches.FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.04",
        edgecolor=border, facecolor=fill, linewidth=1.3,
        linestyle="--" if dashed else "-"))
    cx = x + w / 2
    n_sub = sub.count("\n") + 1
    ax.text(cx, y + h - 0.26, title, ha="center", va="center",
            fontsize=title_size, fontweight="bold", color=border)
    sub_y = (y + 0.22) if h < 1.0 else (y + h - 0.62 - 0.11 * n_sub)
    ax.text(cx, sub_y, sub, ha="center", va="center",
            fontsize=sub_size, color=TEXT_DARK, linespacing=1.35)
    if badge:
        # render as a small italic tag under the title rather than a corner badge
        ax.text(cx, y + h - 0.42, f"[{badge}]", ha="center", va="center",
                fontsize=6.4, style="italic", color=AWS_ORANGE)


def _arrow(ax, p0, p1, *, color=AWS_DARK, dashed=False, lw=1.4, label=None,
           label_dx=0.0, label_dy=0.12, rad=0.0):
    ax.annotate("", xy=p1, xytext=p0, arrowprops=dict(
        arrowstyle="->", color=color, lw=lw,
        linestyle="--" if dashed else "-",
        connectionstyle=f"arc3,rad={rad}"))
    if label:
        mx, my = (p0[0] + p1[0]) / 2 + label_dx, (p0[1] + p1[1]) / 2 + label_dy
        ax.text(mx, my, label, ha="center", va="center", fontsize=6.8,
                color=color, style="italic",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.9))


def build_figure() -> plt.Figure:
    fig, ax = plt.subplots(figsize=(16, 10), dpi=200)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)
    ax.axis("off")

    ax.text(8, 9.6, "Centralized Amazon Bedrock Guardrails — what this reference implementation builds",
            ha="center", va="center", fontsize=14, fontweight="bold", color=AWS_DARK)
    ax.text(8, 9.25, "Layers 1, 3 and 4 are deployed or scripted here. Layer 2 (SCP) is optional "
                     "and described in the blog post only — it is not shipped as code.",
            ha="center", va="center", fontsize=8.8, style="italic", color=AWS_DARK)

    # ── Management / delegated admin plane ──────────────────────────────
    _plane(ax, 0.3, 3.9, 7.6, 5.0, "Management or Delegated-Admin Account", MGMT_BORDER)

    _box(ax, 0.55, 6.9, 3.3, 1.55,
         "CDK  Blog-Benchmark-Guardrail",
         "AWS::Bedrock::Guardrail + GuardrailVersion\n"
         "content / topic / PII policies\n"
         "resource policy: ApplyGuardrail + GetGuardrail\n"
         "scoped to aws:PrincipalOrgID",
         fill=TOOL_FILL, border=MGMT_BORDER, badge="cdk-nag checked")

    _box(ax, 4.2, 6.9, 3.45, 1.55,
         "Layer 1 — Bedrock Organizations Policy",
         "type BEDROCK_POLICY, attached to the OU\n"
         "artifacts/bedrock-organizations-policy.json\n"
         "pins guardrail ARN + numeric version\n"
         "auto-applies to every invoke in the OU",
         badge="hardest to bypass")

    _box(ax, 0.55, 4.95, 3.3, 1.5,
         "CDK  Blog-Benchmark-Dashboard",
         "CloudWatch dashboard + alarms on\n"
         "AWS/Bedrock/Guardrails metrics\n"
         "(Invocations, InvocationsIntervened,\n"
         "latency, throttles, errors)",
         fill=TOOL_FILL, border=MGMT_BORDER)

    _box(ax, 4.2, 4.95, 3.45, 1.5,
         "Layer 2 — SCP backstop  (optional)",
         "Deny InvokeModel* / Converse* unless\n"
         "bedrock:GuardrailIdentifier is present\n"
         "NOT in this repository — example shown\n"
         "in the blog; author + review your own",
         fill=OPT_FILL, border=OPT_BORDER, dashed=True, badge="not shipped")

    _box(ax, 0.55, 4.05, 7.1, 0.7,
         "CDK  Blog-Benchmark-StackSet  (optional, CDK_DEPLOY_STACKSET=1)",
         "independent replica of the guardrail stack per target account / region — not a shared guardrail",
         fill=TOOL_FILL, border=MGMT_BORDER, title_size=8.4, sub_size=6.9)

    # ── Workload plane ───────────────────────────────────────────────────
    _plane(ax, 8.3, 3.9, 7.4, 5.0, "Workload Account(s) in the target OU", WL_BORDER)

    _box(ax, 8.55, 6.9, 3.3, 1.55,
         "Layer 3 — Account-level enforced config",
         "PutEnforcedGuardrailConfiguration\n"
         "scripts/set_ | get_ | delete_account_enforcement.py\n"
         "one configId per account + region\n"
         "evaluates every invoke, attached or not",
         badge="account-wide", title_size=8.6)

    _box(ax, 12.15, 6.9, 3.3, 1.55,
         "Layer 4 — Per-app attachment",
         "guardrailIdentifier + guardrailVersion\n"
         "on each InvokeModel / Converse call\n"
         "scripts/run_benchmark.py, capture_trace.py\n"
         "cross-account: full guardrail ARN + IAM grant",
         badge="most granular")

    _box(ax, 8.55, 4.95, 6.9, 1.5,
         "Amazon Bedrock Runtime — InvokeModel · InvokeModelWithResponseStream · Converse · ConverseStream",
         "evaluates every applicable guardrail (org-enforced, account-enforced, request-supplied) on the same call\n"
         "assessments are unioned; any BLOCKED finding → amazon-bedrock-guardrailAction = INTERVENED, model never runs",
         fill=RUNTIME_FILL, border=WL_BORDER, title_size=7.2, sub_size=7.0)

    _box(ax, 8.55, 4.05, 6.9, 0.7,
         "GenAI application / test harness",
         "any principal with bedrock:InvokeModel — the benchmark and verify scripts play this role here",
         fill=TOOL_FILL, border=WL_BORDER, title_size=8.4, sub_size=6.9)

    # ── Delivery & evidence plane ────────────────────────────────────────
    _plane(ax, 0.3, 0.35, 15.4, 3.2, "Delivery and evidence (all in this repository)", CI_BORDER)

    _box(ax, 0.55, 1.65, 4.7, 1.55,
         "GitLab CI  (.gitlab-ci.yml)",
         "lint → synth (cdk-nag) → deploy-dev → verify-dev\n"
         "→ deploy-prod (manual) → verify-prod\n"
         "static CI credentials = sandbox only;\n"
         "OIDC .aws-oidc template provided",
         fill=TOOL_FILL, border=CI_BORDER)

    _box(ax, 5.55, 1.65, 4.9, 1.55,
         "Release gate  scripts/verify_deployment.py",
         "p99 latency budget on benign prompts\n"
         "known-bad prompt → INTERVENED, and the BLOCKED\n"
         "assessment is attributed to the deployed guardrail\n"
         "DRAFT-version behaviour (standalone vs org policy)",
         fill=TOOL_FILL, border=CI_BORDER, badge="fails closed")

    _box(ax, 10.75, 1.65, 4.7, 1.55,
         "CloudTrail + Logs Insights  (queries/)",
         "Invoke* / Converse* = management events\n"
         "ApplyGuardrail = data event (AWS::Bedrock::Guardrail)\n"
         "— off by default, enable on the trail\n"
         "eventSource bedrock.amazonaws.com",
         fill=TOOL_FILL, border=CI_BORDER)

    _box(ax, 0.55, 0.5, 14.9, 0.95,
         "Measurement scripts  —  run_benchmark.py · capture_trace.py · reproduce_failure_modes.py · "
         "verify_effective_policy.py · generate_chart.py",
         "results/ is chmod 0700 / files 0600 (may contain prompts and PII detections) — treat as sensitive",
         fill=TOOL_FILL, border=CI_BORDER, title_size=8.4, sub_size=7.0)

    # ── Arrows ───────────────────────────────────────────────────────────
    # CDK guardrail → org policy references it
    _arrow(ax, (3.85, 7.65), (4.2, 7.65), color=MGMT_BORDER, label="referenced by", label_dy=-0.9)
    # Org policy → workload runtime (auto-applies)
    _arrow(ax, (7.65, 7.1), (8.55, 6.3), color=LAYER_BORDER, lw=2.0,
           label="auto-applies to every invoke", label_dx=-0.25, label_dy=-0.35)
    # SCP (optional) → runtime, dashed
    _arrow(ax, (7.65, 5.1), (8.55, 5.3), color=OPT_BORDER, dashed=True,
           label="if adopted: deny before Bedrock", label_dx=0.0, label_dy=-0.3)
    # L3 → runtime, L4 → runtime
    _arrow(ax, (10.2, 6.9), (10.2, 6.45), color=LAYER_BORDER)
    _arrow(ax, (13.8, 6.9), (13.8, 6.45), color=LAYER_BORDER)
    # App → runtime
    _arrow(ax, (12.0, 4.75), (12.0, 4.95), color=WL_BORDER)
    # GitLab CI → CDK (deploys)
    _arrow(ax, (2.9, 3.2), (2.2, 4.05), color=CI_BORDER, label="cdk deploy", label_dx=0.55, label_dy=0.0)
    # verify → runtime
    _arrow(ax, (8.0, 3.2), (9.6, 4.05), color=CI_BORDER, label="invokes with trace=ENABLED",
           label_dx=0.2, label_dy=-0.15)
    # runtime → CloudTrail
    _arrow(ax, (13.1, 4.05), (13.1, 3.2), color=CI_BORDER, dashed=True,
           label="events", label_dx=0.35, label_dy=0.0)

    # Footer legend
    ax.text(8, 0.08,
            "Solid = built or scripted here.  Dashed red = optional authorization control described in the blog, "
            "not shipped.  Not depicted because not built: IAM Identity Center, AWS Config, CodePipeline.",
            ha="center", va="bottom", fontsize=7.6, style="italic", color=AWS_DARK)
    return fig


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    out = root / "images" / "architecture-draft.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig = build_figure()
    fig.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
