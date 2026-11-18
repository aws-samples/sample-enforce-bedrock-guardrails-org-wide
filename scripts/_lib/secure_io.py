"""Helpers for writing result files that may contain sensitive content.

CSR-009: run_benchmark.py, capture_trace.py, and friends write full model
responses and guardrail assessment JSON (which can include detected PII
entity values, depending on your guardrail's PII policy actions) to
results/*.csv, results/*.json, results/*.log in plaintext. These files are
gitignored, but nothing previously restricted their filesystem permissions.

This module does two things:
1. Restricts the results directory to owner-only access (0700) on creation.
2. Restricts each written result file to owner-only read/write (0600)
   immediately after writing.

This is a minimal mitigation, not encryption at rest. See SECURITY.md for
the full discussion — treat results/ as sensitive whenever you run these
scripts against non-synthetic prompts.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path


def secure_results_dir(path: Path) -> Path:
    """Ensure the results directory exists and is restricted to the owner."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, stat.S_IRWXU)  # 0700
    except OSError:
        # Best-effort on filesystems that don't support POSIX permissions
        # (e.g. some CI runners, Windows). Not fatal.
        pass
    return path


def secure_file(path: Path) -> Path:
    """Restrict a just-written file to owner read/write only (0600)."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass
    return path
