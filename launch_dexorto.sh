#!/bin/bash
# =====================================================================
# DEXORTO AI — Master Desktop Launcher
# Starts the background jarvis.py daemon and links with the iNiR widget
# =====================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export DISPLAY="${DISPLAY:-:0}"
export PULSE_SERVER="${PULSE_SERVER:-unix:/run/user/$(id -u)/pulse/native}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# 1. Activate Virtual Environment if present
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
fi

# 2. Select optimal Python interpreter (prefer host venv / system python3.12)
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

echo "=================================================="
echo "  DEXORTO AI // DESKTOP LAUNCHER"
echo "  Interpreter: $PYTHON_BIN (Python $PY_VER)"
echo "=================================================="

# 3. Enforce KDE KWin Rules so Dexorto NEVER affects Plasma panel / taskbar / pager
if command -v kwriteconfig5 >/dev/null 2>&1; then
    kwriteconfig5 --file kwinrulesrc --group "dexorto-widget" --key Description "Dexorto Companion Widget"
    kwriteconfig5 --file kwinrulesrc --group "dexorto-widget" --key wmclass "dexorto"
    kwriteconfig5 --file kwinrulesrc --group "dexorto-widget" --key wmclassmatch 1
    kwriteconfig5 --file kwinrulesrc --group "dexorto-widget" --key skiptaskbar true
    kwriteconfig5 --file kwinrulesrc --group "dexorto-widget" --key skiptaskbarrule 2
    kwriteconfig5 --file kwinrulesrc --group "dexorto-widget" --key skippager true
    kwriteconfig5 --file kwinrulesrc --group "dexorto-widget" --key skippagerrule 2
    kwriteconfig5 --file kwinrulesrc --group "dexorto-widget" --key noborder true
    kwriteconfig5 --file kwinrulesrc --group "dexorto-widget" --key noborderrule 2
    qdbus org.kde.KWin /KWin reconfigure >/dev/null 2>&1 || true
fi

# 4. Refresh macOS dock once if running old code without dexorto exemption
if [ ! -f /tmp/macos_dock_v2.flag ] && pgrep -f "macos_dock.py" >/dev/null 2>&1; then
    touch /tmp/macos_dock_v2.flag
    if [ -f "$HOME/launch-macos-dock.sh" ]; then
        echo "[*] Refreshing macOS dock with updated exemptions..."
        "$HOME/launch-macos-dock.sh" >/dev/null 2>&1 &
        sleep 0.3
    fi
fi

# 5. Clean up any stale background processes to free microphone & audio devices
touch "$SCRIPT_DIR/.exit_signal"
sleep 0.2
OLD_PROCS=$(pgrep -f "python.*(jarvis\.py|jarvis_inir_widget\.py|jarvis_widget\.py)" | grep -v "$$")
if [ -n "$OLD_PROCS" ]; then
    echo "[*] Cleaning up stale audio processes to free the microphone..."
    kill -9 $OLD_PROCS 2>/dev/null || kill $OLD_PROCS 2>/dev/null
    sleep 0.4
fi
rm -f "$SCRIPT_DIR/.exit_signal" 2>/dev/null || true

echo "[*] Launching DEXORTO AI Companion (Continuous Wake Word Active)..."
"$PYTHON_BIN" "$SCRIPT_DIR/jarvis_inir_widget.py" 2>&1 | tee "$SCRIPT_DIR/dexorto_runtime.log"

echo "[✓] DEXORTO offline."
