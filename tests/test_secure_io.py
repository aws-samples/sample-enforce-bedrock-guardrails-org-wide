"""Unit tests for scripts/_lib/secure_io.py (CSR-009 mitigation)."""
from __future__ import annotations

import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _lib.secure_io import secure_file, secure_results_dir  # noqa: E402


def test_secure_results_dir_creates_and_restricts(tmp_path):
    target = tmp_path / "results"
    assert not target.exists()

    secure_results_dir(target)

    assert target.exists()
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == stat.S_IRWXU  # 0700 — owner only


def test_secure_results_dir_is_idempotent(tmp_path):
    target = tmp_path / "results"
    secure_results_dir(target)
    secure_results_dir(target)  # should not raise on second call
    assert target.exists()


def test_secure_file_restricts_existing_file(tmp_path):
    f = tmp_path / "trace_20260101T000000Z.json"
    f.write_text('{"hello": "world"}')
    # Simulate a permissive default before securing.
    f.chmod(0o644)

    secure_file(f)

    mode = stat.S_IMODE(f.stat().st_mode)
    assert mode == (stat.S_IRUSR | stat.S_IWUSR)  # 0600 — owner read/write only
