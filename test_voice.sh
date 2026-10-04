#!/bin/bash
# =====================================================================
# DEXORTO AI — Aria Voice Diagnostic Test
# =====================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export DISPLAY="${DISPLAY:-:0}"
export PULSE_SERVER="${PULSE_SERVER:-unix:/run/user/$(id -u)/pulse/native}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# 1. Activate Virtual Environment
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

echo "=================================================="
echo "  DEXORTO AI // ARIA NEURAL VOICE TEST"
echo "  Interpreter: $PYTHON_BIN (Python $PY_VER)"
echo "=================================================="

echo "[*] Generating Aria voice sample..."
"$PYTHON_BIN" -c "
import sys, os, asyncio
try:
    import edge_tts
    async def synth():
        text = 'Hello Dex! This is Aria, your Dexorto AI companion. All voice recognition and speech systems are fully operational.'
        comm = edge_tts.Communicate(text, 'en-US-AriaNeural')
        await comm.save('/tmp/dexorto_voice_test.mp3')
        print('[✓] Audio generated successfully: /tmp/dexorto_voice_test.mp3 (' + str(os.path.getsize('/tmp/dexorto_voice_test.mp3')) + ' bytes)')
    asyncio.run(synth())
except Exception as e:
    print('[!] Voice generation error:', e)
"

echo "[*] Playing audio through speakers..."
PLAYED=0

for player in ffplay mpv paplay pw-play cvlc; do
    if command -v "$player" >/dev/null 2>&1; then
        echo "[*] Playing with $player..."
        if [ "$player" = "ffplay" ]; then
            ffplay -nodisp -autoexit -loglevel quiet /tmp/dexorto_voice_test.mp3
        elif [ "$player" = "mpv" ]; then
            mpv --no-video --really-quiet /tmp/dexorto_voice_test.mp3
        elif [ "$player" = "paplay" ]; then
            paplay /tmp/dexorto_voice_test.mp3
        elif [ "$player" = "pw-play" ]; then
            pw-play /tmp/dexorto_voice_test.mp3
        elif [ "$player" = "cvlc" ]; then
            cvlc --play-and-exit /tmp/dexorto_voice_test.mp3
        fi
        PLAYED=1
        break
    fi
done

if [ "$PLAYED" -eq 0 ]; then
    echo "[*] Attempting playback via pygame.mixer..."
    "$PYTHON_BIN" -c "
import pygame, time
try:
    pygame.mixer.init()
    pygame.mixer.music.load('/tmp/dexorto_voice_test.mp3')
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        time.sleep(0.04)
    print('[✓] Playback complete.')
except Exception as e:
    print('[!] Playback notice:', e)
"
fi

echo "[✓] Voice test finished."
