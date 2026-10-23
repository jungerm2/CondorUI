#!/bin/bash
set -xeuo pipefail

# Usage: render.sh blendfile --procid=<n> --jobs=<n> --frame-start=<n> --frame-end=<n> [renders_dir] [-- extra_args...]
#   renders_dir defaults to "renders/" if not provided
#   Use -- to pass extra arguments verbatim to vsim

blendfile=""
procid=""
total_jobs=""
frame_start=""
frame_end=""
renders_dir="renders/"
extra_args=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --)
            shift
            extra_args+=("$@")
            break
            ;;
        --procid=*)
            procid="${1#*=}"
            shift
            ;;
        --jobs=*)
            total_jobs="${1#*=}"
            shift
            ;;
        --frame-start=*)
            frame_start="${1#*=}"
            shift
            ;;
        --frame-end=*)
            frame_end="${1#*=}"
            shift
            ;;
        --*)
            extra_args+=("$1")
            shift
            ;;
        *)
            if [[ -z "$blendfile" ]]; then
                blendfile="$1"
            elif [[ "$renders_dir" == "renders/" ]]; then
                renders_dir="$1"
            else
                extra_args+=("$1")
            fi
            shift
            ;;
    esac
done

if [[ -z "$blendfile" || -z "$procid" || -z "$total_jobs" || -z "$frame_start" || -z "$frame_end" ]]; then
    echo "Usage: $0 blendfile --procid=<n> --jobs=<n> --frame-start=<n> --frame-end=<n> [renders_dir] [-- extra_args...]" >&2
    exit 1
fi

# Calculate subrange size: split [frame_start, frame_end] into (total_jobs - 1) subranges
actual_jobs=$(( total_jobs - 1 ))
total_frames=$(( frame_end - frame_start + 1 ))
range_size=$(( total_frames / actual_jobs ))
remainder=$(( total_frames % actual_jobs ))

cmd=(vsim blender.render-animation "$blendfile" "$renders_dir")

if [[ "$procid" -eq 0 ]]; then
    # Job 0: dry-run with full range and extra args
    "${cmd[@]}" --dry-run "${extra_args[@]}"
else
    # Calculate start and end for this job
    idx=$(( procid - 1 ))
    start=$(( frame_start + idx * range_size + (idx < remainder ? idx : remainder) ))
    end=$(( start + range_size - 1 + (idx < remainder ? 1 : 0) ))

    "${cmd[@]}" --frame-start="$start" --frame-end="$end" "${extra_args[@]}"

    # Remove transforms.db from renders directory
    rm -f "$renders_dir/transforms.db"
fi

# Package renders directory (format to %05d)
printf -v padded '%05d' "$procid"
tar -czvf "renders_${padded}.tar.gz" "$renders_dir"

