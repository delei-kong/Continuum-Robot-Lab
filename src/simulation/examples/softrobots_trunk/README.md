# SoftRobots Trunk baseline

This directory contains a verbatim, version-pinned copy of the SoftRobots
`Trunk` tutorial that was validated in the remote SOFA environment.

## Provenance

- Upstream repository: <https://github.com/SofaDefrost/SoftRobots>
- Upstream branch/tag: `v25.12`
- Upstream commit: `d1f9c933a99d800cb94f774adf3c40635c482243`
- Imported from: SOFA v25.12.00 Linux Python 3.10 binary distribution
- Import date: 2026-09-29
- License: GNU Lesser General Public License v3.0; see `LICENSE`

The baseline source and meshes are intentionally kept unchanged. Future
controllers should be implemented in separate project-owned scene/controller
files that import or wrap `Trunk`, so the upstream baseline remains available
for comparison.

## Contents

- `trunk.py`: upstream Python scene and `Trunk` prefab;
- `mesh/trunk.vtk`: tetrahedral mechanical mesh;
- `mesh/trunk.stl`: visual surface mesh;
- `mesh/trunk_colli1.stl`, `mesh/trunk_colli2.stl`: collision meshes;
- `UPSTREAM.sha256`: checksums of the imported upstream files.

The scene creates four long and four short cable constraints. It defaults to
direct resolution with zero commanded cable displacement. Its example cable
animation is present but commented out, so an unmodified run mainly exercises
gravity settling, FEM, constraints, and rendering.

## Run

From the local project root, run the remote batch validation and retrieve it:

```bash
scripts/remote/run_sofa_trunk_demo.sh <unique_run_id>
scripts/remote/fetch_run.sh sofa_demo <unique_run_id>
```

From a terminal in the remote XFCE desktop, run the graphical scene:

```bash
bash /root/gpufree-share/Continuum-Robot-Lab/workspace/scripts/server/run_sofa_trunk_gui.sh
```
