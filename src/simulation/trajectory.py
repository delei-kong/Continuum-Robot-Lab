"""Pure-Python reference trajectories for tracking experiments."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, sin, sqrt, tau
from typing import Any, Mapping, Protocol

from control.tracking_contracts import TrajectoryReference, Vec3, finite_vec3


class Trajectory(Protocol):
    @property
    def start_mm(self) -> Vec3: ...

    @property
    def end_mm(self) -> Vec3: ...

    @property
    def duration_s(self) -> float: ...

    def reset(self, seed: int) -> None: ...

    def sample(self, time_s: float) -> TrajectoryReference: ...


@dataclass(frozen=True)
class LinearTrajectory:
    """Move linearly between two task-space points and then hold the endpoint."""

    start_mm: Vec3
    end_mm: Vec3
    duration_s: float

    def __post_init__(self) -> None:
        finite_vec3(self.start_mm, "linear trajectory start")
        finite_vec3(self.end_mm, "linear trajectory end")
        if not isfinite(self.duration_s) or self.duration_s <= 0.0:
            raise ValueError("linear trajectory duration must be finite and positive")

    def reset(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("trajectory seed must be an integer")

    def sample(self, time_s: float) -> TrajectoryReference:
        if not isfinite(time_s) or time_s < 0.0:
            raise ValueError("trajectory time must be finite and non-negative")
        if time_s >= self.duration_s:
            return TrajectoryReference(
                time_s=time_s,
                position_mm=self.end_mm,
                velocity_mm_s=(0.0, 0.0, 0.0),
                phase="hold",
            )
        alpha = time_s / self.duration_s
        position = tuple(
            start + alpha * (end - start)
            for start, end in zip(self.start_mm, self.end_mm)
        )
        velocity = tuple(
            (end - start) / self.duration_s
            for start, end in zip(self.start_mm, self.end_mm)
        )
        return TrajectoryReference(
            time_s=time_s,
            position_mm=position,  # type: ignore[arg-type]
            velocity_mm_s=velocity,  # type: ignore[arg-type]
            acceleration_mm_s2=(0.0, 0.0, 0.0),
            phase="transition",
        )


@dataclass(frozen=True)
class TimedLinearTrajectory:
    """Hold the start, traverse one line segment, then hold the endpoint."""

    start_mm: Vec3
    end_mm: Vec3
    settle_duration_s: float
    transition_duration_s: float
    hold_duration_s: float

    def __post_init__(self) -> None:
        finite_vec3(self.start_mm, "timed linear trajectory start")
        finite_vec3(self.end_mm, "timed linear trajectory end")
        durations = (
            self.settle_duration_s,
            self.transition_duration_s,
            self.hold_duration_s,
        )
        if any(not isfinite(duration) or duration < 0.0 for duration in durations):
            raise ValueError("timed linear trajectory durations must be finite and non-negative")
        if self.transition_duration_s <= 0.0:
            raise ValueError("timed linear transition duration must be positive")

    @property
    def duration_s(self) -> float:
        return (
            self.settle_duration_s
            + self.transition_duration_s
            + self.hold_duration_s
        )

    def reset(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("trajectory seed must be an integer")

    def sample(self, time_s: float) -> TrajectoryReference:
        if not isfinite(time_s) or time_s < 0.0:
            raise ValueError("trajectory time must be finite and non-negative")
        if time_s <= self.settle_duration_s:
            return TrajectoryReference(time_s, self.start_mm, phase="settle")
        transition_time_s = time_s - self.settle_duration_s
        if transition_time_s >= self.transition_duration_s:
            return TrajectoryReference(time_s, self.end_mm, phase="hold")
        alpha = transition_time_s / self.transition_duration_s
        position = tuple(
            start + alpha * (end - start)
            for start, end in zip(self.start_mm, self.end_mm)
        )
        velocity = tuple(
            (end - start) / self.transition_duration_s
            for start, end in zip(self.start_mm, self.end_mm)
        )
        return TrajectoryReference(
            time_s=time_s,
            position_mm=position,  # type: ignore[arg-type]
            velocity_mm_s=velocity,  # type: ignore[arg-type]
            phase="transition",
        )


@dataclass(frozen=True)
class PeriodicEllipseTrajectory:
    """Traverse a parametric 3-D ellipse after settling at its first point."""

    center_mm: Vec3
    axis_cos_mm: Vec3
    axis_sin_mm: Vec3
    settle_duration_s: float
    cycle_duration_s: float
    cycle_count: int
    hold_duration_s: float

    def __post_init__(self) -> None:
        finite_vec3(self.center_mm, "ellipse center")
        finite_vec3(self.axis_cos_mm, "ellipse cosine axis")
        finite_vec3(self.axis_sin_mm, "ellipse sine axis")
        if sum(value * value for value in self.axis_cos_mm) == 0.0:
            raise ValueError("ellipse cosine axis must not be zero")
        if sum(value * value for value in self.axis_sin_mm) == 0.0:
            raise ValueError("ellipse sine axis must not be zero")
        if not isfinite(self.settle_duration_s) or self.settle_duration_s < 0.0:
            raise ValueError("ellipse settle duration must be finite and non-negative")
        if not isfinite(self.cycle_duration_s) or self.cycle_duration_s <= 0.0:
            raise ValueError("ellipse cycle duration must be finite and positive")
        if isinstance(self.cycle_count, bool) or not isinstance(self.cycle_count, int):
            raise ValueError("ellipse cycle count must be an integer")
        if self.cycle_count <= 0:
            raise ValueError("ellipse cycle count must be positive")
        if not isfinite(self.hold_duration_s) or self.hold_duration_s < 0.0:
            raise ValueError("ellipse hold duration must be finite and non-negative")

    @property
    def start_mm(self) -> Vec3:
        return tuple(
            center + axis
            for center, axis in zip(self.center_mm, self.axis_cos_mm)
        )  # type: ignore[return-value]

    @property
    def end_mm(self) -> Vec3:
        return self.start_mm

    @property
    def duration_s(self) -> float:
        return (
            self.settle_duration_s
            + self.cycle_duration_s * self.cycle_count
            + self.hold_duration_s
        )

    def reset(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("trajectory seed must be an integer")

    def sample(self, time_s: float) -> TrajectoryReference:
        if not isfinite(time_s) or time_s < 0.0:
            raise ValueError("trajectory time must be finite and non-negative")
        if time_s <= self.settle_duration_s:
            return TrajectoryReference(time_s, self.start_mm, phase="settle")
        tracking_time_s = time_s - self.settle_duration_s
        tracking_duration_s = self.cycle_duration_s * self.cycle_count
        if tracking_time_s >= tracking_duration_s:
            return TrajectoryReference(time_s, self.end_mm, phase="hold")

        angle = tau * tracking_time_s / self.cycle_duration_s
        angular_rate = tau / self.cycle_duration_s
        position = tuple(
            center + cosine_axis * cos(angle) + sine_axis * sin(angle)
            for center, cosine_axis, sine_axis in zip(
                self.center_mm, self.axis_cos_mm, self.axis_sin_mm
            )
        )
        velocity = tuple(
            angular_rate
            * (-cosine_axis * sin(angle) + sine_axis * cos(angle))
            for cosine_axis, sine_axis in zip(self.axis_cos_mm, self.axis_sin_mm)
        )
        acceleration = tuple(
            -(angular_rate**2)
            * (cosine_axis * cos(angle) + sine_axis * sin(angle))
            for cosine_axis, sine_axis in zip(self.axis_cos_mm, self.axis_sin_mm)
        )
        return TrajectoryReference(
            time_s=time_s,
            position_mm=position,  # type: ignore[arg-type]
            velocity_mm_s=velocity,  # type: ignore[arg-type]
            acceleration_mm_s2=acceleration,  # type: ignore[arg-type]
            phase="tracking",
            cycle_index=int(tracking_time_s / self.cycle_duration_s),
        )


def sample_trajectory_polyline(
    trajectory: Trajectory, sample_count: int
) -> tuple[list[Vec3], list[list[int]]]:
    """Sample a static reference polyline for SOFA-side visual validation."""

    if isinstance(sample_count, bool) or not isinstance(sample_count, int):
        raise ValueError("polyline sample count must be an integer")
    if sample_count < 2:
        raise ValueError("polyline sample count must be at least two")
    positions = [
        trajectory.sample(trajectory.duration_s * index / (sample_count - 1)).position_mm
        for index in range(sample_count)
    ]
    edges = [[index, index + 1] for index in range(sample_count - 1)]
    return positions, edges


def polyline_tube_geometry(
    positions: list[Vec3], radius_mm: float, radial_segments: int = 8
) -> tuple[list[Vec3], list[list[int]]]:
    """Build independent tube segments for a clearly visible SOFA reference path."""

    if not isfinite(radius_mm) or radius_mm <= 0.0:
        raise ValueError("tube radius must be finite and positive")
    if isinstance(radial_segments, bool) or not isinstance(radial_segments, int):
        raise ValueError("tube radial segment count must be an integer")
    if radial_segments < 3:
        raise ValueError("tube radial segment count must be at least three")
    if len(positions) < 2:
        raise ValueError("tube path must contain at least two positions")

    vertices: list[Vec3] = []
    quads: list[list[int]] = []
    for start, end in zip(positions, positions[1:]):
        delta = tuple(finish - begin for begin, finish in zip(start, end))
        length = sqrt(sum(axis * axis for axis in delta))
        if length <= 1e-9:
            continue
        direction = tuple(axis / length for axis in delta)
        helper = (1.0, 0.0, 0.0) if abs(direction[0]) < 0.9 else (0.0, 1.0, 0.0)
        normal = (
            direction[1] * helper[2] - direction[2] * helper[1],
            direction[2] * helper[0] - direction[0] * helper[2],
            direction[0] * helper[1] - direction[1] * helper[0],
        )
        normal_length = sqrt(sum(axis * axis for axis in normal))
        normal = tuple(axis / normal_length for axis in normal)
        binormal = (
            direction[1] * normal[2] - direction[2] * normal[1],
            direction[2] * normal[0] - direction[0] * normal[2],
            direction[0] * normal[1] - direction[1] * normal[0],
        )
        base = len(vertices)
        for point in (start, end):
            for segment in range(radial_segments):
                angle = tau * segment / radial_segments
                offset = tuple(
                    radius_mm * (normal[axis] * cos(angle) + binormal[axis] * sin(angle))
                    for axis in range(3)
                )
                vertices.append(
                    tuple(
                        coordinate + offset[axis]
                        for axis, coordinate in enumerate(point)
                    )  # type: ignore[arg-type]
                )
        for segment in range(radial_segments):
            next_segment = (segment + 1) % radial_segments
            quads.append(
                [
                    base + segment,
                    base + next_segment,
                    base + radial_segments + next_segment,
                    base + radial_segments + segment,
                ]
            )
    if not quads:
        raise ValueError("tube path must contain at least one non-zero segment")
    return vertices, quads


def trajectory_from_mapping(values: Mapping[str, Any]) -> Trajectory:
    trajectory_type = values.get("type")
    if trajectory_type == "linear":
        return LinearTrajectory(
            start_mm=finite_vec3(tuple(values["start_mm"]), "linear trajectory start"),
            end_mm=finite_vec3(tuple(values["end_mm"]), "linear trajectory end"),
            duration_s=float(values["duration_s"]),
        )
    if trajectory_type == "timed_linear":
        return TimedLinearTrajectory(
            start_mm=finite_vec3(
                tuple(values["start_mm"]), "timed linear trajectory start"
            ),
            end_mm=finite_vec3(
                tuple(values["end_mm"]), "timed linear trajectory end"
            ),
            settle_duration_s=float(values["settle_duration_s"]),
            transition_duration_s=float(values["transition_duration_s"]),
            hold_duration_s=float(values["hold_duration_s"]),
        )
    if trajectory_type == "periodic_ellipse":
        return PeriodicEllipseTrajectory(
            center_mm=finite_vec3(tuple(values["center_mm"]), "ellipse center"),
            axis_cos_mm=finite_vec3(
                tuple(values["axis_cos_mm"]), "ellipse cosine axis"
            ),
            axis_sin_mm=finite_vec3(
                tuple(values["axis_sin_mm"]), "ellipse sine axis"
            ),
            settle_duration_s=float(values["settle_duration_s"]),
            cycle_duration_s=float(values["cycle_duration_s"]),
            cycle_count=int(values["cycle_count"]),
            hold_duration_s=float(values["hold_duration_s"]),
        )
    raise ValueError(f"unsupported trajectory type: {trajectory_type!r}")
