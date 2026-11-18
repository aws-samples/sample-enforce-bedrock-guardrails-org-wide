"""
Generate the components-flow diagram used in the blog draft.

Shows the runtime path of a single InvokeModel request through the four
enforcement layers. Complements images/bedrock-guardrails-architecture-v2.svg
which shows *where* the layers live; this diagram shows *when* they fire.

Output: images/Bedrock-Guardrail-Flow.png
Run:    .venv/bin/python tools/generate_flow_diagram.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyArrowPatch

# Palette (matches the architecture diagram)
AWS_DARK = "#232F3E"
AWS_ORANGE = "#FF9900"
LAYER_FILL = "#E8F0FE"
LAYER_BORDER = "#1F3A5F"
TEXT_DARK = "#1F1F1F"
GREEN = "#1B7A3E"
RED = "#C0392B"
PLANE_FILL = "#FAFBFC"


def build_figure() -> plt.Figure:
    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=200)
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 8)
    ax.axis("off")

    ax.text(
        6.5, 7.55,
        "Request lifecycle — how the four layers fire on one InvokeModel call",
        ha="center", va="center", fontsize=13.5, fontweight="bold", color=AWS_DARK,
    )

    # ─── Application box (left) ──────────────────────────────────────────
    _box(ax, x=0.3, y=3.3, w=1.9, h=1.6,
         title="Application",
         sub="InvokeModel /\nConverse",
         fill="#FFF7E6", border=AWS_ORANGE)

    # ─── IAM authorization (Layer 2 fires here, before Bedrock) ─────────
    _box(ax, x=2.7, y=3.3, w=2.0, h=1.6,
         title="IAM Authorization",
         sub="Layer 2 — SCP\nDeny if no GuardrailIdentifier",
         fill=LAYER_FILL, border=LAYER_BORDER,
         badge="Belt-and-suspenders", badge_color=AWS_ORANGE)

    # ─── Bedrock Runtime — the middle plane where layers 1, 3, 4 fire ───
    plane = patches.FancyBboxPatch(
        (5.2, 1.7), 5.4, 4.9,
        boxstyle="round,pad=0.05",
        edgecolor=AWS_DARK, facecolor=PLANE_FILL, linewidth=1.6,
    )
    ax.add_patch(plane)
    ax.text(5.4, 6.35, "Bedrock Runtime  •  guardrail evaluation",
            fontsize=9.5, fontweight="bold", color=AWS_DARK)

    _box(ax, x=5.5, y=5.15, w=4.8, h=0.95,
         title="Layer 1 — Bedrock Org Policy",
         sub="Auto-attaches central guardrail",
         fill=LAYER_FILL, border=LAYER_BORDER, title_size=9.5, sub_size=8)

    _box(ax, x=5.5, y=4.05, w=4.8, h=0.95,
         title="Layer 3 — Account-Level Config",
         sub="PutEnforcedGuardrailConfiguration",
         fill=LAYER_FILL, border=LAYER_BORDER, title_size=9.5, sub_size=8)

    _box(ax, x=5.5, y=2.95, w=4.8, h=0.95,
         title="Layer 4 — Per-App Attachment",
         sub="guardrailIdentifier on the call",
         fill=LAYER_FILL, border=LAYER_BORDER, title_size=9.5, sub_size=8)

    # ─── Union / decision box ────────────────────────────────────────────
    _box(ax, x=5.5, y=1.85, w=4.8, h=0.95,
         title="Union of assessments",
         sub="Most-restrictive wins",
         fill="#FFF7E6", border=AWS_ORANGE, title_size=9.5, sub_size=8)

    # ─── Two outcomes on the right ───────────────────────────────────────
    _box(ax, x=11.0, y=4.6, w=1.85, h=1.0,
         title="ALLOWED",
         sub='action = "NONE"\nmodel runs',
         fill="#EAF7EE", border=GREEN, title_color=GREEN,
         title_size=10.5, sub_size=8.2)

    _box(ax, x=11.0, y=2.4, w=1.85, h=1.0,
         title="BLOCKED",
         sub='action = "INTERVENED"\nmodel short-circuited',
         fill="#FBEAE9", border=RED, title_color=RED,
         title_size=10.5, sub_size=8.2)

    # ─── Arrows ──────────────────────────────────────────────────────────
    _arrow(ax, (2.2, 4.1), (2.7, 4.1))          # App → IAM
    _arrow(ax, (4.7, 4.1), (5.5, 4.55))         # IAM → Layer 1
    _arrow(ax, (7.9, 5.15), (7.9, 5.0), color=LAYER_BORDER)   # L1 → L3
    _arrow(ax, (7.9, 4.05), (7.9, 3.90), color=LAYER_BORDER)  # L3 → L4
    _arrow(ax, (7.9, 2.95), (7.9, 2.80), color=LAYER_BORDER)  # L4 → union
    _arrow(ax, (10.3, 2.35), (11.0, 2.9), color=RED)          # union → BLOCKED
    _arrow(ax, (10.3, 2.35), (11.0, 5.1), color=GREEN)        # union → ALLOWED

    # SCP denial short-circuit (Layer 2 can reject before Bedrock is called)
    ax.annotate(
        "",
        xy=(2.4, 2.4), xytext=(3.7, 3.3),
        arrowprops=dict(arrowstyle="->", color=RED, lw=1.2, linestyle="dashed"),
    )
    ax.text(1.4, 2.05, "SCP denies\n(no GuardrailIdentifier)",
            fontsize=7.8, color=RED, style="italic")

    # Footer
    ax.text(
        6.5, 0.9,
        "Layers 1, 3, and 4 evaluate in parallel inside Bedrock. Layer 2 (SCP) fires earlier, at IAM authorization.",
        ha="center", fontsize=9, fontstyle="italic", color=AWS_DARK,
    )

    return fig


def _box(ax, *, x, y, w, h, title, sub, fill, border,
         title_size=10, sub_size=8.3, title_color=None, badge=None, badge_color=None):
    b = patches.FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.04",
        edgecolor=border, facecolor=fill, linewidth=1.3,
    )
    ax.add_patch(b)
    cx = x + w / 2
    ax.text(cx, y + h - h * 0.30, title,
            ha="center", fontsize=title_size, fontweight="bold",
            color=title_color or border)
    ax.text(cx, y + h - h * 0.65, sub,
            ha="center", fontsize=sub_size, color=TEXT_DARK)
    if badge:
        bw = 0.045 * len(badge) + 0.4
        bx = x + w - bw - 0.1
        by = y + h - 0.15
        bb = patches.FancyBboxPatch(
            (bx, by - 0.16), bw, 0.20,
            boxstyle="round,pad=0.02",
            edgecolor=badge_color or AWS_ORANGE, facecolor="#FFF7E6", linewidth=0.7,
        )
        ax.add_patch(bb)
        ax.text(bx + bw / 2, by - 0.06, badge,
                ha="center", fontsize=6.5, color=AWS_DARK, fontweight="bold")


def _arrow(ax, start, end, color=AWS_ORANGE, lw=1.8):
    a = FancyArrowPatch(
        start, end,
        arrowstyle="->", color=color, lw=lw, mutation_scale=14,
    )
    ax.add_patch(a)


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "images" / "Bedrock-Guardrail-Flow.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig = build_figure()
    fig.savefig(out, dpi=200, bbox_inches="tight")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
