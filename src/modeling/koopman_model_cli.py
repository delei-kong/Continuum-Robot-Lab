"""Controlled command-line entrypoint for registered Koopman model training."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from .koopman_model import available_model_ids, resolve_model_definition, train_and_evaluate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train registered linear and fixed-lift Koopman dynamics models."
    )
    parser.add_argument("--model", default="koopman_v1_fixed_lift", help="registered model family")
    parser.add_argument("--dataset", default="koopman_v1", help="registered audited dataset")
    parser.add_argument("--dataset-audit", default=None, help="approved dataset audit output ID")
    parser.add_argument("--output", default=None, help="model output ID")
    parser.add_argument(
        "--stage",
        choices=("validation", "final"),
        default="validation",
        help="validation selects candidates without test metrics; final reports a frozen selection once",
    )
    parser.add_argument(
        "--selection",
        default=None,
        help="validation-stage output ID required by --stage final",
    )
    parser.add_argument("--list", action="store_true", help="list registered model families")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parents[2]
    try:
        if args.list:
            if args.dataset_audit or args.output or args.selection or args.stage != "validation":
                raise ValueError("--list cannot be combined with training options")
            for model_id in available_model_ids():
                definition = resolve_model_definition(model_id, args.dataset, project_root)
                print(f"{definition.model_id}: dataset={definition.dataset_id}")
            return 0
        if not args.dataset_audit or not args.output:
            raise ValueError("--dataset-audit and --output are required")
        return train_and_evaluate(
            project_root,
            model_id=args.model,
            dataset_id=args.dataset,
            dataset_audit_output=args.dataset_audit,
            output_id=args.output,
            evaluation_stage=args.stage,
            selection_output=args.selection,
        )
    except ValueError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
