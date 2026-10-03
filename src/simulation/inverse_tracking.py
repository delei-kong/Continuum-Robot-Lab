"""Pure-Python target schedule and timing statistics for inverse Trunk control."""

from __future__ import annotations

import random
from dataclasses import dataclass
from math import dist, isfinite, sqrt
from typing import Any, Mapping, Sequence


Point3 = tuple[float, float, float]
Triangle = tuple[int, int, int]
Edge = tuple[int, int]


def _point3(value: Any, name: str) -> Point3:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
        raise ValueError(f"{name} must contain exactly three values")
    point = tuple(float(axis) for axis in value)
    if not all(isfinite(axis) for axis in point):
        raise ValueError(f"{name} must contain finite values")
    return point  # type: ignore[return-value]


def octahedron_marker_geometry(
    radius_mm: float,
) -> tuple[tuple[Point3, ...], tuple[Triangle, ...], tuple[Edge, ...]]:
    """Build a centered octahedron used only as a target visual marker."""

    radius = float(radius_mm)
    if not isfinite(radius) or radius <= 0.0:
        raise ValueError("target marker radius must be finite and positive")
    vertices: tuple[Point3, ...] = (
        (radius, 0.0, 0.0),
        (-radius, 0.0, 0.0),
        (0.0, radius, 0.0),
        (0.0, -radius, 0.0),
        (0.0, 0.0, radius),
        (0.0, 0.0, -radius),
    )
    triangles: tuple[Triangle, ...] = (
        (4, 0, 2),
        (4, 2, 1),
        (4, 1, 3),
        (4, 3, 0),
        (5, 2, 0),
        (5, 1, 2),
        (5, 3, 1),
        (5, 0, 3),
    )
    edges: tuple[Edge, ...] = (
        (0, 2),
        (2, 1),
        (1, 3),
        (3, 0),
        (4, 0),
        (4, 1),
        (4, 2),
        (4, 3),
        (5, 0),
        (5, 1),
        (5, 2),
        (5, 3),
    )
    return vertices, triangles, edges


def crosshair_marker_geometry(half_length_mm: float) -> tuple[tuple[Point3, ...], tuple[Edge, ...]]:
    """Build three centered axis segments used as a target crosshair."""

    half_length = float(half_length_mm)
    if not isfinite(half_length) or half_length <= 0.0:
        raise ValueError("target crosshair length must be finite and positive")
    vertices: tuple[Point3, ...] = (
        (-half_length, 0.0, 0.0),
        (half_length, 0.0, 0.0),
        (0.0, -half_length, 0.0),
        (0.0, half_length, 0.0),
        (0.0, 0.0, -half_length),
        (0.0, 0.0, half_length),
    )
    return vertices, ((0, 1), (2, 3), (4, 5))


def translate_marker(vertices: Sequence[Point3], center_mm: Point3) -> list[list[float]]:
    """Translate marker-local vertices to the current world-space target."""

    if len(center_mm) != 3 or not all(isfinite(axis) for axis in center_mm):
        raise ValueError("marker center must contain three finite values")
    return [
        [vertex[axis] + center_mm[axis] for axis in range(3)]
        for vertex in vertices
    ]


@dataclass(frozen=True)
class InverseTargetSample:
    time_s: float
    position_mm: Point3
    phase: str
    cycle_index: int = -1
    waypoint_index: int = -1


