#!/bin/bash
# Script logic lives in render_multicam.py. Run it with uv so the project
# environment (which provides visionsim/tyro) is in scope; fall back to
# ambient python3 in environments like the execute-node container, where
# those deps are already installed system-wide.
d="$(dirname "$(readlink -f "$0")")"
if command -v uv >/dev/null 2>&1 && [[ -f "$d/pyproject.toml" ]]; then
    exec uv run --project "$d" python "$d/executables/render_multicam.py" "$@"
fi
exec python3 "$d/executables/render_multicam.py" "$@"
