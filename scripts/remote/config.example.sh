#!/usr/bin/env bash

# Copy this file to config.local.sh and fill in the workstation details.
REMOTE_HOST="root@example.invalid"
REMOTE_PORT="22"
REMOTE_IDENTITY="$HOME/.ssh/id_ed25519_continuum_robot_lab"

REMOTE_PROJECT_PARENT="/root/gpufree-share/Continuum-Robot-Lab"
REMOTE_PROJECT_ROOT="$REMOTE_PROJECT_PARENT/workspace"
REMOTE_RUNTIME_ROOT="/root/gpufree-data/continuum-runtime"
REMOTE_CONDA_ENV="$REMOTE_RUNTIME_ROOT/envs/smoke-py311"

# SOFA uses a separate Python 3.10 runtime because the official v25.12 Linux
# binary is not built for Python 3.11.
REMOTE_SOFA_VERSION="25.12.00"
REMOTE_SOFA_PYTHON_VERSION="3.10"
REMOTE_SOFA_INSTALL_ROOT="$REMOTE_RUNTIME_ROOT/sofa/v25.12.00-python3.10"
REMOTE_SOFA_PYTHON_ENV="$REMOTE_RUNTIME_ROOT/envs/sofa-py310"