@dataclass(frozen=True)
class InverseTrackingConfig:
    dt: float
    control_rate_hz: float
    start_target_mm: Point3
    target_mm: Point3
    settle_duration_s: float
    transition_duration_s: float
    hold_duration_s: float
    deadline_ms: float
    benchmark_warmup_steps: int

    def __post_init__(self) -> None:
        scalar_values = (
            self.dt,
            self.control_rate_hz,
            self.settle_duration_s,
            self.transition_duration_s,
            self.hold_duration_s,
            self.deadline_ms,
        )
        if not all(isfinite(value) for value in scalar_values):
            raise ValueError("inverse tracking configuration must contain finite values")
        if self.dt <= 0.0 or self.control_rate_hz <= 0.0:
            raise ValueError("dt and control_rate_hz must be positive")
        if abs(self.dt * self.control_rate_hz - 1.0) > 1e-9:
            raise ValueError("one simulation step must equal one control period")
        if self.settle_duration_s < 0.0:
            raise ValueError("settle duration must be non-negative")
        if self.transition_duration_s <= 0.0 or self.hold_duration_s <= 0.0:
            raise ValueError("transition and hold durations must be positive")
        if self.deadline_ms <= 0.0:
            raise ValueError("deadline_ms must be positive")
        if isinstance(self.benchmark_warmup_steps, bool) or self.benchmark_warmup_steps < 0:
            raise ValueError("benchmark_warmup_steps must be a non-negative integer")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "InverseTrackingConfig":
        return cls(
            dt=float(values["dt"]),
            control_rate_hz=float(values["control_rate_hz"]),
            start_target_mm=_point3(values["start_target_mm"], "start_target_mm"),
            target_mm=_point3(values["target_mm"], "target_mm"),
            settle_duration_s=float(values["settle_duration_s"]),
            transition_duration_s=float(values["transition_duration_s"]),
            hold_duration_s=float(values["hold_duration_s"]),
            deadline_ms=float(values["deadline_ms"]),
            benchmark_warmup_steps=int(values["benchmark_warmup_steps"]),
        )

    @property
    def total_duration_s(self) -> float:
        return self.settle_duration_s + self.transition_duration_s + self.hold_duration_s


class InverseTargetSignal:
    """Hold the initial goal, move linearly, then hold one fixed goal."""

    def __init__(self, config: InverseTrackingConfig) -> None:
        self.config = config

    def sample(self, time_s: float) -> InverseTargetSample:
        if not isfinite(time_s) or time_s < 0.0:
            raise ValueError("time_s must be finite and non-negative")
        config = self.config
        if time_s < config.settle_duration_s:
            return InverseTargetSample(time_s, config.start_target_mm, "settle")

        transition_time = time_s - config.settle_duration_s
        if transition_time < config.transition_duration_s:
            alpha = transition_time / config.transition_duration_s
            position = tuple(
                start + alpha * (target - start)
                for start, target in zip(config.start_target_mm, config.target_mm)
            )
            return InverseTargetSample(time_s, position, "transition")  # type: ignore[arg-type]
        return InverseTargetSample(time_s, config.target_mm, "hold")

    def sample_step(self, step: int) -> InverseTargetSample:
        if isinstance(step, bool) or not isinstance(step, int) or step < 0:
            raise ValueError("step must be a non-negative integer")
        return self.sample(step * self.config.dt)

    def total_steps(self) -> int:
        steps = round(self.config.total_duration_s / self.config.dt)
        if abs(steps * self.config.dt - self.config.total_duration_s) > 1e-9:
            raise ValueError("total duration must be an integer multiple of dt")
        return steps


