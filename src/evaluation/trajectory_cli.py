"""Backward-compatible import path for the tracking experiment CLI.

New callers should import :mod:`experiment.tracking_cli`; this module stays to avoid
breaking existing tests and external notebooks during the staged migration.
"""

from experiment.tracking_cli import (
    RUN_ID_PATTERN,
    TrackingRunSpec,
    build_run_manifest,
    build_runner_environment,
    default_output_name,
    derive_steps_from_config,
    format_available_runs,
    main,
    resolve_run_spec,
    resolve_tracking_spec,
    run_remote_experiment,
    run_remote_workspace_experiment,
    run_remote_workspace_gui_experiment,
    run_local_remote,
    run_server_batch,
    run_server_gui,
    run_tracking_experiment,
    validate_output_name,
)

TrajectoryRunSpec = TrackingRunSpec

__all__ = [
    "RUN_ID_PATTERN",
    "TrackingRunSpec",
    "TrajectoryRunSpec",
    "build_run_manifest",
    "build_runner_environment",
    "default_output_name",
    "derive_steps_from_config",
    "format_available_runs",
    "main",
    "resolve_run_spec",
    "resolve_tracking_spec",
    "run_remote_experiment",
    "run_remote_workspace_experiment",
    "run_remote_workspace_gui_experiment",
    "run_local_remote",
    "run_server_batch",
    "run_server_gui",
    "run_tracking_experiment",
    "validate_output_name",
]


if __name__ == "__main__":
    raise SystemExit(main())
