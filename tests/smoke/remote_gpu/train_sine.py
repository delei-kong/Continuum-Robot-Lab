#!/usr/bin/env python3
"""Small deterministic GPU smoke test for the remote experiment workflow."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import socket
import time
from pathlib import Path

import torch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=800)
    parser.add_argument("--seed", type=int, default=20260927)
    return parser.parse_args()


def write_loss_svg(points: list[tuple[int, float]], destination: Path) -> None:
    width, height, margin = 900, 420, 50
    losses = [max(loss, 1e-12) for _, loss in points]
    log_losses = [math.log10(loss) for loss in losses]
    low, high = min(log_losses), max(log_losses)
    span = max(high - low, 1e-9)
    max_step = max(step for step, _ in points)

    coordinates = []
    for (step, _), log_loss in zip(points, log_losses):
        x = margin + (width - 2 * margin) * step / max(max_step, 1)
        y = margin + (height - 2 * margin) * (high - log_loss) / span
        coordinates.append(f"{x:.2f},{y:.2f}")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">
<rect width="100%" height="100%" fill="white"/>
<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" stroke="black"/>
<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height-margin}" stroke="black"/>
<polyline fill="none" stroke="#2563eb" stroke-width="2" points="{' '.join(coordinates)}"/>
<text x="{width/2}" y="25" text-anchor="middle" font-family="sans-serif">Sine regression loss (log10 scale)</text>
<text x="{width/2}" y="{height-10}" text-anchor="middle" font-family="sans-serif">training step</text>
<text x="15" y="{height/2}" font-family="sans-serif" transform="rotate(-90 15 {height/2})">log10(MSE)</text>
</svg>
"""
    destination.write_text(svg, encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    x = torch.linspace(-2 * math.pi, 2 * math.pi, 2048, device=device).unsqueeze(1)
    y = torch.sin(x)

    model = torch.nn.Sequential(
        torch.nn.Linear(1, 64),
        torch.nn.Tanh(),
        torch.nn.Linear(64, 64),
        torch.nn.Tanh(),
        torch.nn.Linear(64, 1),
    ).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=3e-3)

    started = time.perf_counter()
    loss_points: list[tuple[int, float]] = []
    for step in range(args.steps + 1):
        prediction = model(x)
        loss = torch.nn.functional.mse_loss(prediction, y)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()

        if step % 10 == 0 or step == args.steps:
            value = float(loss.detach().cpu())
            loss_points.append((step, value))
            print(f"step={step:04d} loss={value:.8e}", flush=True)

    if device.type == "cuda":
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started

    with torch.no_grad():
        predicted = model(x).detach().cpu().squeeze(1)
    x_cpu = x.detach().cpu().squeeze(1)
    y_cpu = y.detach().cpu().squeeze(1)

    with (args.output_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["step", "mse_loss"])
        writer.writerows(loss_points)

    with (args.output_dir / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["x", "target", "prediction"])
        for xv, target, estimate in zip(x_cpu.tolist(), y_cpu.tolist(), predicted.tolist()):
            writer.writerow([xv, target, estimate])

    summary = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "pid": os.getpid(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
        "seed": args.seed,
        "steps": args.steps,
        "elapsed_seconds": elapsed,
        "final_loss": loss_points[-1][1],
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_loss_svg(loss_points, args.output_dir / "loss_curve.svg")
    torch.save(
        {"model_state_dict": model.state_dict(), "summary": summary},
        args.output_dir / "model.pt",
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
