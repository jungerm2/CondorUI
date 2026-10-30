#!/usr/bin/env python3
"""Playblast one blend-file as one HTCondor proc, through visionsim.

A playblast is fast, so a batch of scenes is submitted as a single cluster with
one proc per scene: the submit description supplies the per-proc blend through
item data (``$(input_name)``) and transfers only that file (``$(input_uri)``).
Each proc writes ``renders_dir/playblast/`` (video or PNGs) and bundles it as
``playblast_<procid>.tar.gz``.

Frame arguments use the blend-file's ORIGINAL numbering; the keyframe
multiplier is applied here as well as in the config, mirroring render.py.

All --config.* flags come from visionsim's own RenderConfig. Only the colour
pass is produced; include_* flags other than frames are ignored by visionsim.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import tyro
from visionsim.cli.blender import render_playblast
from visionsim.simulate.config import RenderConfig

FRAME_LIMIT = 1_048_574  # Blender's hard frame-number limit


def playblast(
    blend_file: Path,
    /,
    procid: int,
    config: RenderConfig,
    frame_start: int | None = None,
    frame_end: int | None = None,
    output_file: Path | None = None,
    renders_dir: Path = Path("renders"),
    video: bool = True,
) -> None:
    """Playblast one blend-file via visionsim.

    Args:
        blend_file: Path to the blend-file to playblast.
        procid: HTCondor ProcId, used only for the tarball name.
        config: Render configuration; same fields and flags as
            ``vsim blender.render-playblast``.
        frame_start: Start frame (original blend-file numbering); omit to use
            the .blend's own range.
        frame_end: End frame (original blend-file numbering); omit to use the
            .blend's own range.
        output_file: If set, write the configured blend-file here for
            troubleshooting; it is bundled into this proc's tarball.
        renders_dir: Directory holding the ``playblast/`` output for this proc.
        video: Encode an ``.mp4``; false writes a PNG sequence plus transforms.db.
    """
    if frame_end is not None and frame_end >= FRAME_LIMIT:
        sys.exit(f"error: --frame-end {frame_end} reaches Blender's {FRAME_LIMIT} frame limit")

    fs, fe = frame_start, frame_end
    k = config.keyframe_multiplier
    if k != 1.0:
        if fs is None or fe is None:
            sys.exit("error: --config.keyframe-multiplier needs an explicit frame range")
        if k <= 0:
            sys.exit(f"error: --config.keyframe-multiplier must be positive, got {k}")
        fs, fe = round(fs * k), round((fe + 1) * k) - 1
        if fe < fs:
            sys.exit(f"error: keyframe-multiplier {k} produces an empty frame range")
        if fe >= FRAME_LIMIT:
            sys.exit(
                f"error: keyframe-multiplier {k} puts frame end at {fe}, "
                f"beyond Blender's {FRAME_LIMIT} frame limit"
            )
        print(f"keyframe-multiplier={k}: playblasting scaled frame range [{fs}, {fe}]")

    if output_file is not None:
        output_file.parent.mkdir(parents=True, exist_ok=True)

    render_playblast(
        blend_file,
        renders_dir,
        config=config,
        frame_start=fs,
        frame_end=fe,
        video=video,
        output_file=output_file,
    )

    if output_file is not None and output_file.exists():
        renders_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(output_file), renders_dir / output_file.name)

    tar = subprocess.run(
        ["tar", "-czf", f"playblast_{procid:05d}.tar.gz", renders_dir], check=False
    )
    sys.exit(1 if tar.returncode else 0)


if __name__ == "__main__":
    tyro.cli(playblast)
