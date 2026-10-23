#!/bin/bash
set -xeuo pipefail

# Usage: render_multicam.sh blendfile --rows=<N> --cols=<M> --spacing=<d> --procid=<n> --jobs=<N*M*(K+1)> --frame-start=<n> --frame-end=<n> [--config.camera-offset="x y z"] [renders_dir] [-- extra_args...]
#
#   Renders an animation from an N×M grid of cameras on the XY plane.
#   Total jobs = N×M×(K+1), where K = number of frame subranges per camera.
#   - procid maps to camera (row, col) and subrange sub_idx:
#       camera_idx = procid / (K+1)
#       sub_idx    = procid % (K+1)
#   - sub_idx == 0: dry-run (full frame range, with camera offset)
#   - sub_idx > 0:  actual render of a frame subrange
#   Camera positions are centered at the origin.  Position (0,0) is the grid center.
#   --config.camera-offset is relative to the grid center.
#   renders_dir defaults to "renders/" if not provided.
#   Use -- to pass extra arguments verbatim to vsim.

blendfile=""
procid=""
total_jobs=""
rows=""
cols=""
spacing=""
frame_start=""
frame_end=""
camera_offset=""
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
        --rows=*)
            rows="${1#*=}"
            shift
            ;;
        --cols=*)
            cols="${1#*=}"
            shift
            ;;
        --spacing=*)
            spacing="${1#*=}"
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
        --config.camera-offset=*)
            camera_offset="${1#*=}"
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

if [[ -z "$blendfile" || -z "$procid" || -z "$total_jobs" || -z "$rows" || -z "$cols" || -z "$spacing" || -z "$frame_start" || -z "$frame_end" ]]; then
    echo "Usage: $0 blendfile --rows=<N> --cols=<M> --spacing=<d> --procid=<n> --jobs=<N*M*(K+1)> --frame-start=<n> --frame-end=<n> [--config.camera-offset=\"x y z\"] [renders_dir] [-- extra_args...]" >&2
    exit 1
fi

# Total cameras = rows * cols
total_cameras=$(( rows * cols ))

# Validate that total_jobs is divisible by total_cameras (K must be integer)
if (( total_jobs % total_cameras != 0 )); then
    echo "Error: --jobs ($total_jobs) must be a multiple of --rows×--cols ($total_cameras)" >&2
    exit 1
fi

# K = number of actual render subranges per camera
# total_jobs = total_cameras * (K + 1)
# K = total_jobs / total_cameras - 1
subranges_per_camera=$(( total_jobs / total_cameras ))
actual_jobs=$(( subranges_per_camera - 1 ))

if (( actual_jobs < 1 )); then
    echo "Error: --jobs ($total_jobs) must be at least 2×--rows×--cols ($(( 2 * total_cameras ))) to have at least 1 render subrange per camera" >&2
    exit 1
fi

# Derive camera index and subrange index from procid
camera_idx=$(( procid / subranges_per_camera ))
sub_idx=$(( procid % subranges_per_camera ))

# Derive grid position
row=$(( camera_idx / cols ))
col=$(( camera_idx % cols ))

# Compute camera offset for this grid cell (grid centered at origin)
# x = (col - (cols-1)/2) * spacing
# y = (row - (rows-1)/2) * spacing
# z = 0
# Use awk for floating-point arithmetic (more portable than bc)
center_col=$(awk "BEGIN { printf \"%.6f\", ($cols - 1) / 2 }")
center_row=$(awk "BEGIN { printf \"%.6f\", ($rows - 1) / 2 }")
offset_x=$(awk "BEGIN { printf \"%.6f\", ($col - $center_col) * $spacing }")
offset_y=$(awk "BEGIN { printf \"%.6f\", ($row - $center_row) * $spacing }")
offset_z="0"

# Apply global camera offset if provided
if [[ -n "$camera_offset" ]]; then
    # camera_offset is "x y z"
    read -r global_ox global_oy global_oz <<< "$camera_offset"
    offset_x=$(awk "BEGIN { printf \"%.6f\", $offset_x + $global_ox }")
    offset_y=$(awk "BEGIN { printf \"%.6f\", $offset_y + $global_oy }")
    offset_z=$(awk "BEGIN { printf \"%.6f\", $offset_z + $global_oz }")
fi

# Frame subranging
total_frames=$(( frame_end - frame_start + 1 ))
range_size=$(( total_frames / actual_jobs ))
remainder=$(( total_frames % actual_jobs ))

# Package renders directory (format to %05d)
printf -v padded_row '%05d' "$row"
printf -v padded_col '%05d' "$col"
printf -v padded_sub '%05d' "$sub_idx"
printf -v padded_procid '%05d' "$procid"

camera_dir=${renders_dir}/${padded_row}_${padded_col}
cmd=(vsim blender.render-animation "$blendfile" "$camera_dir")

if [[ "$sub_idx" -eq 0 ]]; then
    # Dry-run with full frame range, camera offset, and extra args
    "${cmd[@]}" --dry-run --config.camera-offset=${offset_x} ${offset_y} ${offset_z} "${extra_args[@]}"
else
    # Calculate start and end for this subrange
    idx=$(( sub_idx - 1 ))
    start=$(( frame_start + idx * range_size + (idx < remainder ? idx : remainder) ))
    end=$(( start + range_size - 1 + (idx < remainder ? 1 : 0) ))

    "${cmd[@]}" --frame-start="$start" --frame-end="$end" --config.camera-offset=${offset_x} ${offset_y} ${offset_z} "${extra_args[@]}"

    # Remove transforms.db from renders directory
    rm -f "$camera_dir/transforms.db"
fi

tar -czvf "renders_${padded_procid}.tar.gz" "$camera_dir"
