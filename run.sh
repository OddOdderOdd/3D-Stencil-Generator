#!/usr/bin/env bash
# 3D Stencil Generator — one-command setup + launch
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🎨  3D Stencil Generator"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ python3 not found. Install Python 3.11+ and rerun."
  exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✓ Python $PY_VER"

if [ ! -d "$VENV" ]; then
  echo "→ Creating virtual environment: $VENV"
  python3 -m venv "$VENV"
fi

# shellcheck source=/dev/null
source "$VENV/bin/activate"

echo "→ Installing/Updating app dependencies (editable install)…"
python -m pip install --upgrade pip
python -m pip install -e "$SCRIPT_DIR"

echo "✅ Setup complete — launching GUI"

if [ -n "${WAYLAND_DISPLAY:-}" ]; then
  export QT_QPA_PLATFORM=wayland
elif [ -n "${DISPLAY:-}" ]; then
  export QT_QPA_PLATFORM=xcb
fi

exec python "$SCRIPT_DIR/main.py" "$@"
