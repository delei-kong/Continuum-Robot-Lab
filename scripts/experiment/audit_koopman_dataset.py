#!/usr/bin/env python3
"""Thin entrypoint for registered Koopman dataset assembly and audit."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from modeling.koopman_dataset_cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
