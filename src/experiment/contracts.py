"""Stable data contracts shared by experiment selection and execution."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
MANIFEST_SCHEMA_VERSION = 1
ExecutionMode = Literal["batch", "gui"]


@dataclass(frozen=True)
class TrackingPreset:
    """Code-owned description of one supported tracking input."""

    input_name: str
    config_rel: str
    scene_rel: str
    artifact_profile: str
    gui_description: str


@dataclass(frozen=True)
class TrackingRunSpec:
    """A resolved tracking preset with its configuration-derived duration."""

    input_name: str
    algorithm: str
    config_rel: str
    scene_rel: str
    artifact_profile: str
    steps: int
    gui_description: str

    @property
    def trajectory(self) -> str:
        """Compatibility name for callers using the former trajectory CLI."""

        return self.input_name

    @property
    def controller(self) -> str:
        """Compatibility name for callers using the former controller CLI."""

        return self.algorithm


@dataclass(frozen=True)
class RunManifest:
    """Resolved, code-generated request passed to a runtime adapter.

    This is an internal execution artifact.  Users select only registered
    high-level input and algorithm options; they do not author manifests.
    """

    run_id: str
    pipeline_id: str
    input_id: str
    algorithm_id: str
    config_rel: str
    scene_rel: str
    artifact_profile: str
    steps: int
    mode: ExecutionMode
    timeout_s: int
    gui_description: str
    schema_version: int = MANIFEST_SCHEMA_VERSION

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_mapping(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RunManifest":
        expected = {
            "run_id",
            "pipeline_id",
            "input_id",
            "algorithm_id",
            "config_rel",
            "scene_rel",
            "artifact_profile",
            "steps",
            "mode",
            "timeout_s",
            "gui_description",
            "schema_version",
        }
        unexpected = set(payload) - expected
        missing = expected - set(payload)
        if missing or unexpected:
            details = []
            if missing:
                details.append(f"missing={sorted(missing)}")
            if unexpected:
                details.append(f"unexpected={sorted(unexpected)}")
            raise ValueError(f"invalid run manifest fields: {', '.join(details)}")

        string_fields = (
            "run_id",
            "pipeline_id",
            "input_id",
            "algorithm_id",
            "config_rel",
            "scene_rel",
            "artifact_profile",
            "gui_description",
        )
        for name in string_fields:
            if not isinstance(payload[name], str) or not payload[name]:
                raise ValueError(f"run manifest field {name!r} must be a non-empty string")
        if not RUN_ID_PATTERN.fullmatch(str(payload["run_id"])):
            raise ValueError("run manifest run_id is invalid")
        if payload["mode"] not in {"batch", "gui"}:
            raise ValueError("run manifest mode must be batch or gui")
        for name in ("steps", "timeout_s", "schema_version"):
            value = payload[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"run manifest field {name!r} must be a positive integer")
        if payload["schema_version"] != MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported run manifest schema version {payload['schema_version']}"
            )

        return cls(**dict(payload))

    @classmethod
    def from_json(cls, raw: str) -> "RunManifest":
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("run manifest is not valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("run manifest must be a JSON object")
        return cls.from_mapping(payload)
