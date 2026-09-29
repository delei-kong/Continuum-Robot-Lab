# Continuum Robot Lab Workspace Rules

## Scope

These instructions apply to this directory and every subdirectory under it.

`/Users/tory/Desktop/workspace/Continuum-Robot-Lab/workspace` is the active research-project root and the local source of truth.

## File placement

- Put all new active project code, Python packages, simulation scenes, configuration files, tests, operational scripts, experiment metadata, generated figures, and project documentation under this directory.
- Do not create new active implementation files in the parent `Continuum-Robot-Lab` directory.
- Keep reference and administrative materials in their existing parent-level locations unless the user explicitly requests a move:
  - `../开题报告/`
  - `../中期答辩/`
  - `../paper/`
  - `../CRVS/`
- Treat `../CRVS/` as a legacy MATLAB reference project, not as the implementation root for the new Python research system.
- Use a flat source layout under `src/`; do not add an extra project-name package directory unless the user explicitly revisits this decision.
- Store source code in `src/`, infrastructure checks in `tests/smoke/`, other tests in `tests/`, operational tooling in `scripts/`, and documentation in `docs/`.
- Store reusable research data under `datasets/` and generated logs, checkpoints, metrics, figures, and videos under `outputs/`.
- Store project-level Agent workflows and Skill source under `agent/`. Treat this directory as the authoritative version; tool-specific installed copies are deployment artifacts.
- Do not commit large datasets, checkpoints, caches, or generated outputs unless explicitly requested.

## Local and remote workflow

- Develop and edit code locally in this workspace. The remote GPU workstation is an execution mirror, not a second source of truth.
- Mirror this local `workspace/` root to `/root/gpufree-share/Continuum-Robot-Lab/workspace` on the current remote workstation so the project-root directory name is identical on both sides.
- Use the scripts in `scripts/remote/` for SSH checks, environment setup, upload, background execution, status inspection, and result retrieval.
- Keep machine-specific connection settings in `scripts/remote/config.local.sh`; keep that file ignored by Git.
- Never store passwords, private keys, API tokens, or other credentials in this workspace.
- The dedicated SSH private key remains at `~/.ssh/id_ed25519_continuum_robot_lab` and must never be copied into the repository or remote server.
- Keep persistent remote code and important results on the remote shared storage. Treat the remote high-speed data disk as rebuildable temporary storage.
- Do not edit remote source files manually except for emergency diagnosis. Reproduce any emergency fix locally before the next experiment.
- Do not delete remote data or use destructive synchronization flags such as unguarded `rsync --delete` without explicit user approval and exact path verification.

## Reproducibility

- Run local syntax checks and lightweight tests before uploading code.
- Every formal experiment must eventually record its Git commit, configuration snapshot, random seed, dependency versions, device information, start/end time, and exit code.
- Give every remote run a unique run ID. Never overwrite a previous run directory.
- Split machine-learning datasets by complete trajectory or episode, not by randomly mixing adjacent transitions.
- Preserve failed experiment logs when they contain useful diagnostic information.

## Git conventions

- Write commit subjects as `<type>: <concise Chinese summary>`.
- Use conventional types such as `feat`, `fix`, `docs`, `refactor`, `test`, and `chore`.
- Keep each commit focused on one coherent change and leave `main` in a runnable state.
- Do not include the branch label, such as `[main]`, in the commit subject; Git displays it separately.

## Environment conventions

- Use Python 3.11 for the current remote research environment unless compatibility testing establishes a different pinned version.
- Do not use the remote base Python 3.13 environment for project dependencies.
- Prefer isolated Conda environments on the remote runtime disk during the current infrastructure phase.
- Pin important research dependencies once the simulator choice is finalized.
- Run long remote jobs under `tmux` or a scheduler so they do not depend on an SSH session remaining connected.

## Documentation

- Keep the remote-workflow SOP at `docs/本地开发与远程实验工作流SOP.md` current whenever the workflow, remote environment, commands, failure modes, or storage policy changes.
- Record material workflow changes in the SOP revision table.
- Keep research planning and implementation decisions explicit; do not silently expand the experiment scope.
