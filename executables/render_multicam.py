#!/usr/bin/env python3
"""Render a camera subrange of an N×M camera grid as one HTCondor proc, via visionsim.

Total jobs = R*C*(K+1): K render subranges per camera plus one dry-run
(sub_idx 0) per camera. ProcID maps onto a rows×cols grid of cameras:

    per_camera = jobs // (rows * cols)
    camera_idx = procid // per_camera
    sub_idx    = procid %  per_camera

Camera positions are centered at the origin; position (0, 0) is the grid
center. --config.camera-offset (from RenderConfig) is relative to the grid
center — the per-cell offset and the global offset are summed here and passed
to visionsim as the camera offset for this proc.

--frame-start/--frame-end use the blend-file's ORIGINAL frame numbering. The
keyframe multiplier is therefore intercepted here: it is still applied to the
scene by render_animation (via the config), but its effect
([s, e] -> [round(s*k), round((e+1)*k) - 1]) is replicated by this script to
compute the absolute subranges that get forwarded.

The blendfile is positional and must lead the command line; everything else
(including --renders-dir) is an option.

If the render fails, the exception propagates and no tarball is produced, so
HTCondor surfaces the failure directly in stderr.
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
from pathlib import Path

import tyro
from visionsim.cli.blender import render_animation
from visionsim.simulate.config import RenderConfig

FRAME_LIMIT = 1_048_574  # Blender's hard frame-number limit


def scale_frame_range(fs: int, fe: int, k: float) -> tuple[int, int]:
    """Rescale [fs, fe] exactly like visionsim's move_keyframes(scale=k)."""
    return round(fs * k), round((fe + 1) * k) - 1


def split_ranges(fs: int, fe: int, n: int) -> list[tuple[int, int]]:
    """Cover [fs, fe] with n contiguous subranges; early ones take the remainder."""
    size, rem = divmod(fe - fs + 1, n)
    out, start = [], fs
    for i in range(n):
        end = start + size - 1 + (i < rem)
        out.append((start, end))
        start = end + 1
    return out


def render_grid(
    blend_file: Path,
    /,
    rows: int,
    cols: int,
    spacing: float,
    procid: int,
    jobs: int,
    frame_start: int,
    frame_end: int,
    config: RenderConfig,
    output_file: Path | None = None,
    renders_dir: Path = Path("renders"),
) -> None:
    """Render one camera/subrange of an N×M camera grid via visionsim.

    One HTCondor proc executes this; each camera gets ``jobs // rows*cols``
    procs — one dry-run (sub_idx 0) plus the rest rendering consecutive
    subranges of the frame range.

    Args:
        blend_file: Path to the blend-file to render.
        rows: Number of rows of cameras on the grid.
        cols: Number of columns of cameras on the grid.
        spacing: Distance between adjacent cameras on the grid.
        procid: HTCondor ProcId within the cluster.
        jobs: Total number of procs: rows*cols*(K+1), K render subranges per camera.
        frame_start: Start of the frame range (original blend-file numbering).
        frame_end: End of the frame range (original blend-file numbering).
        renders_dir: Dataset output directory for this proc.
        output_file: If set, write the configured blend-file here for troubleshooting.
        config: Render configuration; same fields and flags as
            ``vsim blender.render-animation``.
    """
    total_cameras = rows * cols
    if total_cameras < 1:
        sys.exit("error: --rows and --cols must be at least 1")
    if jobs % total_cameras:
        sys.exit(f"error: --jobs ({jobs}) is not a multiple of rows*cols ({total_cameras})")
    per_camera = jobs // total_cameras
    if per_camera < 2:
        sys.exit(
            f"error: --jobs ({jobs}) must be at least 2×rows*cols "
            f"({2 * total_cameras}) to have at least 1 render subrange per camera"
        )
    if not 0 <= procid < jobs:
        sys.exit(f"error: --procid must be within [0, {jobs - 1}]")
    if frame_end >= FRAME_LIMIT:
        sys.exit(f"error: --frame-end {frame_end} reaches Blender's {FRAME_LIMIT} frame limit")

    fs, fe = frame_start, frame_end
    k = config.keyframe_multiplier
    if k != 1.0:
        if k <= 0:
            sys.exit(f"error: --config.keyframe-multiplier must be positive, got {k}")
        fs, fe = scale_frame_range(fs, fe, k)
        if fe < fs:
            sys.exit(f"error: keyframe-multiplier {k} produces an empty frame range")
        if fe >= FRAME_LIMIT:
            sys.exit(
                f"error: keyframe-multiplier {k} puts frame end at {fe}, "
                f"beyond Blender's {FRAME_LIMIT} frame limit"
            )
        print(f"keyframe-multiplier={k}: rendering scaled frame range [{fs}, {fe}]")

    camera_idx, sub_idx = divmod(procid, per_camera)
    row, col = divmod(camera_idx, cols)
    gx, gy, gz = config.camera_offset or (0.0, 0.0, 0.0)
    sx = gx + (col - (cols - 1) / 2) * spacing
    sy = gy + (row - (rows - 1) / 2) * spacing
    config = dataclasses.replace(config, camera_offset=(sx, sy, gz))
    camera_dir = renders_dir / f"{row:05d}_{col:05d}"

    if sub_idx == 0:
        render_animation(
            blend_file, camera_dir, config=config, output_file=output_file, dry_run=True
        )
    else:
        start, end = split_ranges(fs, fe, per_camera - 1)[sub_idx - 1]
        render_animation(
            blend_file,
            camera_dir,
            config=config,
            frame_start=start,
            frame_end=end,
            output_file=output_file,
            dry_run=False,
        )

    if sub_idx != 0:
        # transforms.db lives beside the outputs themselves (root, or
        # root/frames/ in this visionsim layout); drop them all
        for db in camera_dir.glob("**/transforms.db"):
            db.unlink(missing_ok=True)
    tar = subprocess.run(["tar", "-czf", f"renders_{procid:05d}.tar.gz", camera_dir], check=False)
    sys.exit(1 if tar.returncode else 0)


if __name__ == "__main__":
    tyro.cli(render_grid)
