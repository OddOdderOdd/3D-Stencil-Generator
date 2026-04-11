#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  3D Stencil Generator — Setup & Launch (CachyOS / Arch Linux)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
MAIN="$SCRIPT_DIR/main.py"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🎨  3D Stencil Generator"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Python check ───────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "❌  python3 not found.  Install: sudo pacman -S python"
    exit 1
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✓  Python $PY_VER"

# ── 2. System packages (faster than pip on Arch) ──────────────────────────────
install_if_missing() {
    local pkg="$1"; local py_test="$2"
    if python3 -c "$py_test" 2>/dev/null; then
        echo "✓  $pkg (system)"
    elif pacman -Qi "$pkg" &>/dev/null 2>&1; then
        echo "✓  $pkg (system, already installed)"
    else
        echo "→  Installing $pkg via pacman…"
        sudo pacman -S --noconfirm "$pkg"
    fi
}

install_if_missing python-pyqt5 "import PyQt5"
install_if_missing python-opencv "import cv2"
install_if_missing python-numpy  "import numpy"

# ── 3. Virtual environment (for packages not in Arch repos) ───────────────────
if [ ! -d "$VENV" ]; then
    echo ""
    echo "→  Creating venv at $VENV …"
    python3 -m venv --system-site-packages "$VENV"
fi

# shellcheck source=/dev/null
source "$VENV/bin/activate"

echo ""
echo "→  Installing pip packages…"
pip install --quiet --upgrade pip
pip install --quiet \
    "shapely>=2.0.0" \
    "trimesh>=4.0.0" \
    "numpy-stl>=3.0.0" \
    "mapbox_earcut" \
    "manifold3d>=2.4.0" \
    "scipy>=1.10.0" \
    "Pillow>=10.0.0"

# Fallbacks if system PyQt5 / opencv weren't available
python3 -c "import PyQt5" 2>/dev/null || pip install --quiet PyQt5
python3 -c "import cv2"   2>/dev/null || pip install --quiet opencv-python

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅  Setup complete — launching…"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 4. Display server detection ───────────────────────────────────────────────
if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    export QT_QPA_PLATFORM=wayland
elif [ -n "${DISPLAY:-}" ]; then
    export QT_QPA_PLATFORM=xcb
fi

exec python3 "$MAIN" "$@"