@dataclass(frozen=True)
class PeriodicRandomTrackingConfig:
    dt: float
    control_rate_hz: float
    start_target_mm: Point3
    random_seed: int
    waypoint_count: int
    cycle_count: int
    workspace_bounds_mm: tuple[tuple[float, float], ...]
    min_start_distance_mm: float
    min_waypoint_separation_mm: float
    min_base_distance_mm: float
    max_base_distance_mm: float
    settle_duration_s: float
    transition_duration_s: float
    hold_duration_s: float
    deadline_ms: float
    benchmark_warmup_steps: int
    max_generation_attempts: int

    def __post_init__(self) -> None:
        scalar_values = (
            self.dt,
            self.control_rate_hz,
            self.min_start_distance_mm,
            self.min_waypoint_separation_mm,
            self.min_base_distance_mm,
            self.max_base_distance_mm,
            self.settle_duration_s,
            self.transition_duration_s,
            self.hold_duration_s,
            self.deadline_ms,
        )
        if not all(isfinite(value) for value in scalar_values):
            raise ValueError("periodic tracking configuration must contain finite values")
        if self.dt <= 0.0 or self.control_rate_hz <= 0.0:
            raise ValueError("dt and control_rate_hz must be positive")
        if abs(self.dt * self.control_rate_hz - 1.0) > 1e-9:
            raise ValueError("one simulation step must equal one control period")
        if self.waypoint_count < 2 or self.cycle_count < 1:
            raise ValueError("waypoint_count must be at least two and cycle_count positive")
        if len(self.workspace_bounds_mm) != 3 or any(
            len(bounds) != 2 or not all(isfinite(value) for value in bounds)
            or bounds[0] >= bounds[1]
            for bounds in self.workspace_bounds_mm
        ):
            raise ValueError("workspace bounds must contain three increasing finite ranges")
        if self.min_start_distance_mm <= 0.0 or self.min_waypoint_separation_mm <= 0.0:
            raise ValueError("waypoint distance constraints must be positive")
        if self.min_base_distance_mm <= 0.0 or (
            self.max_base_distance_mm <= self.min_base_distance_mm
        ):
            raise ValueError("base distance range must be positive and increasing")
        if self.settle_duration_s < 0.0:
            raise ValueError("settle duration must be non-negative")
        if self.transition_duration_s <= 0.0 or self.hold_duration_s <= 0.0:
            raise ValueError("transition and hold durations must be positive")
        if self.deadline_ms <= 0.0:
            raise ValueError("deadline_ms must be positive")
        integer_values = (
            self.random_seed,
            self.waypoint_count,
            self.cycle_count,
            self.benchmark_warmup_steps,
            self.max_generation_attempts,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in integer_values):
            raise ValueError("seed, counts, warmup, and attempts must be integers")
        if self.benchmark_warmup_steps < 0 or self.max_generation_attempts < 1:
            raise ValueError("warmup must be non-negative and attempts positive")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "PeriodicRandomTrackingConfig":
        raw_bounds = values["workspace_bounds_mm"]
        if not isinstance(raw_bounds, Mapping):
            raise ValueError("workspace_bounds_mm must be a mapping")
        bounds = tuple(
            tuple(float(value) for value in raw_bounds[axis]) for axis in ("x", "y", "z")
        )
        return cls(
            dt=float(values["dt"]),
            control_rate_hz=float(values["control_rate_hz"]),
            start_target_mm=_point3(values["start_target_mm"], "start_target_mm"),
            random_seed=int(values["random_seed"]),
            waypoint_count=int(values["waypoint_count"]),
            cycle_count=int(values["cycle_count"]),
            workspace_bounds_mm=bounds,
            min_start_distance_mm=float(values["min_start_distance_mm"]),
            min_waypoint_separation_mm=float(values["min_waypoint_separation_mm"]),
            min_base_distance_mm=float(values["min_base_distance_mm"]),
            max_base_distance_mm=float(values["max_base_distance_mm"]),
            settle_duration_s=float(values["settle_duration_s"]),
            transition_duration_s=float(values["transition_duration_s"]),
            hold_duration_s=float(values["hold_duration_s"]),
            deadline_ms=float(values["deadline_ms"]),
            benchmark_warmup_steps=int(values["benchmark_warmup_steps"]),
            max_generation_attempts=int(values.get("max_generation_attempts", 10000)),
        )

    @property
    def total_duration_s(self) -> float:
        segment_duration = self.transition_duration_s + self.hold_duration_s
        return self.settle_duration_s + self.cycle_count * self.waypoint_count * segment_duration


def generate_random_waypoints(config: PeriodicRandomTrackingConfig) -> tuple[Point3, ...]:
    """Generate a deterministic, spatially separated waypoint set inside safe bounds."""

    generator = random.Random(config.random_seed)
    waypoints: list[Point3] = []
    for _attempt in range(config.max_generation_attempts):
        candidate = tuple(
            generator.uniform(lower, upper)
            for lower, upper in config.workspace_bounds_mm
        )
        base_distance = sqrt(sum(axis * axis for axis in candidate))
        if not config.min_base_distance_mm <= base_distance <= config.max_base_distance_mm:
            continue
        if dist(candidate, config.start_target_mm) < config.min_start_distance_mm:
            continue
        if any(dist(candidate, waypoint) < config.min_waypoint_separation_mm for waypoint in waypoints):
            continue
        waypoints.append(candidate)  # type: ignore[arg-type]
        if len(waypoints) == config.waypoint_count:
            return tuple(waypoints)
    raise ValueError(
        "unable to generate enough separated waypoints within max_generation_attempts"
    )


