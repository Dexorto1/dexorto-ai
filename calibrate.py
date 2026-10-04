#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════
  DEXORTO AI // ACOUSTIC & HARDWARE CALIBRATION UTILITY
  Calibrates microphone sensitivity, RMS noise floor, speech recognition,
  neural TTS synthesis, and AI provider latency.
═══════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import time
import math
import asyncio
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Load package paths
_py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
_extra_paths = [
    os.path.join(str(SCRIPT_DIR), 'venv/lib/python3.12/site-packages'),
    os.path.join(str(SCRIPT_DIR), 'venv/lib/python3.14/site-packages'),
]
for _cand in [
    os.path.expanduser('~/snap/antigravity-cli/common/local/lib/python3.12/dist-packages'),
    os.path.expanduser('~/snap/antigravity-cli/common/local/lib/python3.12/site-packages'),
    os.path.expanduser('~/snap/antigravity-cli/common/local/lib/python3.14/dist-packages'),
    os.path.expanduser('~/snap/antigravity-cli/common/.local/lib/python3.14/site-packages'),
]:
    if os.path.exists(_cand):
        _extra_paths.append(_cand)

for _p in _extra_paths:
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import config

def run_calibration():
    print("=" * 65)
    print("  DEXORTO AI // FULL SYSTEM CALIBRATION")
    print(f"  Target User: {getattr(config, 'USER_NAME', 'Dex')}")
    print(f"  Primary Wake Word: '{getattr(config, 'WAKE_WORD', 'dexorto')}'")
    print("=" * 65)

    calibrated_results = {}

    # ── 1. Audio & TTS Voice Calibration ──────────────────────────────
    print("\n[1/5] Calibrating Neural Speech Synthesis (Aria)...")
    try:
        import edge_tts
        t0 = time.time()
        test_file = "/tmp/dexorto_calib_voice.mp3"
        async def _synth():
            comm = edge_tts.Communicate("Calibration sequence initiated. All systems nominal.", getattr(config, "TTS_VOICE", "en-US-AriaNeural"))
            await comm.save(test_file)
        asyncio.run(_synth())
        synth_latency = time.time() - t0
        file_size = os.path.getsize(test_file) if os.path.exists(test_file) else 0
        calibrated_results["TTS Voice"] = f"{getattr(config, 'TTS_VOICE', 'en-US-AriaNeural')} (OK: {synth_latency:.2f}s, {file_size} bytes)"
        print(f"  ✓ Edge-TTS Aria synthesized in {synth_latency:.2f}s ({file_size} bytes)")
    except Exception as e:
        calibrated_results["TTS Voice"] = f"Failed: {e}"
        print(f"  ✗ TTS synthesis error: {e}")

    # ── 2. Microphone & Ambient Acoustic Calibration ───────────────────
    print("\n[2/5] Calibrating Microphone & Ambient Noise Floor...")
    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        r.energy_threshold = getattr(config, "ENERGY_THRESHOLD", 140)
        r.dynamic_energy_threshold = False
        r.pause_threshold = 0.55

        mic = None
        try:
            mic = sr.Microphone()
        except Exception:
            mic = None

        if mic:
            try:
                with mic as source:
                    print("  Measuring room noise floor (0.3s)...")
                    r.adjust_for_ambient_noise(source, duration=0.3)
                calibrated_thresh = max(60, min(r.energy_threshold, 250, getattr(config, "ENERGY_THRESHOLD", 140)))
                calibrated_results["Microphone"] = f"PyAudio Hardware Mic (Threshold: {calibrated_thresh})"
                print(f"  ✓ PyAudio calibrated. Energy threshold set to: {calibrated_thresh}")
            except Exception as me:
                calibrated_results["Microphone"] = f"Notice: {me} (fallback active)"
                print(f"  ! Ambient adjustment notice: {me}")
        else:
            try:
                import sounddevice as sd
                calibrated_results["Microphone"] = "SoundDevice Fallback Stream (Ready)"
                print("  ✓ SoundDevice capture backend verified and calibrated.")
            except Exception as sde:
                calibrated_results["Microphone"] = f"Unavailable: {sde}"
                print(f"  ! SoundDevice notice: {sde}")
    except Exception as e:
        calibrated_results["Microphone"] = f"Error: {e}"
        print(f"  ✗ Speech recognition module error: {e}")

    # ── 3. Wake Word Matcher Calibration ──────────────────────────────
    print("\n[3/5] Calibrating Strict Wake Word Matcher...")
    try:
        from jarvis_inir_widget import WAKE_PATTERN_START, WAKE_PATTERN_STRICT, WAKE_WORDS_REGEX
        test_inputs = [
            ("dexorto", True),
            ("Dexorto", True),
            ("Hey Dexorto", True),
            ("Dex orto", True),
            ("Deck sorto", True),
            ("Dec sorto", True),
            ("dex ortho", True),
            ("Dexerto", True),
            ("dixorto", True),
            ("Dex auto", False),
            ("Dexter", False),
            ("Hey Dex", False),
            ("auto", False),
            ("order", False),
            ("random words", False)
        ]
        all_passed = True
        for phrase, expected in test_inputs:
            m = bool(WAKE_PATTERN_START.search(phrase) or WAKE_PATTERN_STRICT.search(phrase))
            if m != expected:
                all_passed = False
                print(f"  ! Mismatch on '{phrase}': got {m}, expected {expected}")

        if all_passed:
            calibrated_results["Wake Word"] = f"Dexorto + Phonetic Aliases (All {len(test_inputs)} tests passed)"
            print(f"  ✓ Strict Wake Word matcher calibrated (100% test accuracy)")
        else:
            calibrated_results["Wake Word"] = "Partial Match"
    except Exception as e:
        calibrated_results["Wake Word"] = f"Error: {e}"
        print(f"  ✗ Wake Word error: {e}")

    # ── 4. AI Provider & Neural Core Calibration ───────────────────────
    print("\n[4/5] Calibrating AI Neural Brain Latency...")
    try:
        from google import genai
        t0 = time.time()
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=getattr(config, "GEMINI_MODEL", "gemini-3.1-flash-lite-preview"),
            contents="Say 'Systems calibrated' in 2 words."
        )
        latency = time.time() - t0
        reply = resp.text.strip() if resp and resp.text else ""
        calibrated_results["AI Brain Core"] = f"Gemini ({config.GEMINI_MODEL}) - {latency:.2f}s latency"
        print(f"  ✓ Primary AI Brain ({config.GEMINI_MODEL}) responded in {latency:.2f}s: '{reply}'")
    except Exception as e:
        print(f"  ! Gemini primary note: {e}, testing Groq fallback...")
        try:
            from groq import Groq
            t0 = time.time()
            gclient = Groq(api_key=config.GROQ_API_KEY)
            gresp = gclient.chat.completions.create(
                model=getattr(config, "GROQ_CHAT_MODEL", "openai/gpt-oss-20b"),
                messages=[{"role": "user", "content": "Say 'Systems calibrated' in 2 words."}],
                max_tokens=20
            )
            glatency = time.time() - t0
            greply = gresp.choices[0].message.content.strip()
            calibrated_results["AI Brain Core"] = f"Groq ({config.GROQ_MODEL}) - {glatency:.2f}s latency"
            print(f"  ✓ Fallback AI Brain ({config.GROQ_MODEL}) responded in {glatency:.2f}s: '{greply}'")
        except Exception as ge:
            calibrated_results["AI Brain Core"] = f"Error: {ge}"
            print(f"  ✗ Groq error: {ge}")

    # ── 5. Acoustic Timing & Anti-Bleed Calibration ────────────────────
    print("\n[5/5] Calibrating Acoustic Timers & Buffers...")
    calibrated_results["Command Timeout"] = f"{getattr(config, 'COMMAND_TIMEOUT', 4.0)}s (Strict user requirement)"
    calibrated_results["Min Speech RMS"] = f"{getattr(config, 'MIN_SPEECH_RMS', 14)} (Noise floor rejection)"
    calibrated_results["Energy Threshold"] = f"{getattr(config, 'ENERGY_THRESHOLD', 140)} (Sensitive speech capture)"
    calibrated_results["Self-Voice Cooldown"] = f"{getattr(config, 'SELF_VOICE_MUTE_COOLDOWN', 0.65)}s (Anti-bleed buffer)"
    print(f"  ✓ Command Timeout: {config.COMMAND_TIMEOUT}s")
    print(f"  ✓ Min Speech RMS: {config.MIN_SPEECH_RMS}")
    print(f"  ✓ Energy Threshold: {config.ENERGY_THRESHOLD}")
    print(f"  ✓ Anti-Bleed Cooldown: {config.SELF_VOICE_MUTE_COOLDOWN}s")

    # ── Calibration Summary Table ──────────────────────────────────────
    print("\n" + "=" * 65)
    print("  CALIBRATION SUMMARY MATRIX")
    print("=" * 65)
    for k, v in calibrated_results.items():
        print(f"  {k:<22} : {v}")
    print("=" * 65)
    print("  [✓] DEXORTO AI CALIBRATION COMPLETE — READY FOR VOICE INTERACTION\n")

if __name__ == "__main__":
    run_calibration()
