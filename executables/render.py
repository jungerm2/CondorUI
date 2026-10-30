#!/usr/bin/env python3
"""Render a contiguous subrange of a frame range as one HTCondor proc, through visionsim.

ProcId 0 is the dry-run over the full range; the remaining jobs-1 procs render
contiguous subranges of [frame-start, frame-end] and package their outputs as
``renders_<procid>.tar.gz`` for HTCondor.

If the render fails, the exception propagates and no tarball is produced, so
HTCondor surfaces the failure directly in stderr.

--frame-start/--frame-end use the blend-file's ORIGINAL frame numbering. The
keyframe multiplier is therefore intercepted here: it is still applied to the
scene by render_animation (via the config), but its effect
([s, e] -> [round(s*k), round((e+1)*k) - 1]) is replicated by this script to
compute the absolute subranges that get forwarded.

The blendfile is positional and must lead the command line; everything else
(including --renders-dir) is an option. All --config.* flags come from
visionsim's own RenderConfig and mean the same as in
``vsim blender.render-animation``.
"""

from __future__ import annotations

import shutil
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


def render(
    blend_file: Path,
    /,
    procid: int,
    jobs: int,
    config: RenderConfig,
    frame_start: int | None = None,
    frame_end: int | None = None,
    output_file: Path | None = None,
    renders_dir: Path = Path("renders"),
) -> None:
    """Render one frame subrange of a blend-file via visionsim.

    One HTCondor proc executes this; ProcId 0 is the dry-run, the rest render
    consecutive subranges of the frame range.

    Args:
        blend_file: Path to the blend-file to render.
        procid: HTCondor ProcId within the cluster; ProcId 0 is the dry-run.
        jobs: Total number of procs: 1 dry-run plus jobs-1 renderers.
        frame_start: Start of the frame range (original blend-file numbering).
        frame_end: End of the frame range (original blend-file numbering).
        renders_dir: Dataset output directory for this proc.
        output_file: If set, write the configured blend-file here for troubleshooting.
            Only the dry-run proc writes one; the render procs would be identical.
        config: Render configuration; same fields and flags as
            ``vsim blender.render-animation``.
    """
    if jobs < 2:
        sys.exit("error: --jobs must be at least 2 (1 dry-run + at least 1 renderer)")
    if not 0 <= procid < jobs:
        sys.exit(f"error: --procid must be within [0, {jobs - 1}]")
    if frame_start is None or frame_end is None:
        sys.exit("error: --frame-start and --frame-end are required")
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

    if output_file is not None and procid == 0:
        output_file.parent.mkdir(parents=True, exist_ok=True)

    if procid == 0:
        render_animation(
            blend_file, renders_dir, config=config, output_file=output_file, dry_run=True
        )
    else:
        start, end = split_ranges(fs, fe, jobs - 1)[procid - 1]
        render_animation(
            blend_file,
            renders_dir,
            config=config,
            frame_start=start,
            frame_end=end,
            output_file=None,
            dry_run=False,
        )

    if procid != 0:
        # transforms.db lives beside the outputs themselves (root, or
        # root/frames/ in this visionsim layout); drop them all
        for db in renders_dir.glob("**/transforms.db"):
            db.unlink(missing_ok=True)
    else:
        # The dry-run's debug blend rides in its tarball rather than being
        # listed in transfer_output_files, which the other procs never write.
        if output_file is not None and output_file.exists():
            renders_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(output_file), renders_dir / output_file.name)

    tar = subprocess.run(["tar", "-czf", f"renders_{procid:05d}.tar.gz", renders_dir], check=False)
    sys.exit(1 if tar.returncode else 0)


if __name__ == "__main__":
    tyro.cli(render)
