#!/usr/bin/env python3
"""Verify the semantic integrity and hashes of a completed smoke-test run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


ARTIFACT_FILES = (
    "COMPLETE",
    "exit_code",
    "loss_curve.svg",
    "metrics.csv",
    "model.pt",
    "predictions.csv",
    "stdout.log",
    "summary.json",
)
MANIFEST_NAME = "artifact_manifest.sha256"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--check-manifest", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"run_verification=failed: {message}")


def write_manifest(run_dir: Path) -> None:
    lines = [f"{sha256(run_dir / name)}  {name}" for name in ARTIFACT_FILES]
    (run_dir / MANIFEST_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_manifest(run_dir: Path) -> None:
    manifest_path = run_dir / MANIFEST_NAME
    require(manifest_path.is_file(), f"missing {MANIFEST_NAME}")
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        expected, filename = line.split(maxsplit=1)
        filename = filename.strip()
        path = run_dir / filename
        require(path.is_file(), f"manifest file missing: {filename}")
        require(sha256(path) == expected, f"checksum mismatch: {filename}")


def verify(run_dir: Path) -> dict[str, object]:
    require(run_dir.is_dir(), f"missing run directory: {run_dir}")
    for filename in ARTIFACT_FILES:
        path = run_dir / filename
        require(path.exists(), f"missing required artifact: {filename}")

    require(not (run_dir / "FAILED").exists(), "FAILED marker exists")
    require((run_dir / "exit_code").read_text(encoding="utf-8").strip() == "0", "non-zero exit code")
    require((run_dir / "model.pt").stat().st_size > 0, "empty model checkpoint")
    require("<svg" in (run_dir / "loss_curve.svg").read_text(encoding="utf-8"), "invalid SVG")

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    require(summary.get("cuda_available") is True, "CUDA was not used")
    require("NVIDIA" in str(summary.get("device", "")), "unexpected training device")

    with (run_dir / "metrics.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    require(len(rows) >= 2, "not enough metric rows")
    initial_loss = float(rows[0]["mse_loss"])
    final_loss = float(rows[-1]["mse_loss"])
    require(math.isfinite(initial_loss) and math.isfinite(final_loss), "non-finite loss")
    require(final_loss < initial_loss, "loss did not decrease")
    require(final_loss < 1e-2, "final loss is above smoke-test threshold")
    require(abs(final_loss - float(summary["final_loss"])) < 1e-12, "summary and CSV disagree")

    with (run_dir / "predictions.csv").open(newline="", encoding="utf-8") as handle:
        prediction_rows = sum(1 for _ in handle) - 1
    require(prediction_rows >= 100, "prediction output is unexpectedly small")

    return {
        "run_verification": "passed",
        "device": summary["device"],
        "steps": summary["steps"],
        "initial_loss": initial_loss,
        "final_loss": final_loss,
        "loss_ratio": final_loss / initial_loss,
        "prediction_rows": prediction_rows,
    }


def main() -> None:
    args = parse_args()
    result = verify(args.run_dir)
    if args.write_manifest:
        write_manifest(args.run_dir)
        result["manifest"] = "written"
    if args.check_manifest:
        check_manifest(args.run_dir)
        result["manifest"] = "passed"
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
