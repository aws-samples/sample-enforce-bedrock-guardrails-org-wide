#!/usr/bin/env python3
"""Generate the latency-distribution chart used in the blog post.

Reads the most recent benchmark CSV in the results directory and produces
a PNG histogram + KDE per scenario. Writes alongside the CSV.

Optional dependency: matplotlib (pinned in requirements-dev.txt).
Install via:  make install
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def find_latest_csv(results_dir: Path) -> Path:
    csvs = sorted(results_dir.glob("benchmark_*.csv"))
    if not csvs:
        raise FileNotFoundError(f"No benchmark_*.csv in {results_dir}")
    return csvs[-1]


def load(csv_path: Path) -> dict[str, list[float]]:
    by_scenario: dict[str, list[float]] = defaultdict(list)
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("error_code"):
                continue
            try:
                lat = float(row["latency_ms"])
            except (TypeError, ValueError):
                continue
            by_scenario[row["scenario"]].append(lat)
    return dict(by_scenario)


def render(by_scenario: dict[str, list[float]], out_path: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        print(
            "matplotlib not installed. Run: make install (installs requirements-dev.lock)",
            file=sys.stderr,
        )
        sys.exit(2)

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=200)
    colors = {
        "NoGuardrail": "#1F3A5F",
        "AttachedBenign": "#FF9900",
        "AttachedIntervened": "#1B7A3E",
    }
    for name, latencies in by_scenario.items():
        if not latencies:
            continue
        ax.hist(
            latencies,
            bins=30,
            histtype="step",
            linewidth=2,
            color=colors.get(name, "gray"),
            label=f"{name} (n={len(latencies)})",
        )

    ax.set_xlabel("Latency (ms)")
    ax.set_ylabel("Calls")
    ax.set_title("InvokeModel latency distribution by scenario")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    print(f"wrote {out_path}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", help="Specific CSV to render. Defaults to the latest.")
    p.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    args = p.parse_args()

    results_dir = Path(args.results_dir)
    if args.csv:
        csv_path = Path(args.csv)
    else:
        csv_path = find_latest_csv(results_dir)

    by_scenario = load(csv_path)
    out_path = csv_path.with_suffix(".png")
    render(by_scenario, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
