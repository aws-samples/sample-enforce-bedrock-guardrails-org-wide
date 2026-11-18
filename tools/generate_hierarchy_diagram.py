"""
Generate the policy hierarchy diagram for the blog post.

Shows the AWS Organization structure deployed during the blog demonstration:
  Management Account
    ├── Bedrock Guardrails (L1 org policy + resource policy)
    ├── Organizations Policies (Bedrock + SCP)
    └── WorkloadOU  (<OU_ID>)
          └── Member Account  (<MEMBER_ACCOUNT_ID>)
                ├── Inherits: Bedrock Org Policy → guardrail auto-applied
                ├── Inherits: SCP → deny invoke without guardrail
                ├── Account-Level Config (L3) → strict guardrail
                └── Per-App Attachment (L4) → explicit guardrailIdentifier

Output: images/Bedrock-Guardrail-Hierarchy.png
Run:    .venv/bin/python tools/generate_hierarchy_diagram.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyArrowPatch

AWS_DARK   = "#232F3E"
AWS_ORANGE = "#FF9900"
MGMT_FILL  = "#EBF5FB"
MGMT_BORDER= "#1F3A5F"
OU_FILL    = "#F0FFF4"
OU_BORDER  = "#1B7A3E"
MEMBER_FILL= "#FFF9EC"
MEMBER_BORDER = "#B7770D"
POLICY_FILL= "#E8F0FE"
POLICY_BORDER = "#1F3A5F"
GUARDRAIL_FILL = "#FFF0E6"
GUARDRAIL_BORDER = "#C05000"
LABEL_DARK = "#1F1F1F"
INHERITED  = "#7D8CA3"


def _box(ax, x, y, w, h, title, sub=None, fill="#fff", border="#333",
         title_size=9.5, sub_size=8.0, title_color=None, bold=True):
    b = patches.FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.04",
        edgecolor=border, facecolor=fill, linewidth=1.3,
        zorder=3,
    )
    ax.add_patch(b)
    cx = x + w / 2
    ty = y + h * 0.62 if sub else y + h / 2
    ax.text(cx, ty, title,
            ha="center", va="center",
            fontsize=title_size, fontweight="bold" if bold else "normal",
            color=title_color or border, zorder=4)
    if sub:
        ax.text(cx, y + h * 0.25, sub,
                ha="center", va="center",
                fontsize=sub_size, color=LABEL_DARK, zorder=4,
                style="italic")


def _arrow(ax, x1, y1, x2, y2, color=AWS_DARK, style="->", lw=1.5, dashed=False):
    ls = "dashed" if dashed else "solid"
    ax.annotate("",
                xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color,
                                lw=lw, linestyle=ls),
                zorder=5)


def _label(ax, x, y, text, color=INHERITED, size=7.5, ha="left"):
    ax.text(x, y, text, ha=ha, va="center",
            fontsize=size, color=color, zorder=6,
            bbox=dict(boxstyle="round,pad=0.15", facecolor="white",
                      edgecolor="none", alpha=0.85))


def build_figure() -> plt.Figure:
    fig, ax = plt.subplots(figsize=(13, 8.5), dpi=200)
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 9.5)
    ax.axis("off")

    # ── Title ──────────────────────────────────────────────────────────
    ax.text(6.5, 9.1,
            "Policy & guardrail hierarchy — deployed org structure",
            ha="center", va="center",
            fontsize=13.5, fontweight="bold", color=AWS_DARK)

    # ── Management account plane ────────────────────────────────────────
    mgmt_plane = patches.FancyBboxPatch(
        (0.3, 4.8), 12.4, 3.8,
        boxstyle="round,pad=0.08",
        edgecolor=MGMT_BORDER, facecolor=MGMT_FILL, linewidth=1.8, zorder=1)
    ax.add_patch(mgmt_plane)
    ax.text(0.55, 8.38,
            "Management Account  •  Org ID: <ORG_ID>",
            fontsize=9.5, fontweight="bold", color=MGMT_BORDER)

    # Management account node
    _box(ax, 0.6, 7.0, 2.4, 1.0,
         "Management Account",
         sub="<MGMT_ACCOUNT_ID>",
         fill=MGMT_FILL, border=MGMT_BORDER, title_size=9.5)

    # ── Guardrails ──────────────────────────────────────────────────────
    _box(ax, 3.7, 7.15, 3.6, 0.7,
         "Org Baseline Guardrail  v1",
         sub="Content filters + BenchmarkDeniedTopic + PII",
         fill=GUARDRAIL_FILL, border=GUARDRAIL_BORDER, title_size=8.8)

    _box(ax, 7.8, 7.15, 3.6, 0.7,
         "Account Strict Guardrail  v3",
         sub="AcademicDishonesty + CompetitorMention",
         fill=GUARDRAIL_FILL, border=GUARDRAIL_BORDER, title_size=8.8)

    # ── Policies ────────────────────────────────────────────────────────
    _box(ax, 3.7, 5.6, 2.4, 1.0,
         "Bedrock Org Policy",
         sub="<BEDROCK_POLICY_ID>\nAuto-applies Org Baseline Guardrail",
         fill=POLICY_FILL, border=MGMT_BORDER, title_size=8.8)

    _box(ax, 6.5, 5.6, 2.4, 1.0,
         "Service Control Policy",
         sub="<SCP_POLICY_ID>\nDeny InvokeModel without GuardrailIdentifier",
         fill=POLICY_FILL, border=MGMT_BORDER, title_size=8.8)

    _box(ax, 9.3, 5.6, 2.4, 1.0,
         "Guardrail Resource Policy",
         sub="AllowOrgMembers\nbedrock:ApplyGuardrail",
         fill=POLICY_FILL, border=MGMT_BORDER, title_size=8.8)

    # Policy → Guardrail links
    _arrow(ax, 5.5, 6.6, 5.5, 7.15, color=MGMT_BORDER)
    _arrow(ax, 10.6, 6.6, 9.6, 7.15, color=MGMT_BORDER)

    # ── WorkloadOU plane ─────────────────────────────────────────────────
    ou_plane = patches.FancyBboxPatch(
        (0.3, 0.5), 12.4, 3.8,
        boxstyle="round,pad=0.08",
        edgecolor=OU_BORDER, facecolor=OU_FILL, linewidth=1.8, zorder=1)
    ax.add_patch(ou_plane)
    ax.text(0.55, 4.1,
            "WorkloadOU  •  <OU_ID>",
            fontsize=9.5, fontweight="bold", color=OU_BORDER)

    # OU node
    _box(ax, 0.6, 2.8, 2.4, 0.9,
         "WorkloadOU",
         sub="<OU_ID>",
         fill=OU_FILL, border=OU_BORDER, title_size=9.5)

    # Inherited policy badges
    _box(ax, 3.7, 3.4, 2.4, 0.75,
         "↓ Bedrock Org Policy",
         sub="inherited from mgmt",
         fill="#E8F8F0", border=OU_BORDER, title_size=8.0, bold=False)
    _box(ax, 6.5, 3.4, 2.4, 0.75,
         "↓ SCP",
         sub="inherited from mgmt",
         fill="#E8F8F0", border=OU_BORDER, title_size=8.0, bold=False)

    # ── Member account ───────────────────────────────────────────────────
    _box(ax, 3.5, 1.0, 5.6, 2.0,
         "Member Account  (<MEMBER_ACCOUNT_ID>)",
         fill=MEMBER_FILL, border=MEMBER_BORDER, title_size=10, title_color=MEMBER_BORDER)

    # Layers inside the member account
    layer_y = 1.15
    for i, (label, color) in enumerate([
        ("L1: Org Baseline Guardrail auto-applied via Bedrock Org Policy", OU_BORDER),
        ("L2: bedrock:InvokeModel denied if no GuardrailIdentifier  (SCP)", MGMT_BORDER),
        ("L3: Account-Level Config → blog-account-strict-guardrail v3", AWS_ORANGE),
        ("L4: Per-App Attachment → guardrailIdentifier on each call", "#6C3483"),
    ]):
        ax.text(3.75, layer_y + i * 0.32, f"  {label}",
                fontsize=7.8, color=color, va="center", zorder=6,
                fontweight="bold" if i == 2 else "normal")

    # ── Arrows: Mgmt → OU (policy inheritance) ──────────────────────────
    # Bedrock Org Policy down to OU
    _arrow(ax, 4.9, 5.6, 4.9, 4.15,
           color=OU_BORDER, lw=1.8, dashed=False)
    _label(ax, 5.0, 4.9, "attaches to OU", color=OU_BORDER, size=7.5)

    # SCP down to OU
    _arrow(ax, 7.7, 5.6, 6.8, 4.15,
           color=MGMT_BORDER, lw=1.8, dashed=False)
    _label(ax, 7.8, 4.9, "attaches to OU", color=MGMT_BORDER, size=7.5)

    # OU → member account inheritance arrows
    _arrow(ax, 4.9, 3.4, 5.0, 3.0,
           color=OU_BORDER, lw=1.5, dashed=True)
    _arrow(ax, 6.8, 3.4, 6.5, 3.0,
           color=MGMT_BORDER, lw=1.5, dashed=True)

    # Guardrail resource policy → member account (cross-account)
    _arrow(ax, 10.5, 5.6, 7.8, 3.0,
           color=GUARDRAIL_BORDER, lw=1.2, dashed=True)
    _label(ax, 9.5, 4.5, "cross-account\nApplyGuardrail", color=GUARDRAIL_BORDER, size=7.2)

    # Management account → OU tree line
    _arrow(ax, 1.8, 7.0, 1.8, 4.7,
           color=MGMT_BORDER, lw=1.5, style="-")
    _arrow(ax, 1.8, 4.7, 1.8, 3.7,
           color=OU_BORDER, lw=1.5, style="->")
    _label(ax, 1.85, 4.75, "org tree", color=INHERITED, size=7.2)

    # ── Legend ───────────────────────────────────────────────────────────
    legend_items = [
        (GUARDRAIL_BORDER, "Guardrail resource"),
        (MGMT_BORDER,      "Organizations policy"),
        (OU_BORDER,        "OU / inherited policy"),
        (MEMBER_BORDER,    "Member account"),
        (AWS_ORANGE,       "Account-level config (L3)"),
        ("#6C3483",        "Per-app attachment (L4)"),
    ]
    for i, (color, label) in enumerate(legend_items):
        lx = 0.4 + (i % 3) * 4.2
        ly = 0.22 - (i // 3) * 0.0
        ax.plot(lx, ly, "s", color=color, markersize=7, zorder=6)
        ax.text(lx + 0.18, ly, label,
                fontsize=7.5, va="center", color=LABEL_DARK, zorder=6)

    return fig


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "images" / "Bedrock-Guardrail-Hierarchy.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig = build_figure()
    fig.savefig(out, dpi=200, bbox_inches="tight")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
