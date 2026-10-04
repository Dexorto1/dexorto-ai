#!/bin/bash
# DEXORTO AI — iNiR Music Player Widget Launcher
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "venv/bin/python" ]; then
    ./venv/bin/python jarvis_inir_widget.py "$@"
else
    python3 jarvis_inir_widget.py "$@"
fi
