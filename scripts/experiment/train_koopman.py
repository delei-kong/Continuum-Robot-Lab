#!/usr/bin/env python3
"""Stable user entrypoint for registered Koopman dynamics training."""

from modeling.koopman_model_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