class PeriodicRandomTargetSignal:
    """Visit a reproducible random waypoint set repeatedly with linear transitions."""

    def __init__(
        self, config: PeriodicRandomTrackingConfig, waypoints: Sequence[Point3]
    ) -> None:
        if len(waypoints) != config.waypoint_count:
            raise ValueError("waypoint count does not match periodic tracking configuration")
        self.config = config
        self.waypoints = tuple(_point3(point, "waypoint") for point in waypoints)

    def sample(self, time_s: float) -> InverseTargetSample:
        if not isfinite(time_s) or time_s < 0.0:
            raise ValueError("time_s must be finite and non-negative")
        config = self.config
        if time_s < config.settle_duration_s:
            return InverseTargetSample(time_s, config.start_target_mm, "settle")

        segment_duration = config.transition_duration_s + config.hold_duration_s
        elapsed = time_s - config.settle_duration_s
        segment_index = min(
            int(elapsed / segment_duration),
            config.cycle_count * config.waypoint_count - 1,
        )
        cycle_index, waypoint_index = divmod(segment_index, config.waypoint_count)
        local_time = elapsed - segment_index * segment_duration
        target = self.waypoints[waypoint_index]
        if segment_index == 0:
            source = config.start_target_mm
        else:
            source = self.waypoints[(waypoint_index - 1) % config.waypoint_count]
        if local_time < config.transition_duration_s:
            alpha = local_time / config.transition_duration_s
            position = tuple(
                start + alpha * (goal - start) for start, goal in zip(source, target)
            )
            return InverseTargetSample(
                time_s,
                position,  # type: ignore[arg-type]
                "transition",
                cycle_index,
                waypoint_index,
            )
        return InverseTargetSample(
            time_s, target, "hold", cycle_index, waypoint_index
        )

    def sample_step(self, step: int) -> InverseTargetSample:
        if isinstance(step, bool) or not isinstance(step, int) or step < 0:
            raise ValueError("step must be a non-negative integer")
        return self.sample(step * self.config.dt)

    def total_steps(self) -> int:
        steps = round(self.config.total_duration_s / self.config.dt)
        if abs(steps * self.config.dt - self.config.total_duration_s) > 1e-9:
            raise ValueError("total duration must be an integer multiple of dt")
        return steps


def percentile(values: Sequence[float], probability: float) -> float:
    """Return a linearly interpolated percentile without external dependencies."""

    if not values:
        raise ValueError("values must not be empty")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be between zero and one")
    ordered = sorted(float(value) for value in values)
    if not all(isfinite(value) for value in ordered):
        raise ValueError("values must be finite")
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def summarize_step_times(
    step_times_ms: Sequence[float], deadline_ms: float, warmup_steps: int
) -> dict[str, float | int | bool]:
    if not isfinite(deadline_ms) or deadline_ms <= 0.0:
        raise ValueError("deadline_ms must be finite and positive")
    if isinstance(warmup_steps, bool) or not isinstance(warmup_steps, int) or warmup_steps < 0:
        raise ValueError("warmup_steps must be a non-negative integer")
    measured = [float(value) for value in step_times_ms[warmup_steps:]]
    if not measured:
        raise ValueError("no timing samples remain after warmup")
    missed = sum(value > deadline_ms for value in measured)
    p99_ms = percentile(measured, 0.99)
    return {
        "warmup_steps": warmup_steps,
        "measured_steps": len(measured),
        "mean_ms": sum(measured) / len(measured),
        "p50_ms": percentile(measured, 0.50),
        "p95_ms": percentile(measured, 0.95),
        "p99_ms": p99_ms,
        "max_ms": max(measured),
        "deadline_ms": deadline_ms,
        "deadline_misses": missed,
        "deadline_success_ratio": (len(measured) - missed) / len(measured),
        "p99_deadline_met": p99_ms <= deadline_ms,
    }
