#!/bin/bash
# =====================================================================
# DEXORTO AI — Master System & Acoustic Calibration
# =====================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
fi

PYTHON_BIN=""
for cand in "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/venv/bin/python3" "/usr/bin/python3.12" "/usr/bin/python3" "python3"; do
    if [ -x "$cand" ] || command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c "import sys" >/dev/null 2>&1; then
            PYTHON_BIN="$cand"
            break
        fi
    fi
done
[ -z "$PYTHON_BIN" ] && PYTHON_BIN="python3"

PY_VER=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "3.12")
if [ "$PY_VER" = "3.12" ]; then
    export PYTHONPATH="$SCRIPT_DIR/venv/lib/python3.12/site-packages:$HOME/snap/antigravity-cli/common/local/lib/python3.12/dist-packages:$SCRIPT_DIR:${PYTHONPATH:-}"
else
    export PYTHONPATH="$HOME/snap/antigravity-cli/common/local/lib/python3.14/dist-packages:$HOME/snap/antigravity-cli/common/.local/lib/python3.14/site-packages:$SCRIPT_DIR/venv/lib/python3.12/site-packages:$SCRIPT_DIR:${PYTHONPATH:-}"
fi

"$PYTHON_BIN" "$SCRIPT_DIR/calibrate.py"
