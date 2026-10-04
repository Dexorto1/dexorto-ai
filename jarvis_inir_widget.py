#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════
  DEXORTO AI // DUAL-MODE COMPANION & TERMINAL
  Features:
   - Dual Window Mode:
       * Fullscreen Kitty-Style Black Terminal Application (F11 / 🗗)
       * Compact Floating Companion Widget (360×500) for non-fullscreen tasks (🗖)
   - Window Minimize [—] Button with background continuous wake-word listening
   - Movie-Accurate Iron Man Mark-85 Arc Reactor Holographic Core HUD (pulsing iris,
     rotating targeting crosshairs, dynamic reactive acoustic equalizer waveforms)
   - Interactive Feature Settings Panel [⚙] (Hindi Mode, Barge-in, JSON Filter, etc.)
   - Continuous Wake-Word Detection ("dexorto") in background with Wake Barge-In
   - Multilingual / Auto Language Whisper Turbo (Native Hindi & English comprehension)
   - Strict Color Palette: Black, Red, Green, and Crisp White
   - Full Multi-Line Response Stream (No truncation, smooth scrolling)
   - Browser Tab Reuse (Does not open duplicate tabs for songs/inboxes)
   - Robust X11 EWMH: skips panel taskbar & desktop pager
   - Seamless IPC connection to jarvis.py daemon with standalone fallback
═══════════════════════════════════════════════════════════════════════════
"""

import sys
import os
import gc
import re
import io
import json
import time
from datetime import datetime
import math
import asyncio
import tempfile
import threading
import subprocess
import urllib.request
import shutil
from pathlib import Path
import wave
import struct
import ctypes
from ctypes import (
    c_ulong, c_int, c_long, c_char_p, c_void_p, c_uint, POINTER, byref, cast
)

# Add parent directory and local package directories to sys.path before third-party imports
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

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

for _p in reversed(_extra_paths):
    if os.path.exists(_p):
        if _p in sys.path:
            sys.path.remove(_p)
        sys.path.insert(0, _p)

import config
import requests
import pygame
import pygame.gfxdraw
from jarvis_ipc import JarvisIPCClient
from browser_controller import BrowserController
from assistant_tools import (
    ASSISTANT_TOOLS, GEMINI_TOOLS, ToolExecutor, TaskManager, is_specific_command,
    format_short_clean_response, filter_json_to_human_words, parse_hindi_command_intent,
    change_voice, HindiTutor, PersonaManager, set_mic_sensitivity,
    MemoryManager, get_effective_system_prompt, manage_memory
)

# Attempt Edge-TTS import
try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

# Attempt Google GenAI import
try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

# Attempt Groq import
try:
    from groq import Groq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False

# Attempt SpeechRecognition import
try:
    import speech_recognition as sr
    HAS_SR = True
except ImportError:
    HAS_SR = False

# Attempt SoundDevice import for robust fallback microphone capture
try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except Exception:
    HAS_SOUNDDEVICE = False

# Attempt NumPy & WebRTC VAD
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import webrtcvad
    HAS_WEBRTCVAD = True
except ImportError:
    HAS_WEBRTCVAD = False

# ── Whisper Hallucination Filter ─────────────────────────
WHISPER_HALLUCINATIONS = {
    "thank you", "thank you.", "thank you for watching", "thank you for watching.",
    "thanks for watching", "thanks for watching.", "please subscribe", "like and subscribe",
    "subtitles by", "amara.org", "bye", "bye.", "goodbye", "goodbye.", "you", "you.",
    "[music]", "[applause]", "[silence]", "...", "--", "thank you so much",
    "thank you very much", "see you next time", "see you later",
    "dexorto ai assistant", "dexorto ai", "bilingual assistant fluent in english and hindi",
    "spotify, music, gaana bajao", "spotify", "music", "gaana bajao", "terminal kholo",
    "mausam kaisa hai", "teach hindi"
}

HALLUCINATION_SUBSTRINGS = (
    "thank you for watching", "thanks for watching", "please subscribe",
    "like and subscribe", "subtitles by", "amara.org", "see you next time",
    "see you later", "dexorto ai assistant", "bilingual assistant fluent",
    "spotify, music, gaana bajao"
)

def is_whisper_hallucination(text: str) -> bool:
    """Detects Whisper hallucinations, repetitive decoding loops, and prompt echoes."""
    if not text:
        return True
    c = text.strip().lower().strip(".,?!:;\"' ")
    if not c or len(c) < 2:
        return True
    if c in WHISPER_HALLUCINATIONS:
        return True
    if any(sub in c for sub in HALLUCINATION_SUBSTRINGS):
        return True
    # Strip bracketed tokens e.g. [music], (applause)
    no_brackets = re.sub(r'\[.*?\]|\(.*?\)', '', c).strip(".,?!:;\"' ")
    if not no_brackets:
        return True
    if no_brackets in WHISPER_HALLUCINATIONS:
        return True
    if any(sub in no_brackets for sub in HALLUCINATION_SUBSTRINGS):
        return True
    # Repeated word loop check: e.g. "word word word"
    words = no_brackets.split()
    if len(words) >= 3 and len(set(words)) == 1:
        return True
    return False

# ── Strict Wake Word Matchers ─────────────────────────────
WAKE_WORDS_REGEX = (
    r'(?:'
    r'dexorto|dex[-_\s]*orto|dex[-_\s]*ortho|'
    r'deck[-_\s]*sorto|dec[-_\s]*sorto|decksorto|decsorto|'
    r'dexerto|dex[-_\s]*erto|dixorto|dix[-_\s]*orto'
    r')'
)
WAKE_PREFIXES_REGEX = r'(?:(?:hey|hi|ok|hello|yo|suno|listen|arre)\s+)?'

WAKE_PATTERN_START = re.compile(
    r'^' + WAKE_PREFIXES_REGEX + WAKE_WORDS_REGEX + r'\b[,\s\.\?!-]*(.*)$',
    re.IGNORECASE
)
WAKE_PATTERN_END = re.compile(
    r'^(.*?)[,\s]+' + WAKE_PREFIXES_REGEX + WAKE_WORDS_REGEX + r'[\s\.\?!]*$',
    re.IGNORECASE
)
WAKE_PATTERN_STRICT = re.compile(
    r'\b' + WAKE_PREFIXES_REGEX + WAKE_WORDS_REGEX + r'\b',
    re.IGNORECASE
)

def is_audio_silent(raw_bytes: bytes, min_rms: int = 24) -> bool:
    """Checks if audio chunk is pure room silence or low-level noise floor with peak chunk energy detection."""
    if not raw_bytes or len(raw_bytes) < 320:
        return True

    # 1. High-speed C-extension calculation via audioop
    try:
        import audioop
        # 16-bit mono 16kHz: 1600 samples = 3200 bytes = 100ms
        chunk_bytes = 3200
        if len(raw_bytes) >= chunk_bytes:
            peak_rms = 0
            for i in range(0, len(raw_bytes) - chunk_bytes + 1, chunk_bytes):
                sub_rms = audioop.rms(raw_bytes[i:i + chunk_bytes], 2)
                if sub_rms > peak_rms:
                    peak_rms = sub_rms
            return bool(peak_rms < min_rms)
        else:
            return bool(audioop.rms(raw_bytes, 2) < min_rms)
    except Exception:
        pass

    # 2. NumPy array vectorization fallback
    if HAS_NUMPY:
        try:
            samples = np.frombuffer(raw_bytes, dtype=np.int16)
            if len(samples) == 0:
                return True
            chunk_size = 1600  # 100ms at 16kHz
            if len(samples) >= chunk_size:
                chunks = len(samples) // chunk_size
                peak_rms = 0.0
                for i in range(chunks):
                    c = samples[i * chunk_size:(i + 1) * chunk_size]
                    c_rms = np.sqrt(np.mean(c.astype(np.float32)**2))
                    if c_rms > peak_rms:
                        peak_rms = c_rms
                return bool(peak_rms < min_rms)
            else:
                rms = np.sqrt(np.mean(samples.astype(np.float32)**2))
                return bool(rms < min_rms)
        except Exception:
            pass

    # 3. Pure Python struct fallback (microsecond speed)
    try:
        import struct
        import math
        n_samples = len(raw_bytes) // 2
        if n_samples == 0:
            return True
        chunk_samples = 1600
        fmt = f"<{n_samples}h"
        samples = struct.unpack(fmt, raw_bytes[:n_samples * 2])
        if n_samples >= chunk_samples:
            peak_rms = 0
            for i in range(0, n_samples - chunk_samples + 1, chunk_samples):
                sub = samples[i:i + chunk_samples]
                sub_rms = math.isqrt(sum(s * s for s in sub) // chunk_samples)
                if sub_rms > peak_rms:
                    peak_rms = sub_rms
            return bool(peak_rms < min_rms)
        else:
            total_rms = math.isqrt(sum(s * s for s in samples) // n_samples)
            return bool(total_rms < min_rms)
    except Exception:
        pass

    # Safe default: return True (silent) to prevent false wake loops on failure
    return True

def clean_speech_output(text: str) -> str:
    """Prepares text for realistic, natural spoken audio synthesis."""
    if not text:
        return ""
    return format_short_clean_response(text, max_sentences=2)


# ══════════════════════════════════════════════════════════
# Minimal Gray / Matte Slate & Tech Cyan Palette (JARVIS UI)
# ══════════════════════════════════════════════════════════
class Palette:
    # Minimal Gray / Matte Slate & Carbon Canvas (from reference UI)
    BG = (7, 11, 16)                   # Deep minimal slate-carbon canvas (#070B10)
    CARD_BG = (13, 20, 29)             # Matte dark slate card container (#0D141D)
    CARD_BG_ELEVATED = (17, 26, 38)    # Elevated card / stat box (#111A26)
    CARD_BORDER = (24, 38, 52)         # Refined tech border (#182634)
    CARD_BORDER_LIGHT = (36, 54, 74)   # Subtle highlight border
    CARD_HOVER = (20, 31, 45)          # Card hover state

    # Tech Cyan & Electric Blue accents (from reference UI)
    CYAN = (0, 210, 255)               # Vibrant HUD electric cyan (#00D2FF)
    CYAN_MUTED = (0, 150, 200)         # Muted cyan for secondary accents
    CYAN_DARK = (10, 32, 46)           # Translucent cyan panel tint
    CYAN_GLOW = (0, 210, 255, 60)      # Ambient ring glow

    # Steel Gray & Crisp Typography
    WHITE = (240, 245, 250)            # Crisp off-white heading (#F0F5FA)
    WHITE_MUTED = (160, 175, 195)      # Silver slate secondary text (#A0AFC3)
    WHITE_DIM = (85, 105, 125)         # Dim steel divider/subtext (#55697D)
    STAT_LABEL = (100, 120, 142)       # Minimal label steel (#64788E)

    # Status & Feedback Colors
    GREEN = (0, 230, 130)              # Online / Ready emerald (#00E682)
    GREEN_HOVER = (50, 255, 160)
    GREEN_DARK = (10, 36, 24)          # Green tint
    GREEN_PULSE = (0, 230, 130, 75)
    RED = (255, 68, 85)                # Listening / Recording crimson (#FF4455)
    RED_HOVER = (255, 95, 110)
    RED_DARK = (42, 14, 20)            # Red tint
    RED_PULSE = (255, 68, 85, 75)
    GOLD = (255, 195, 18)              # Accent gold (#FFC312)
    HUD_BORDER = (24, 38, 52)          # Refined border

    # Terminal / UI Prompts
    TERM_GREEN = (0, 230, 130)
    TERM_CURSOR = (0, 210, 255, 180)

    # Chat Bubbles (minimal gray / slate)
    MSG_USER_BG = (18, 30, 44)         # User message card (#121E2C)
    MSG_USER_BORDER = (28, 48, 70)
    MSG_AI_BG = (12, 18, 26)           # AI message card (#0C121A)
    MSG_AI_BORDER = (22, 34, 48)
    MSG_SYS_BG = (10, 14, 20)          # System message card

    # Input Box & Controls
    INPUT_BG = (9, 14, 21)             # Bottom input pill (#090E15)
    INPUT_BORDER = (24, 38, 52)        # Input outline
    INPUT_FOCUSED = (0, 180, 230)      # Input active glow
    SEND_BTN = (0, 210, 255)           # Electric cyan send button
    SEND_BTN_HOVER = (60, 225, 255)

    # Status Bar
    STATUS_BG = (6, 9, 14)
    STATUS_BORDER = (18, 28, 38)


# ══════════════════════════════════════════════════════════
# X11 Window Manager Integration
# (Prevents interference with KDE panel and dock in both modes)
# ══════════════════════════════════════════════════════════
class XClientMessageEvent(ctypes.Structure):
    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", c_int),
        ("display", c_void_p),
        ("window", c_ulong),
        ("message_type", c_ulong),
        ("format", c_int),
        ("data", c_long * 5)
    ]


class XEvent(ctypes.Union):
    _fields_ = [
        ("type", c_int),
        ("xclient", XClientMessageEvent),
        ("pad", c_long * 24)
    ]


class XClassHint(ctypes.Structure):
    _fields_ = [
        ("res_name", c_char_p),
        ("res_class", c_char_p)
    ]


class X11Helper:
    def __init__(self):
        self.disp = None
        self.wid = None
        self.x11 = None
        self._init_x11()

    def _init_x11(self):
        try:
            self.x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
            self.x11.XOpenDisplay.restype = c_void_p
            self.x11.XOpenDisplay.argtypes = [c_char_p]
            self.x11.XDefaultRootWindow.restype = c_ulong
            self.x11.XDefaultRootWindow.argtypes = [c_void_p]
            self.x11.XInternAtom.restype = c_ulong
            self.x11.XInternAtom.argtypes = [c_void_p, c_char_p, c_int]
            self.x11.XChangeProperty.restype = c_int
            self.x11.XChangeProperty.argtypes = [
                c_void_p, c_ulong, c_ulong, c_ulong, c_int, c_int, POINTER(c_ulong), c_int
            ]
            self.x11.XSetClassHint.argtypes = [c_void_p, c_ulong, POINTER(XClassHint)]
            self.x11.XSetClassHint.restype = c_int
            self.x11.XSendEvent.argtypes = [c_void_p, c_ulong, c_int, c_long, c_void_p]
            self.x11.XSendEvent.restype = c_int
            self.x11.XQueryTree.argtypes = [
                c_void_p, c_ulong, POINTER(c_ulong), POINTER(c_ulong), POINTER(POINTER(c_ulong)), POINTER(c_uint)
            ]
            self.x11.XQueryTree.restype = c_int
            self.x11.XMoveWindow.argtypes = [c_void_p, c_ulong, c_int, c_int]
            self.x11.XMoveWindow.restype = c_int
            self.x11.XQueryPointer.argtypes = [
                c_void_p, c_ulong, POINTER(c_ulong), POINTER(c_ulong),
                POINTER(c_int), POINTER(c_int), POINTER(c_int), POINTER(c_int), POINTER(c_uint)
            ]
            self.x11.XQueryPointer.restype = c_int
            self.x11.XMapRaised.argtypes = [c_void_p, c_ulong]
            self.x11.XMapRaised.restype = c_int
            self.x11.XFlush.argtypes = [c_void_p]
            self.x11.XFlush.restype = c_int

            disp_env = os.environ.get("DISPLAY", ":0").encode('utf-8')
            self.disp = self.x11.XOpenDisplay(disp_env)
        except Exception:
            self.x11 = None
            self.disp = None

    def configure_window(self, caption_match="Dexorto", mode="fullscreen", pos_x=None, pos_y=None):
        """Configures the window to skip panel & dock (EWMH hints) in both fullscreen & compact modes."""
        if not self.x11 or not self.disp:
            return False
        try:
            root = self.x11.XDefaultRootWindow(self.disp)

            # 1. Try Pygame WM info
            try:
                wm_info = pygame.display.get_wm_info()
                if wm_info and "window" in wm_info and wm_info["window"]:
                    self.wid = wm_info["window"]
            except Exception:
                pass

            net_client_list = self.x11.XInternAtom(self.disp, b"_NET_CLIENT_LIST", 0)
            net_wm_name = self.x11.XInternAtom(self.disp, b"_NET_WM_NAME", 0)
            wm_name = self.x11.XInternAtom(self.disp, b"WM_NAME", 0)
            atom_type = self.x11.XInternAtom(self.disp, b"ATOM", 0)

            # 2. Try _NET_CLIENT_LIST scan if needed
            if not self.wid:
                actual_type, actual_fmt, nitems, bytes_after = c_ulong(), c_int(), c_ulong(), c_ulong()
                prop = POINTER(ctypes.c_ubyte)()
                st = self.x11.XGetWindowProperty(
                    self.disp, root, net_client_list, 0, 4096, 0, 0,
                    byref(actual_type), byref(actual_fmt), byref(nitems), byref(bytes_after), byref(prop)
                )
                if st == 0 and prop:
                    win_ids = cast(prop, POINTER(c_ulong))
                    for i in range(nitems.value):
                        w = win_ids[i]
                        for atom_n in [net_wm_name, wm_name]:
                            n_prop = POINTER(ctypes.c_ubyte)()
                            s = self.x11.XGetWindowProperty(
                                self.disp, w, atom_n, 0, 512, 0, 0,
                                byref(c_ulong()), byref(c_int()), byref(c_ulong()), byref(c_ulong()), byref(n_prop)
                            )
                            if s == 0 and n_prop:
                                t = ctypes.string_at(n_prop).decode('utf-8', errors='ignore')
                                self.x11.XFree(n_prop)
                                if caption_match.lower() in t.lower():
                                    self.wid = w
                                    break
                        if self.wid:
                            break
                    self.x11.XFree(prop)

            if not self.wid:
                return False

            # Set WM_CLASS to 'dexorto', 'dexorto'
            hint = XClassHint(res_name=b"dexorto", res_class=b"dexorto")
            self.x11.XSetClassHint(self.disp, self.wid, byref(hint))

            # Reposition if specified
            if pos_x is not None and pos_y is not None:
                self.x11.XMoveWindow(self.disp, self.wid, int(pos_x), int(pos_y))

            # If compact mode, set Window Type: UTILITY (skips taskbar naturally)
            if mode == "compact":
                net_wm_window_type = self.x11.XInternAtom(self.disp, b"_NET_WM_WINDOW_TYPE", 0)
                type_utility = self.x11.XInternAtom(self.disp, b"_NET_WM_WINDOW_TYPE_UTILITY", 0)
                wtypes = (c_ulong * 1)(type_utility)
                self.x11.XChangeProperty(self.disp, self.wid, net_wm_window_type, atom_type, 32, 0, wtypes, 1)

            # Motif WM hints for borderless (MWM_HINTS_DECORATIONS = 2, decorations = 0)
            motif_wm_hints = self.x11.XInternAtom(self.disp, b"_MOTIF_WM_HINTS", 0)
            hints_data = (c_ulong * 5)(2, 0, 0, 0, 0)
            self.x11.XChangeProperty(self.disp, self.wid, motif_wm_hints, motif_wm_hints, 32, 0, hints_data, 5)

            # Send _NET_WM_STATE ClientMessage for SKIP_TASKBAR and SKIP_PAGER
            net_wm_state = self.x11.XInternAtom(self.disp, b"_NET_WM_STATE", 0)
            skip_taskbar = self.x11.XInternAtom(self.disp, b"_NET_WM_STATE_SKIP_TASKBAR", 0)
            skip_pager = self.x11.XInternAtom(self.disp, b"_NET_WM_STATE_SKIP_PAGER", 0)

            states = (c_ulong * 2)(skip_taskbar, skip_pager)
            self.x11.XChangeProperty(self.disp, self.wid, net_wm_state, atom_type, 32, 0, states, 2)

            mask = (1 << 20) | (1 << 19)
            for atom_val in (skip_taskbar, skip_pager):
                event = XEvent()
                event.type = 33
                event.xclient.type = 33
                event.xclient.send_event = 1
                event.xclient.display = self.disp
                event.xclient.window = self.wid
                event.xclient.message_type = net_wm_state
                event.xclient.format = 32
                event.xclient.data[0] = 1  # _NET_WM_STATE_ADD
                event.xclient.data[1] = atom_val
                event.xclient.data[2] = 0
                event.xclient.data[3] = 1
                self.x11.XSendEvent(self.disp, root, 0, mask, byref(event))

            self.x11.XFlush(self.disp)
            print(f"[X11] Configured Dexorto window (mode: {mode}, ID: {self.wid})")
            return True
        except Exception as e:
            print("[X11] Config notice:", e)
            return False

    def move_window(self, x, y):
        if self.x11 and self.disp and self.wid:
            try:
                self.x11.XMoveWindow(self.disp, self.wid, int(x), int(y))
                self.x11.XFlush(self.disp)
            except Exception:
                pass

    def raise_window(self):
        if self.x11 and self.disp and self.wid:
            try:
                self.x11.XMapRaised(self.disp, self.wid)
                self.x11.XFlush(self.disp)
            except Exception:
                pass

    def iconify_window(self):
        if self.x11 and self.disp and self.wid:
            try:
                screen = 0
                if hasattr(self.x11, "XDefaultScreen"):
                    screen = self.x11.XDefaultScreen(self.disp)
                if hasattr(self.x11, "XIconifyWindow"):
                    self.x11.XIconifyWindow(self.disp, self.wid, screen)
                self.x11.XFlush(self.disp)
            except Exception:
                pass

    def get_pointer_pos(self):
        if not self.x11 or not self.disp:
            return None
        try:
            root = self.x11.XDefaultRootWindow(self.disp)
            root_ret, child_ret = c_ulong(), c_ulong()
            rx, ry, wx, wy = c_int(), c_int(), c_int(), c_int()
            mask = c_uint()
            st = self.x11.XQueryPointer(
                self.disp, root, byref(root_ret), byref(child_ret),
                byref(rx), byref(ry), byref(wx), byref(wy), byref(mask)
            )
            if st != 0:
                return (rx.value, ry.value)
        except Exception:
            pass
        return None


# ══════════════════════════════════════════════════════════
# HUD Core Status & Arc Reactor State Engine
# ══════════════════════════════════════════════════════════
class EmotionEngine:
    """
    Computes holographic Arc Reactor state, colors, and telemetry labels:
    - IDLE: Calm holographic cyan/gold breathing halo & 'ONLINE' badge
    - LISTENING: Glowing crimson red alert ring & dynamic acoustic capture
    - THINKING: High-speed cyan orbital reticle & 'PROCESSING' badge
    - SPEAKING: Cheerful emerald green waveform arcs & 'SPEAKING' badge
    - MUTED: Dim silver/slate idle ring & 'MUTED' badge
    - TROUBLE / ERROR: Pulsing amber/red diagnostics & 'TROUBLE' alert
    """
    def __init__(self):
        pass

    def get_emotion(self, state: str, is_recording: bool, is_speaking: bool, voice_muted: bool):
        if voice_muted and state == "IDLE":
            return "idle", "READY // WAKE: \"DEXORTO\"", "READY", Palette.GREEN

        if state == "LISTENING" or is_recording:
            return "listening", "LISTENING...", "LISTENING", Palette.RED

        if state in ["THINKING", "SEARCHING"]:
            return "thinking", "PROCESSING...", "THINKING", Palette.WHITE

        if state == "SPEAKING" or is_speaking:
            return "speaking", "SPEAKING...", "SPEAKING", Palette.GREEN

        if state in ["ERROR", "TROUBLE"]:
            return "trouble", "CONFUSED...", "TROUBLE", Palette.RED

        return "idle", "READY // WAKE: \"DEXORTO\"", "READY", Palette.GREEN


# ══════════════════════════════════════════════════════════
# Standalone Assistant Backend (Multi-Provider Fallback)
# 10s Voice Input Window with 100ms Initial Delay
# ══════════════════════════════════════════════════════════
class AssistantBackend:
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dexorto_widget_")
        self.gemini_client = None
        self.groq_client = None
        self.tavily_client = None
        if HAS_SR:
            self.recognizer = sr.Recognizer()
            self.recognizer.energy_threshold = getattr(config, "ENERGY_THRESHOLD", 140)
            self.recognizer.dynamic_energy_threshold = True
            self.recognizer.dynamic_energy_adjustment_damping = 0.15
            self.recognizer.dynamic_energy_ratio = 1.4
            self.recognizer.pause_threshold = 0.45
            self.recognizer.non_speaking_duration = 0.25
            self.recognizer.phrase_threshold = 0.15
        else:
            self.recognizer = None
        self.microphone = None
        self.is_speaking = False
        self.last_spoken_text = ""
        self.last_speech_end_time = 0.0
        self.audio_available = True
        self.active_player_proc = None
        self.preferred_provider = getattr(config, "PREFERRED_PROVIDER", "gemini")
        self.tts_voice = getattr(config, "TTS_VOICE", "en-US-AriaNeural")

        self._init_services()

    def _init_services(self):
        # Gemini
        if HAS_GEMINI and getattr(config, "GEMINI_API_KEY", ""):
            try:
                self.gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
            except Exception as e:
                print("Gemini init notice:", e)

        # Groq
        if HAS_GROQ and getattr(config, "GROQ_API_KEY", ""):
            try:
                self.groq_client = Groq(api_key=config.GROQ_API_KEY)
            except Exception as e:
                print("Groq init notice:", e)

        # Tavily
        tavily_key = getattr(config, "TAVILY_API_KEY", "")
        if tavily_key and tavily_key != "YOUR_TAVILY_API_KEY_HERE":
            try:
                from tavily import TavilyClient
                self.tavily_client = TavilyClient(api_key=tavily_key)
            except Exception:
                pass

        # Audio setup (4096-sample buffer eliminates ALSA/Pulse underrun crackles)
        try:
            buf_size = getattr(config, "TTS_BUFFER_SIZE", 4096)
            if not pygame.mixer.get_init():
                pygame.mixer.pre_init(frequency=24000, size=-16, channels=2, buffer=buf_size)
                pygame.mixer.init(frequency=24000, size=-16, channels=2, buffer=buf_size)
            self.audio_available = True
        except Exception as me:
            print("[Audio] pygame.mixer init notice:", me)
            self.audio_available = True  # External system audio fallbacks (ffplay/paplay/aplay) are active

        if HAS_SR:
            try:
                self.microphone = sr.Microphone()
                self.recognizer.energy_threshold = getattr(config, "ENERGY_THRESHOLD", 140)
                self.recognizer.dynamic_energy_threshold = False  # Fixed sensitivity prevents deafness
                self.recognizer.pause_threshold = 0.55            # Responsive conversational pause
                self.recognizer.non_speaking_duration = 0.20
                self.recognizer.phrase_threshold = 0.15
                with self.microphone as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=0.2)
                configured_thresh = getattr(config, "ENERGY_THRESHOLD", 140)
                self.recognizer.energy_threshold = max(60, min(self.recognizer.energy_threshold, 250, configured_thresh))
                print(f"[Audio] Microphone initialized! Energy threshold: {self.recognizer.energy_threshold}")
            except Exception as me:
                print(f"[Audio] PyAudio init notice: {me} (will use sounddevice recording fallback)")
                self.microphone = None

        if HAS_WEBRTCVAD:
            try:
                self.vad = webrtcvad.Vad(getattr(config, "VAD_AGGRESSIVENESS", 2))
            except Exception:
                self.vad = None
        else:
            self.vad = None

    def _record_audio_fallback(self, duration: float = 3.0):
        """Fallback audio capture using sounddevice if PyAudio/sr.Microphone is unavailable."""
        if HAS_SOUNDDEVICE:
            try:
                sr_rate = 16000
                rec = sd.rec(int(duration * sr_rate), samplerate=sr_rate, channels=1, dtype='int16')
                sd.wait()
                raw_bytes = rec.tobytes()
                if HAS_SR and self.recognizer:
                    return sr.AudioData(raw_bytes, sr_rate, 2)
            except Exception as sde:
                print("[Audio] SoundDevice capture notice:", sde)
        return None

    def play_wake_chime(self):
        """Plays a gentle 180ms dual-tone sci-fi activation chime upon wake word detection."""
        def _chime_worker():
            chime_path = os.path.join(self.temp_dir, "wake_chime.wav")
            if not os.path.exists(chime_path):
                try:
                    sr_rate = 24000
                    with wave.open(chime_path, 'wb') as wav:
                        wav.setnchannels(1)
                        wav.setsampwidth(2)
                        wav.setframerate(sr_rate)
                        for i in range(int(sr_rate * 0.06)):
                            v = int(math.sin(2 * math.pi * 659.25 * i / sr_rate) * 7000 * (1 - i / (sr_rate * 0.06)))
                            wav.writeframes(struct.pack('<h', v))
                        for i in range(int(sr_rate * 0.015)):
                            wav.writeframes(struct.pack('<h', 0))
                        for i in range(int(sr_rate * 0.08)):
                            v = int(math.sin(2 * math.pi * 880.0 * i / sr_rate) * 8500 * (1 - i / (sr_rate * 0.08)))
                            wav.writeframes(struct.pack('<h', v))
                except Exception:
                    return

            try:
                if pygame.mixer.get_init():
                    snd = pygame.mixer.Sound(chime_path)
                    snd.set_volume(0.6)
                    snd.play()
                    return
            except Exception:
                pass

            for cmd in [
                ["paplay", chime_path],
                ["aplay", "-q", chime_path],
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", chime_path],
                ["pw-play", chime_path]
            ]:
                try:
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
                    break
                except Exception:
                    continue

        threading.Thread(target=_chime_worker, daemon=True).start()

    def is_specific_command(self, text: str) -> tuple:
        """Validates if text is a specific actionable command or just idle/wake noise."""
        has_pending = bool(TaskManager.get_pending_app())
        return is_specific_command(text, has_pending_action=has_pending)

    def transcribe_mic(self) -> str:
        """Transcribes speech with 4-second timeout and specificity filtering."""
        if not HAS_SR:
            return ""

        audio = None
        try:
            # Check post-speech acoustic cooldown to avoid recording speaker reverberations
            cooldown = getattr(config, "SELF_VOICE_MUTE_COOLDOWN", 0.65)
            rem = cooldown - (time.time() - self.last_speech_end_time)
            if rem > 0:
                time.sleep(rem)
            else:
                time.sleep(0.08)

            if self.microphone:
                try:
                    with self.microphone as source:
                        audio = self.recognizer.listen(
                            source,
                            timeout=getattr(config, "COMMAND_TIMEOUT", 4.0),
                            phrase_time_limit=7
                        )
                except sr.WaitTimeoutError:
                    return ""
                except Exception:
                    audio = None

            if audio is None:
                audio = self._record_audio_fallback(duration=getattr(config, "COMMAND_TIMEOUT", 4.0))
                if audio is None:
                    return ""

            # Silence floor check
            raw_bytes = audio.get_raw_data()
            min_rms = getattr(config, "MIN_SPEECH_RMS", 12)
            if is_audio_silent(raw_bytes, min_rms=min_rms):
                return ""

            # 1. Ultra-fast Groq Whisper Turbo (~150ms transcription)
            if self.groq_client:
                try:
                    wav_data = audio.get_wav_data()
                    audio_file = io.BytesIO(wav_data)
                    audio_file.name = "audio.wav"
                    prompt_text = getattr(config, "WHISPER_PROMPT", "Dexorto AI assistant.")
                    resp = self.groq_client.audio.transcriptions.create(
                        model="whisper-large-v3-turbo",
                        file=audio_file,
                        temperature=0.0,
                        prompt=prompt_text
                    )
                    if resp and resp.text:
                        candidate = resp.text.strip()
                        print(f"[Voice Mic] Transcribed command: '{candidate}'")
                        if not is_whisper_hallucination(candidate) and not self._is_self_voice_echo(candidate):
                            is_spec, clean_cand = self.is_specific_command(candidate)
                            if is_spec:
                                return clean_cand
                            else:
                                print(f"[Voice Mic] Filtered non-specific candidate: '{candidate}'")
                except Exception as ge:
                    print("[Voice Mic] Groq Whisper error:", ge)

            # 2. Resilient Google STT fallback
            try:
                candidate = self.recognizer.recognize_google(audio).strip()
                print(f"[Voice Mic] Google STT fallback: '{candidate}'")
                if not is_whisper_hallucination(candidate) and not self._is_self_voice_echo(candidate):
                    is_spec, clean_cand = self.is_specific_command(candidate)
                    if is_spec:
                        return clean_cand
            except Exception as ge:
                print("[Voice Mic] Google STT notice:", ge)

            return ""
        except sr.WaitTimeoutError:
            return ""
        except Exception as e:
            print("[Voice Mic] Unexpected error:", e)
            return ""

    def _is_self_voice_echo(self, text: str) -> bool:
        """Prevents assistant from triggering on its own spoken audio output."""
        if not text or not self.last_spoken_text:
            return False
        # If currently speaking or within 2.5s of speech
        if not self.is_speaking and (time.time() - self.last_speech_end_time > 2.5):
            return False
        c_text = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower()).strip()
        c_last = re.sub(r'[^a-zA-Z0-9\s]', '', self.last_spoken_text.lower()).strip()
        if not c_text or not c_last:
            return False
        if c_text in c_last:
            return True
        words = [w for w in c_text.split() if len(w) > 3]
        if words:
            last_words = set(c_last.split())
            matches = sum(1 for w in words if w in last_words)
            if matches >= max(2, int(len(words) * 0.5)):
                return True
        return False

    def listen_for_wake_word(self) -> tuple:
        """
        Listens continuously for the strict wake word in background.
        Rejects room noise floor, assistant self-voice reverberation, and speaker bleed.
        Returns: (detected: bool, followup_command: str)
        """
        if not HAS_SR:
            return False, ""

        # 1. Post-speech acoustic cooldown check (eliminates speaker reverberation & buffer latency)
        cooldown = getattr(config, "SELF_VOICE_MUTE_COOLDOWN", 0.65)
        if time.time() - self.last_speech_end_time < cooldown:
            return False, ""

        # 2. Barge-in / speaking check
        if self.is_speaking:
            if not getattr(config, "ALLOW_BARGE_IN", True):
                return False, ""
            min_rms = max(24, int(getattr(config, "MIN_SPEECH_RMS", 12) * 1.8))
        else:
            min_rms = getattr(config, "MIN_SPEECH_RMS", 12)

        audio = None
        if not self.microphone and not getattr(self, "_mic_failed", False):
            try:
                self.microphone = sr.Microphone()
            except Exception:
                self.microphone = None
                self._mic_failed = True

        if self.microphone:
            try:
                with self.microphone as source:
                    audio = self.recognizer.listen(
                        source,
                        timeout=2.5,
                        phrase_time_limit=3.5
                    )
            except sr.WaitTimeoutError:
                return False, ""
            except Exception:
                audio = None

        if audio is None:
            audio = self._record_audio_fallback(duration=2.5)
            if audio is None:
                time.sleep(0.4)
                return False, ""

        try:
            # Fast silence check — skip API call if room is quiet or speaker bleed is low
            raw_bytes = audio.get_raw_data()
            if is_audio_silent(raw_bytes, min_rms=min_rms):
                return False, ""

            text = ""
            if self.groq_client:
                try:
                    wav_data = audio.get_wav_data()
                    audio_file = io.BytesIO(wav_data)
                    audio_file.name = "audio.wav"
                    prompt_text = getattr(config, "WHISPER_PROMPT", "Dexorto AI assistant.")
                    resp = self.groq_client.audio.transcriptions.create(
                        model="whisper-large-v3-turbo",
                        file=audio_file,
                        temperature=0.0,
                        prompt=prompt_text
                    )
                    if resp and resp.text:
                        candidate = resp.text.strip()
                        if not is_whisper_hallucination(candidate) and not self._is_self_voice_echo(candidate):
                            text = candidate
                except Exception as ge:
                    print("[Wake] Groq Whisper notice:", ge)

            if not text:
                try:
                    candidate = self.recognizer.recognize_google(audio).strip()
                    if not is_whisper_hallucination(candidate) and not self._is_self_voice_echo(candidate):
                        text = candidate
                except Exception:
                    return False, ""

            if not text:
                return False, ""

            # Strict Wake Word Matcher
            detected, inline_cmd = self._parse_wake_and_command(text)
            if detected:
                print(f"[Wake] Wake word recognized in: '{text}'!")
            return detected, inline_cmd

        except sr.WaitTimeoutError:
            return False, ""
        except Exception:
            return False, ""

        except sr.WaitTimeoutError:
            return False, ""
        except Exception:
            return False, ""

    def _parse_wake_and_command(self, text: str) -> tuple:
        """Parses strict wake word and extracts any specific command spoken in the same breath."""
        if not text:
            return False, ""
        t = text.strip()

        # 1. Starts with wake word: "Dexorto play music" / "Hey dexorto, what time is it"
        m_start = WAKE_PATTERN_START.search(t)
        if m_start:
            cmd = m_start.group(1).strip().lstrip(",.?! ").rstrip(",.?! ")
            if cmd:
                is_spec, clean_cmd = self.is_specific_command(cmd)
                if is_spec:
                    return True, clean_cmd
            return True, ""

        # 2. Ends with wake word: "What time is it, dexorto?" / "Play music dexorto"
        m_end = WAKE_PATTERN_END.search(t)
        if m_end:
            cmd = m_end.group(1).strip().lstrip(",.?! ").rstrip(",.?! ")
            if cmd:
                is_spec, clean_cmd = self.is_specific_command(cmd)
                if is_spec:
                    return True, clean_cmd
            return True, ""

        # 3. Contains strict wake word: "Can you hear me, dexorto, answer please"
        m_strict = WAKE_PATTERN_STRICT.search(t)
        if m_strict:
            cmd = WAKE_PATTERN_STRICT.sub("", t).strip().lstrip(",.?! ").rstrip(",.?! ")
            if cmd:
                is_spec, clean_cmd = self.is_specific_command(cmd)
                if is_spec:
                    return True, clean_cmd
            return True, ""

        return False, ""

    def search_tavily(self, query: str) -> str:
        if not self.tavily_client:
            return ""
        try:
            resp = self.tavily_client.search(query=query, max_results=3)
            return "\n".join([f"- {r.get('title', '')}: {r.get('content', '')}" for r in resp.get("results", [])])
        except Exception:
            return ""

    def ask_brain(self, user_query: str) -> str:
        """Queries primary provider with graceful multi-tier fallbacks using formal LLM tools."""
        # 1. Check pending confirmation for opening duplicate instance
        low_q = user_query.strip().lower()
        pending_app = TaskManager.get_pending_app()
        if pending_app:
            if re.match(r'^(?:yes|yeah|yup|sure|ok|okay|please do|go ahead|open it|open another|do it)\b', low_q):
                TaskManager.clear_pending_app()
                return ToolExecutor.execute_tool("open_app", {"app_name": pending_app, "force_new_instance": True})
            elif re.match(r'^(?:no|nope|cancel|nevermind|don\'t|dont|stop)\b', low_q):
                TaskManager.clear_pending_app()
                return f"Understood, Dex. Keeping your current {pending_app.capitalize()} window in focus."

        pref = getattr(config, "PREFERRED_PROVIDER", self.preferred_provider).lower()
        effective_prompt = get_effective_system_prompt()

        # Fast-path deterministic execution for direct commands (play music, open apps, volume, menu)
        direct_ans = ToolExecutor.execute_direct_command(user_query)
        if direct_ans:
            return format_short_clean_response(direct_ans, max_sentences=2)

        def _log_debug(msg):
            try:
                debug_log = os.path.join(str(SCRIPT_DIR), "ai_debug.log")
                with open(debug_log, "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
            except Exception:
                pass

        def _try_gemini():
            if not self.gemini_client:
                _log_debug("[Gemini] gemini_client is None!")
                return None
            models = [getattr(config, "GEMINI_MODEL", "gemini-3.1-flash-lite-preview")] + getattr(config, "GEMINI_FALLBACKS", ["gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-3.5-flash-lite"])
            for m in models:
                try:
                    _log_debug(f"[Gemini] Requesting model {m} for query: {user_query[:50]}")
                    chat = self.gemini_client.chats.create(
                        model=m,
                        config=types.GenerateContentConfig(
                            system_instruction=effective_prompt,
                            tools=GEMINI_TOOLS,
                            temperature=0.7,
                            max_output_tokens=90
                        )
                    )
                    resp = chat.send_message(user_query)
                    reply_text = None
                    try:
                        if resp and resp.text:
                            reply_text = resp.text
                    except Exception:
                        pass
                    if not reply_text and resp and getattr(resp, "candidates", None):
                        for cand in resp.candidates:
                            content = getattr(cand, "content", None)
                            if content and getattr(content, "parts", None):
                                for part in content.parts:
                                    if hasattr(part, "text") and part.text:
                                        reply_text = part.text
                                        break
                                if reply_text:
                                    break
                    if reply_text and reply_text.strip():
                        _log_debug(f"[Gemini] Model {m} SUCCESS: {reply_text.strip()[:60]}")
                        return format_short_clean_response(reply_text.strip(), max_sentences=2)
                    _log_debug(f"[Gemini] Model {m} returned empty reply")
                except Exception as e:
                    _log_debug(f"[Gemini] Model {m} EXCEPTION: {e}")
                    print(f"[Gemini] Model {m} notice:", e)
                    continue
            return None

        def _try_groq():
            if not self.groq_client:
                return None
            models = [getattr(config, "GROQ_CHAT_MODEL", "openai/gpt-oss-20b")] + getattr(config, "GROQ_CHAT_FALLBACKS", ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"])
            for m in models:
                try:
                    resp = self.groq_client.chat.completions.create(
                        model=m,
                        messages=[{"role": "system", "content": effective_prompt}, {"role": "user", "content": user_query}],
                        tools=ASSISTANT_TOOLS,
                        tool_choice="auto",
                        max_tokens=90,
                        temperature=0.7
                    )
                    msg = resp.choices[0].message
                    tool_calls = getattr(msg, "tool_calls", None)
                    if tool_calls:
                        tool_results = []
                        for tc in tool_calls:
                            t_name = tc.function.name
                            try:
                                t_args = json.loads(tc.function.arguments)
                            except Exception:
                                t_args = {}
                            t_res = ToolExecutor.execute_tool(t_name, t_args, tavily_search_fn=self.search_tavily)
                            if t_res:
                                tool_results.append(t_res)
                        if tool_results:
                            return format_short_clean_response(" ".join(tool_results), max_sentences=2)

                    if msg.content and msg.content.strip():
                        return format_short_clean_response(msg.content.strip(), max_sentences=2)
                except Exception as e:
                    print(f"[Groq] Model {m} notice:", e)
                    continue
            return None

        def _try_openrouter():
            key = getattr(config, "OPENROUTER_API_KEY", "")
            if not key or key == "YOUR_OPENROUTER_KEY_HERE":
                return None
            models = [getattr(config, "OPENROUTER_MODEL", "qwen/qwen3.8-27b:free")] + getattr(config, "OPENROUTER_FALLBACKS", [])
            for m in models:
                try:
                    headers = {
                        "Authorization": f"Bearer {key}",
                        "HTTP-Referer": "http://localhost:8000",
                        "X-Title": "Dexorto Companion",
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "model": m,
                        "messages": [{"role": "system", "content": effective_prompt}, {"role": "user", "content": user_query}],
                        "tools": ASSISTANT_TOOLS,
                        "tool_choice": "auto",
                        "max_tokens": 90,
                        "temperature": 0.7
                    }
                    resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=12)
                    if resp.status_code == 200:
                        choice = resp.json().get("choices", [{}])[0].get("message", {})
                        tool_calls = choice.get("tool_calls")
                        if tool_calls:
                            tool_results = []
                            for tc in tool_calls:
                                t_name = tc.get("function", {}).get("name", "")
                                try:
                                    t_args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                                except Exception:
                                    t_args = {}
                                t_res = ToolExecutor.execute_tool(t_name, t_args, tavily_search_fn=self.search_tavily)
                                if t_res:
                                    tool_results.append(t_res)
                            if tool_results:
                                return format_short_clean_response(" ".join(tool_results), max_sentences=2)
                        content = choice.get("content", "")
                        if content and content.strip():
                            return format_short_clean_response(content.strip(), max_sentences=2)
                except Exception:
                    continue
            return None

        if pref == "gemini":
            order = [_try_gemini, _try_groq, _try_openrouter]
        elif pref == "groq":
            order = [_try_groq, _try_gemini, _try_openrouter]
        else:
            order = [_try_openrouter, _try_gemini, _try_groq]
        for fn in order:
            res = fn()
            if res:
                return format_short_clean_response(res, max_sentences=2)

        return "I am having trouble connecting to AI services right now."

    def play_tts(self, text: str, on_finished=None):
        clean = clean_speech_output(text)

        if not clean or not HAS_EDGE_TTS:
            if on_finished:
                on_finished()
            return

        def _worker():
            was_interrupted = False
            try:
                self.is_speaking = True
                self.last_spoken_text = clean.lower()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                out_file = os.path.join(self.temp_dir, "speech.mp3")

                voice_to_use = self.tts_voice
                if re.search(r'[\u0900-\u097F]', clean):
                    voice_to_use = getattr(config, "TTS_VOICE_HINDI", "hi-IN-MadhurNeural")

                async def _save():
                    comm = edge_tts.Communicate(
                        text=clean,
                        voice=voice_to_use,
                        rate=getattr(config, "TTS_RATE", "+0%"),
                        pitch=getattr(config, "TTS_PITCH", "+0Hz")
                    )
                    await comm.save(out_file)

                loop.run_until_complete(_save())
                loop.close()

                if not self.is_speaking:
                    was_interrupted = True
                    if os.path.exists(out_file):
                        try:
                            os.remove(out_file)
                        except OSError:
                            pass
                    return

                if os.path.exists(out_file) and os.path.getsize(out_file) > 0:
                    played = False
                    # 1. Primary: pygame.mixer
                    try:
                        if not pygame.mixer.get_init():
                            buf_size = getattr(config, "TTS_BUFFER_SIZE", 4096)
                            pygame.mixer.pre_init(frequency=24000, size=-16, channels=2, buffer=buf_size)
                            pygame.mixer.init(frequency=24000, size=-16, channels=2, buffer=buf_size)
                        pygame.mixer.music.load(out_file)
                        pygame.mixer.music.set_volume(1.0)
                        pygame.mixer.music.play()
                        while pygame.mixer.music.get_busy() and self.is_speaking:
                            time.sleep(0.03)
                        if not self.is_speaking:
                            was_interrupted = True
                        pygame.mixer.music.unload()
                        played = True
                    except Exception as pge:
                        print("[TTS] pygame.mixer playback notice:", pge)
                        played = False

                    # 2. Resilient system audio player fallbacks
                    if not played and not was_interrupted:
                        for p_cmd in [
                            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", out_file],
                            ["mpv", "--no-video", "--really-quiet", out_file],
                            ["paplay", out_file],
                            ["aplay", "-q", out_file],
                            ["pw-play", out_file]
                        ]:
                            try:
                                proc = subprocess.Popen(p_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                self.active_player_proc = proc
                                while proc.poll() is None and self.is_speaking:
                                    time.sleep(0.04)
                                if not self.is_speaking:
                                    was_interrupted = True
                                    proc.terminate()
                                self.active_player_proc = None
                                played = True
                                break
                            except Exception:
                                continue

                if os.path.exists(out_file):
                    try:
                        os.remove(out_file)
                    except OSError:
                        pass
            except Exception as e:
                print("[TTS] Playback error:", e)
            finally:
                self.is_speaking = False
                self.last_speech_end_time = time.time()
                if on_finished and not was_interrupted:
                    on_finished()

        threading.Thread(target=_worker, daemon=True).start()

    def stop_tts(self):
        self.is_speaking = False
        self.last_speech_end_time = time.time()
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass
        if getattr(self, "active_player_proc", None):
            try:
                self.active_player_proc.terminate()
            except Exception:
                pass
            self.active_player_proc = None

    def run_actions(self, text: str, user_query: str = ""):
        """
        Parses fallback JSON commands (if any from older prompts or fallbacks)
        and routes them strictly through ToolExecutor to enforce single-instance app policies and tab reuse.
        """
        matches = re.findall(r'\{[^{}]*"action"[^{}]*\}', text, re.DOTALL)
        for m in matches:
            try:
                data = json.loads(m)
                action = data.get("action", "")
                if action == "open_app":
                    target = data.get("target") or data.get("app") or data.get("app_name", "")
                    ToolExecutor.execute_tool("open_app", {"app_name": target})
                elif action == "play_music":
                    song = data.get("song") or data.get("target", "")
                    plat = data.get("platform") or getattr(config, "DEFAULT_MUSIC_PLATFORM", "spotify")
                    ToolExecutor.execute_tool("play_music", {"song": song, "platform": plat})
                elif action == "open_url":
                    url = data.get("target") or data.get("url", "")
                    ToolExecutor.execute_tool("open_url", {"url": url})
                elif action == "compose_message":
                    service = data.get("inbox") or data.get("service", "gmail")
                    to = data.get("to") or data.get("recipient", "")
                    subject = data.get("subject", "")
                    message = data.get("message", "")
                    ToolExecutor.execute_tool("compose_message", {"service": service, "recipient": to, "subject": subject, "message": message})
                elif action == "type_text":
                    text_to_type = data.get("text", "")
                    ToolExecutor.execute_tool("type_text", {"text": text_to_type})
                elif BrowserController.execute_action(data):
                    pass
            except Exception:
                pass


# ══════════════════════════════════════════════════════════
# Continuous Wake Word Listener (Background Thread)
# ══════════════════════════════════════════════════════════
class WakeWordListener:
    def __init__(self, backend: AssistantBackend, on_wake_callback):
        self.backend = backend
        self.on_wake = on_wake_callback
        self.active = True
        self.paused = False
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.active = False

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def _listen_loop(self):
        print("[Wake] Continuous background wake word tracker ACTIVE (listening for 'dexorto')...")
        while self.active:
            if self.paused:
                time.sleep(0.15)
                continue

            try:
                detected, inline_cmd = self.backend.listen_for_wake_word()
                if detected and self.active and not self.paused:
                    if inline_cmd:
                        print(f"[Wake] Wake word + immediate command: '{inline_cmd}'")
                    else:
                        print("[Wake] Wake word detected!")
                    self.on_wake(inline_cmd)
            except Exception as e:
                time.sleep(0.3)

            time.sleep(0.04)


# ══════════════════════════════════════════════════════════
# Dexorto AI Dual-Mode Application
# (Fullscreen Terminal <-> Compact Floating Widget)
# ══════════════════════════════════════════════════════════
class DexortoDualApp:
    def __init__(self):
        # 1. Screen Dimensions Detection
        self.screen_w = 1366
        self.screen_h = 768
        try:
            temp_x11 = X11Helper()
            if temp_x11.disp and temp_x11.x11:
                screen_num = 0
                if hasattr(temp_x11.x11, "XDefaultScreen"):
                    screen_num = temp_x11.x11.XDefaultScreen(temp_x11.disp)
                if hasattr(temp_x11.x11, "XDisplayWidth"):
                    cur_w = temp_x11.x11.XDisplayWidth(temp_x11.disp, screen_num)
                    if cur_w > 0:
                        self.screen_w = cur_w
                if hasattr(temp_x11.x11, "XDisplayHeight"):
                    cur_h = temp_x11.x11.XDisplayHeight(temp_x11.disp, screen_num)
                    if cur_h > 0:
                        self.screen_h = cur_h
        except Exception:
            pass

        # 2. Default Window Mode
        self.mode = getattr(config, "DEFAULT_WINDOW_MODE", "fullscreen")
        self.compact_w = 360
        self.compact_h = 500

        if self.mode == "compact":
            self.width = self.compact_w
            self.height = self.compact_h
            self.current_win_x = max(20, self.screen_w - self.width - 24)
            self.current_win_y = 52
        else:
            self.width = self.screen_w
            self.height = self.screen_h
            self.current_win_x = 0
            self.current_win_y = 0

        # SDL Environment setup before pygame.init()
        os.environ["SDL_VIDEO_WINDOW_POS"] = f"{self.current_win_x},{self.current_win_y}"
        os.environ["SDL_VIDEO_X11_WMCLASS"] = "dexorto"
        os.environ["SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR"] = "0"

        try:
            pygame.mixer.pre_init(frequency=24000, size=-16, channels=2, buffer=getattr(config, "TTS_BUFFER_SIZE", 4096))
        except Exception:
            pass

        pygame.init()
        pygame.font.init()

        self.caption = "Dexorto AI // Companion"
        pygame.display.set_caption(self.caption)
        self.screen = pygame.display.set_mode((self.width, self.height), pygame.NOFRAME)

        # 3. Typography
        sans_font = None
        sans_bold = None
        for fp, fpb in [
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            ("/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf", "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf"),
        ]:
            if os.path.exists(fp) and os.path.exists(fpb):
                sans_font = fp
                sans_bold = fpb
                break

        mono_font = None
        for fp in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        ]:
            if os.path.exists(fp):
                mono_font = fp
                break

        if sans_font and sans_bold:
            self.font_hud_title = pygame.font.Font(sans_bold, 18)
            self.font_card_title = pygame.font.Font(sans_bold, 13)
            self.font_big_temp = pygame.font.Font(sans_bold, 24)
            self.font_stat_val = pygame.font.Font(sans_bold, 12)
            self.font_stat_lbl = pygame.font.Font(sans_font, 10)
            self.font_title = pygame.font.Font(sans_bold, 14)
            self.font_badge = pygame.font.Font(sans_bold, 11)
            self.font_btn = pygame.font.Font(sans_bold, 11)
            self.font_text = pygame.font.Font(sans_font, 13)
            self.font_sub = pygame.font.Font(sans_font, 11)
            self.font_input = pygame.font.Font(sans_font, 13)
        else:
            self.font_hud_title = pygame.font.Font(None, 20)
            self.font_card_title = pygame.font.Font(None, 16)
            self.font_big_temp = pygame.font.Font(None, 26)
            self.font_stat_val = pygame.font.Font(None, 14)
            self.font_stat_lbl = pygame.font.Font(None, 11)
            self.font_title = pygame.font.Font(None, 16)
            self.font_badge = pygame.font.Font(None, 12)
            self.font_btn = pygame.font.Font(None, 12)
            self.font_text = pygame.font.Font(None, 14)
            self.font_sub = pygame.font.Font(None, 12)
            self.font_input = pygame.font.Font(None, 14)

        if mono_font:
            self.font_mono = pygame.font.Font(mono_font, 13)
            self.font_mono_sm = pygame.font.Font(mono_font, 11)
            self.font_header = pygame.font.Font(mono_font, 18)
        else:
            self.font_mono = pygame.font.Font(None, 14)
            self.font_mono_sm = pygame.font.Font(None, 12)
            self.font_header = pygame.font.Font(None, 18)

        # 4. Feature Settings & System Controls
        self.settings_open = False
        self.settings_tab = 0
        self.settings_tab_rects = []
        self.send_btn_rect = pygame.Rect(0, 0, 0, 0)
        self.understand_hindi = getattr(config, "UNDERSTAND_HINDI", True)
        self.allow_barge_in = getattr(config, "ALLOW_BARGE_IN", True)
        self.auto_json_filter = getattr(config, "AUTO_JSON_FILTER", True)
        self.prevent_duplicate_apps = getattr(config, "PREVENT_DUPLICATE_APPS", True)
        self.reuse_browser_tabs = getattr(config, "REUSE_BROWSER_TABS", True)
        self.settings_toggles = []
        self._load_persisted_settings()

        # 5. X11 Window Configuration
        self.x11 = X11Helper()
        if self.x11 and self.x11.disp:
            TaskManager.set_x11(self.x11.x11, self.x11.disp)
        self.x11_configured = self.x11.configure_window(
            self.caption, mode=self.mode, pos_x=self.current_win_x, pos_y=self.current_win_y
        )
        self.x11_retry_count = 0

        # Window Dragging State (for compact mode)
        self.is_dragging = False
        self.drag_offset_x = 0
        self.drag_offset_y = 0

        # 6. Assistant Backend & IPC
        self.backend = AssistantBackend()
        self.emotion_engine = EmotionEngine()

        self.ipc_client = JarvisIPCClient(on_event_callback=self._handle_ipc_event)
        self.linked_to_daemon = False

        # 7. State & Messages
        self.state = "IDLE"
        self.start_time = time.time()
        self.is_recording = False
        self.output_voice_enabled = True
        self.last_clean_response = ""
        self.command_count = 0

        self.messages = [
            {
                "sender": "SYSTEM",
                "text": f"DEXORTO AI // Minimal Gray HUD Online. Wake-word active (say \"{getattr(config, 'WAKE_WORD', 'dexorto')}\").",
                "time": time.strftime("%H:%M"),
                "color": Palette.CYAN
            },
            {
                "sender": "DEXORTO",
                "text": "All systems online, Dex. Minimal HUD loaded: [Notes] [Weather] [Calculator] [Timer] [RAM Audit] [Smart URLs]. Speak your command or click any protocol.",
                "time": time.strftime("%H:%M"),
                "color": Palette.GREEN
            }
        ]
        self.scroll_y = 0
        self.max_scroll = 0
        self.active_input_text = ""
        self.input_focused = True

        # Animation State
        self.anim_t = 0.0
        self.pulse_phase = 0.0

        # Telemetry, Disk, Weather & Protocols State
        self.cpu_pct = 0
        self.ram_pct = 0
        self.ram_used_gb = 0.0
        self.ram_total_gb = 0.0
        self.disk_pct = 0
        self.disk_used_gb = 0.0
        self.disk_total_gb = 0.0
        self.weather_info = {
            "temp": "35.0°C",
            "city": "Vadodara, IN",
            "desc": "Sunny",
            "humidity": "22%",
            "wind": "5 km/h",
            "feels_like": "34.0°C",
            "last_fetched": 0
        }
        self.last_telemetry_time = 0.0
        self.protocol_btns = []
        self._fetch_weather_async()
        self._update_telemetry()

        # 8. Compute Layout Bounding Rectangles
        self._recalc_layout()

        # 9. Wake Word Listener
        self.wake_listener = WakeWordListener(self.backend, self._on_wake_word)
        self.wake_listener.start()

    def _load_persisted_settings(self):
        """Loads user-persisted settings overrides from user_settings.json."""
        try:
            s_file = os.path.join(str(SCRIPT_DIR), "user_settings.json")
            if os.path.exists(s_file):
                with open(s_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "understand_hindi" in data:
                    self.understand_hindi = data["understand_hindi"]
                    setattr(config, "UNDERSTAND_HINDI", self.understand_hindi)
                if "teach_hindi" in data:
                    setattr(config, "TEACH_HINDI", data["teach_hindi"])
                if "allow_barge_in" in data:
                    self.allow_barge_in = data["allow_barge_in"]
                    setattr(config, "ALLOW_BARGE_IN", self.allow_barge_in)
                if "auto_json_filter" in data:
                    self.auto_json_filter = data["auto_json_filter"]
                    setattr(config, "AUTO_JSON_FILTER", self.auto_json_filter)
                if "prevent_duplicate_apps" in data:
                    self.prevent_duplicate_apps = data["prevent_duplicate_apps"]
                    setattr(config, "PREVENT_DUPLICATE_APPS", self.prevent_duplicate_apps)
                if "reuse_browser_tabs" in data:
                    self.reuse_browser_tabs = data["reuse_browser_tabs"]
                    setattr(config, "REUSE_BROWSER_TABS", self.reuse_browser_tabs)
                if "output_voice_enabled" in data:
                    self.output_voice_enabled = data["output_voice_enabled"]
        except Exception:
            pass

    def _persist_setting(self, key: str, value):
        """Persists a single setting key-value pair to user_settings.json."""
        try:
            s_file = os.path.join(str(SCRIPT_DIR), "user_settings.json")
            data = {}
            if os.path.exists(s_file):
                with open(s_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data[key] = value
            with open(s_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _fetch_weather_async(self):
        """Fetches wttr.in weather data asynchronously in a background thread."""
        def _worker():
            try:
                req = urllib.request.Request("https://wttr.in/?format=j1", headers={"User-Agent": "curl/7.68.0"})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    cur = data["current_condition"][0]
                    area = data["nearest_area"][0]["areaName"][0]["value"]
                    country = data["nearest_area"][0]["country"][0]["value"]
                    self.weather_info = {
                        "temp": f"{cur['temp_C']}°C",
                        "city": f"{area}, {country[:2].upper()}",
                        "desc": cur["weatherDesc"][0]["value"],
                        "humidity": f"{cur['humidity']}%",
                        "wind": f"{cur['windspeedKmph']} km/h",
                        "feels_like": f"{cur['FeelsLikeC']}°C",
                        "last_fetched": time.time(),
                    }
            except Exception:
                pass
        threading.Thread(target=_worker, daemon=True).start()

    def _update_telemetry(self):
        """Reads real-time hardware telemetry without blocking (every 1.5s)."""
        now = time.time()
        if now - self.last_telemetry_time < 1.5:
            return
        self.last_telemetry_time = now

        # Periodic lightweight GC every 30s to keep RAM footprint minimal
        if not hasattr(self, "_last_gc_time"):
            self._last_gc_time = now
        elif now - self._last_gc_time > 30.0:
            self._last_gc_time = now
            gc.collect()
        try:
            load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
            cpu_count = os.cpu_count() or 1
            self.cpu_pct = min(100, int((load / cpu_count) * 100))

            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
            info = {}
            for l in lines:
                parts = l.split(":")
                if len(parts) == 2:
                    info[parts[0].strip()] = int(parts[1].strip().split()[0])
            total = info.get("MemTotal", 0)
            avail = info.get("MemAvailable", 0)
            if total > 0:
                self.ram_pct = int(100 * (1 - avail / total))
                self.ram_total_gb = round(total / (1024 * 1024), 1)
                self.ram_used_gb = round((total - avail) / (1024 * 1024), 1)
        except Exception:
            pass

        try:
            disk = shutil.disk_usage(os.path.expanduser("~"))
            self.disk_used_gb = round(disk.used / (1024**3), 1)
            self.disk_total_gb = round(disk.total / (1024**3), 1)
            self.disk_pct = int(100 * disk.used / disk.total) if disk.total > 0 else 0
        except Exception:
            pass

        if now - getattr(self.weather_info, "last_fetched", 0) > 600:
            self._fetch_weather_async()

    def _recalc_layout(self):
        """Recalculates all UI rectangles for the active window mode (Minimal Gray JARVIS HUD)."""
        if self.mode == "fullscreen":
            self.header_h = 46
            self.header_rect = pygame.Rect(0, 0, self.width, self.header_h)
            self.close_btn_rect = pygame.Rect(self.width - 42, 8, 32, 30)       # [ ✕ ] Cut / Close
            self.mode_btn_rect = pygame.Rect(self.width - 78, 8, 32, 30)        # [ 🗗 ] Restore / Shrink
            self.minimize_btn_rect = pygame.Rect(self.width - 114, 8, 32, 30)   # [ — ] Minimize
            self.settings_btn_rect = pygame.Rect(self.width - 150, 8, 32, 30)   # [ ⚙ ] Settings

            # Available height for main panels (reserving 24px for status bar)
            status_h = 24
            available_h = self.height - self.header_h - status_h - 16
            content_y = self.header_h + 8

            # ── 1. Left Column: 4 System Cards (System Stats, Weather, Protocols, Uptime) ──
            self.left_col_w = min(330, max(280, int(self.width * 0.28)))
            self.left_col_rect = pygame.Rect(14, content_y, self.left_col_w, available_h)

            card_gap = 8
            # Proportional card heights
            h1 = int(available_h * 0.23)
            h2 = int(available_h * 0.25)
            h3 = int(available_h * 0.31)
            h4 = available_h - h1 - h2 - h3 - 3 * card_gap

            self.card_stats_rect = pygame.Rect(14, content_y, self.left_col_w, h1)
            self.card_weather_rect = pygame.Rect(14, self.card_stats_rect.bottom + card_gap, self.left_col_w, h2)
            self.card_deck_rect = pygame.Rect(14, self.card_weather_rect.bottom + card_gap, self.left_col_w, h3)
            self.card_uptime_rect = pygame.Rect(14, self.card_deck_rect.bottom + card_gap, self.left_col_w, h4)

            # Refresh buttons inside cards
            self.stats_refresh_rect = pygame.Rect(self.card_stats_rect.right - 26, self.card_stats_rect.y + 6, 20, 20)
            self.weather_refresh_rect = pygame.Rect(self.card_weather_rect.right - 26, self.card_weather_rect.y + 6, 20, 20)

            # Protocol buttons inside Card 3 (App Deck)
            from config import WEEKLY_STUDY_SCHEDULE
            today_name = datetime.now().strftime("%A")
            today_task = WEEKLY_STUDY_SCHEDULE.get(today_name.lower(), "Study")
            if len(today_task) > 16:
                disp_task = "HALF REST & CS" if ("rest" in today_task.lower() or "cs" in today_task.lower()) else today_task[:16].upper()
            else:
                disp_task = today_task.upper()

            proto_x = self.card_deck_rect.x + 8
            proto_w = self.card_deck_rect.width - 16
            proto_top = self.card_deck_rect.y + 28
            half_w = (proto_w - 6) // 2
            row_h = 24
            row_gap = 4

            r0_y = proto_top
            r1_y = r0_y + row_h + row_gap
            r2_y = r1_y + row_h + row_gap
            r3_y = r2_y + row_h + row_gap
            r4_y = r3_y + row_h + row_gap

            self.protocol_btns = [
                {"id": "tasks", "label": f"📅 TODAY: {disp_task}", "rect": pygame.Rect(proto_x, r0_y, proto_w, row_h), "accent": Palette.GOLD},
                {"id": "notes", "label": "📝 NOTES", "rect": pygame.Rect(proto_x, r1_y, half_w, row_h), "accent": Palette.CYAN},
                {"id": "weather", "label": "🌤 WEATHER", "rect": pygame.Rect(proto_x + half_w + 6, r1_y, half_w, row_h), "accent": Palette.CYAN},
                {"id": "calc", "label": "🧮 CALCULATOR", "rect": pygame.Rect(proto_x, r2_y, half_w, row_h), "accent": Palette.CYAN},
                {"id": "audit", "label": "⚡ RAM AUDIT", "rect": pygame.Rect(proto_x + half_w + 6, r2_y, half_w, row_h), "accent": Palette.GREEN},
                {"id": "music", "label": "► SPOTIFY", "rect": pygame.Rect(proto_x, r3_y, half_w, row_h), "accent": Palette.GREEN},
                {"id": "insta", "label": "💬 INSTAGRAM", "rect": pygame.Rect(proto_x + half_w + 6, r3_y, half_w, row_h), "accent": Palette.GREEN},
                {"id": "teach_hindi", "label": "📖 HINDI TUTOR", "rect": pygame.Rect(proto_x, r4_y, half_w, row_h), "accent": Palette.CYAN},
                {"id": "terminal", "label": "💻 TERMINAL", "rect": pygame.Rect(proto_x + half_w + 6, r4_y, half_w, row_h), "accent": Palette.WHITE_MUTED},
            ]

            # ── 2. Right Column: Conversation Deck (Header, Stream, Input) ──
            self.right_col_w = min(390, max(310, int(self.width * 0.32)))
            right_x = self.width - self.right_col_w - 14
            self.right_col_rect = pygame.Rect(right_x, content_y, self.right_col_w, available_h)

            conv_hdr_y = content_y + 8
            self.conv_clear_rect = pygame.Rect(self.right_col_rect.right - 146, conv_hdr_y, 62, 22)
            self.conv_extract_rect = pygame.Rect(self.right_col_rect.right - 78, conv_hdr_y, 70, 22)

            # Input Bar at bottom of Right Column
            input_h = 38
            self.input_rect = pygame.Rect(self.right_col_rect.x + 8, self.right_col_rect.bottom - input_h - 8, self.right_col_rect.width - 16, input_h)
            send_w = 32
            self.send_btn_rect = pygame.Rect(self.input_rect.right - send_w - 3, self.input_rect.y + 3, send_w, send_w)

            # Chat Stream Area inside Right Column
            chat_top = content_y + 36
            chat_h = (self.input_rect.y - 8) - chat_top
            self.chat_card_rect = pygame.Rect(self.right_col_rect.x + 6, chat_top, self.right_col_rect.width - 12, chat_h)

            # ── 3. Center Column: Hero Arc Reactor Core & Action Controls ──
            center_x = self.left_col_rect.right + 12
            center_w = right_x - center_x - 12
            self.center_col_rect = pygame.Rect(center_x, content_y, center_w, available_h)

            self.reactor_cx = self.center_col_rect.centerx
            self.reactor_cy = self.center_col_rect.y + int(self.center_col_rect.height * 0.38)
            self.reactor_r = min(85, int(self.center_col_rect.width * 0.22), int(self.center_col_rect.height * 0.23))

            self.status_pill_rect = pygame.Rect(self.reactor_cx - 130, self.reactor_cy + self.reactor_r + 48, 260, 26)

            btn_y = self.center_col_rect.bottom - 54
            btn_size = 46
            self.btn_deck_rect = pygame.Rect(self.reactor_cx - btn_size // 2 - 64, btn_y, btn_size, btn_size)
            self.btn_mic_rect = pygame.Rect(self.reactor_cx - btn_size // 2, btn_y, btn_size, btn_size)
            self.btn_stop_rect = pygame.Rect(self.reactor_cx + btn_size // 2 + 18, btn_y, btn_size, btn_size)
            self.btn_spk_rect = self.btn_deck_rect

        else:
            # Compact Floating Widget Mode (360 × 520)
            self.header_h = 38
            self.header_rect = pygame.Rect(0, 0, self.width, self.header_h)
            self.close_btn_rect = pygame.Rect(self.width - 34, 5, 28, 28)       # [ ✕ ] Cut / Close
            self.mode_btn_rect = pygame.Rect(self.width - 66, 5, 28, 28)        # [ 🗖 ] Maximize
            self.minimize_btn_rect = pygame.Rect(self.width - 98, 5, 28, 28)   # [ — ] Minimize
            self.settings_btn_rect = pygame.Rect(self.width - 130, 5, 28, 28)  # [ ⚙ ] Settings

            self.hud_card_rect = pygame.Rect(10, 42, self.width - 20, 100)
            self.reactor_cx = self.hud_card_rect.x + 50
            self.reactor_cy = self.hud_card_rect.centery
            self.reactor_r = 34

            # Compact Quick Utilities Bar (6 dex-bot tool pills)
            c_tools = [
                {"id": "tasks", "label": "📅"},
                {"id": "notes", "label": "📝"},
                {"id": "weather", "label": "🌤"},
                {"id": "calc", "label": "🧮"},
                {"id": "audit", "label": "⚡"},
                {"id": "music", "label": "►"},
            ]
            c_tb_y = 148
            c_tb_w = (self.width - 20 - 5 * 6) // len(c_tools)
            self.compact_tool_btns = []
            for c_i, ct in enumerate(c_tools):
                c_rect = pygame.Rect(10 + c_i * (c_tb_w + 6), c_tb_y, c_tb_w, 24)
                self.compact_tool_btns.append({"id": ct["id"], "label": ct["label"], "rect": c_rect})

            self.chat_card_rect = pygame.Rect(10, 178, self.width - 20, 230)

            ctrl_y = 416
            self.btn_spk_rect = pygame.Rect(10, ctrl_y, 108, 32)
            self.btn_mic_rect = pygame.Rect(self.width // 2 - 18, ctrl_y - 2, 36, 36)
            self.btn_stop_rect = pygame.Rect(self.width - 118, ctrl_y, 108, 32)

            self.input_rect = pygame.Rect(10, 456, self.width - 20, 32)
            send_w = 28
            self.send_btn_rect = pygame.Rect(self.input_rect.right - send_w - 2, self.input_rect.y + 2, send_w, 28)
            self.protocol_btns = []

    def toggle_window_mode(self):
        """Switches between Fullscreen Terminal and Compact Floating Widget."""
        if self.mode == "fullscreen":
            self.mode = "compact"
            self.width = self.compact_w
            self.height = self.compact_h
            self.current_win_x = max(20, self.screen_w - self.width - 24)
            self.current_win_y = 52
        else:
            self.mode = "fullscreen"
            self.width = self.screen_w
            self.height = self.screen_h
            self.current_win_x = 0
            self.current_win_y = 0

        os.environ["SDL_VIDEO_WINDOW_POS"] = f"{self.current_win_x},{self.current_win_y}"
        self.screen = pygame.display.set_mode((self.width, self.height), pygame.NOFRAME)

        # Reposition and re-apply EWMH utility & skip_taskbar rules
        if self.x11:
            self.x11.configure_window(
                self.caption, mode=self.mode, pos_x=self.current_win_x, pos_y=self.current_win_y
            )

        self._recalc_layout()
        self.scroll_y = self.max_scroll
        print(f"[Window] Switched to {self.mode.upper()} mode ({self.width}x{self.height})")

    def minimize_window(self):
        """Minimizes the window while keeping wake-word detector alive."""
        print("[Window] Minimizing Dexorto window (Wake word listener remains active in background)...")
        pygame.display.iconify()
        if hasattr(self, "x11") and self.x11:
            self.x11.iconify_window()

    def _on_wake_word(self, query: str = ""):
        """Triggered when user speaks the wake word 'dexorto'."""
        was_speaking = (self.state == "SPEAKING" or self.backend.is_speaking)

        if was_speaking:
            print("[Interrupt] Wake word barge-in detected during speech! Stopping speech and shifting to wake word...")
            self.stop_actions()
        elif self.state == "LISTENING":
            return
        elif self.state == "THINKING":
            print("[Interrupt] Wake word detected during thinking! Cancelling and shifting to wake word...")
            self.stop_actions()

        if self.x11:
            self.x11.raise_window()

        if query:
            is_spec, clean_cmd = self.backend.is_specific_command(query)
            if is_spec:
                if clean_cmd.lower().strip(".,!? ") in ["stop", "cancel", "shut up", "be quiet", "pause"]:
                    print(f"[Interrupt] Stop command confirmed: '{clean_cmd}'. Returning to IDLE.")
                    self.state = "IDLE"
                    self.wake_listener.resume()
                    return
                print(f"[Wake] Immediate command detected with wake word: '{clean_cmd}'")
                self.submit_query(clean_cmd)
                return

        print("[Wake] Shifted to wake word! Activating listening mode...")
        self.backend.play_wake_chime()
        self.toggle_input_voice()

    # ── IPC Event Bridge ─────────────────────────────────
    def _handle_ipc_event(self, event: dict):
        evt = event.get("event")
        if evt == "daemon_connected":
            self.linked_to_daemon = True
        elif evt == "daemon_disconnected":
            self.linked_to_daemon = False
        elif evt == "status":
            self.state = event.get("state", self.state)
            if "response" in event and event["response"]:
                self._append_message("DEXORTO", event["response"])
        elif evt == "wake":
            self.state = "LISTENING"
            self.is_recording = True
        elif evt == "transcribed":
            prompt = event.get("prompt", "")
            if prompt:
                self._append_message("DEX", prompt)
            self.is_recording = False
        elif evt == "speaking":
            self.state = "SPEAKING"
            self.wake_listener.resume()
            resp = event.get("response", "")
            if resp:
                self._append_message("DEXORTO", resp)
                self.last_clean_response = resp
        elif evt == "speech_done":
            if self.state == "SPEAKING":
                self.state = "IDLE"
        elif evt == "mute_changed":
            self.output_voice_enabled = not event.get("muted", False)

    def _append_message(self, sender: str, text: str):
        if sender == "DEXORTO":
            clean = format_short_clean_response(text, max_sentences=2)
        else:
            clean = re.sub(r'\{[^}]*"action"[^}]*\}', '', text)
            clean = re.sub(r'```[\s\S]*?```', '', clean).strip()
        if not clean:
            return

        if self.messages and self.messages[-1].get("sender") == sender and self.messages[-1].get("text") == clean:
            return

        color = Palette.GREEN if sender == "DEXORTO" else (
            Palette.WHITE_MUTED if sender in ["DEX", "YOU"] else (
                Palette.RED if sender == "ERROR" else Palette.WHITE_DIM
            )
        )

        self.messages.append({
            "sender": sender,
            "text": clean,
            "time": time.strftime("%H:%M"),
            "color": color
        })
        self.scroll_y = 999999

    def wrap_text(self, text: str, max_w: int, font):
        lines = []
        for paragraph in text.split('\n'):
            words = paragraph.split(' ')
            cur = []
            for w in words:
                cand = (' '.join(cur + [w])) if cur else w
                if font.size(cand)[0] <= max_w:
                    cur.append(w)
                else:
                    if cur:
                        lines.append(' '.join(cur))
                    cur = [w]
            if cur:
                lines.append(' '.join(cur))
            elif not paragraph:
                lines.append('')
        return lines

    # ── Interaction Handlers ─────────────────────────────
    def toggle_input_voice(self):
        self.wake_listener.pause()

        if self.linked_to_daemon:
            self.state = "LISTENING"
            self.is_recording = True
            self.ipc_client.send_command({"cmd": "trigger_listen"})
            return

        if self.is_recording:
            self.is_recording = False
            self.state = "IDLE"
            self.wake_listener.resume()
            return

        self.is_recording = True
        self.state = "LISTENING"

        def _worker():
            time.sleep(0.1)
            query = self.backend.transcribe_mic()
            self.is_recording = False
            if query:
                is_spec, clean_cmd = self.backend.is_specific_command(query)
                if is_spec:
                    self.submit_query(clean_cmd)
                else:
                    print(f"[Voice] Non-specific speech filtered: '{query}' -> stopping until keyword called.")
                    self.state = "IDLE"
            else:
                self.state = "IDLE"
            self.wake_listener.resume()

        threading.Thread(target=_worker, daemon=True).start()

    def toggle_output_voice(self):
        self.output_voice_enabled = not self.output_voice_enabled
        if self.linked_to_daemon:
            self.ipc_client.send_command({"cmd": "toggle_mute"})
        else:
            if not self.output_voice_enabled:
                self.backend.stop_tts()

    def cycle_voice_model(self, target: str = "cycle"):
        """Switches active voice model (female, male, hindi, british, us) and confirms."""
        if self.linked_to_daemon:
            self.ipc_client.send_command({"cmd": "change_voice", "target": target})
            return

        ok, new_key, msg = change_voice(target)
        if ok:
            if hasattr(self, "backend") and self.backend:
                self.backend.tts_voice = new_key
            self._append_message("SYSTEM", msg)
            if self.output_voice_enabled:
                self.state = "SPEAKING"
                self.backend.play_tts(msg, on_finished=lambda: (
                    setattr(self, "state", "IDLE") if self.state == "SPEAKING" else None
                ))

    def cycle_persona(self, target: str = "cycle"):
        """Switches active AI persona (JARVIS, Friday, Edith, Hindi Mitra, Custom) and updates prompt & voice."""
        if target == "cycle":
            ok, p, msg = PersonaManager.cycle_persona()
        else:
            ok, p, msg = PersonaManager.set_active_persona(target)
        if ok:
            if hasattr(self, "backend") and self.backend and p.get("voice_key"):
                self.backend.tts_voice = p["voice_key"]
            self._append_message("SYSTEM", msg)
            if self.output_voice_enabled:
                self.state = "SPEAKING"
                self.backend.play_tts(msg, on_finished=lambda: (
                    setattr(self, "state", "IDLE") if self.state == "SPEAKING" else None
                ))
            return p
        return None

    def stop_actions(self):
        if self.linked_to_daemon:
            self.ipc_client.send_command({"cmd": "stop"})
        self.backend.stop_tts()
        self.is_recording = False
        self.state = "IDLE"
        self.wake_listener.resume()

    def replay_last(self):
        if self.linked_to_daemon:
            self.ipc_client.send_command({"cmd": "replay"})
            return
        if self.last_clean_response and self.output_voice_enabled:
            self.state = "SPEAKING"
            self.wake_listener.resume()
            self.backend.play_tts(self.last_clean_response, on_finished=lambda: (
                setattr(self, "state", "IDLE") if self.state == "SPEAKING" else None
            ))

    def submit_query(self, query: str):
        query = query.strip()
        if not query:
            return

        # Check /rem slash command directly (permanent remember)
        m_rem = re.match(r'^[/\\]\s*rem(?:ember)?(?:\s+forever)?\b\s*[:,-]?\s*(.*)$', query, re.I)
        if m_rem:
            content = m_rem.group(1).strip()
            if content:
                ok, item, msg = MemoryManager.add_permanent_memory(content, source="slash_rem")
            else:
                msg = "Please specify what you want me to remember forever, Dex."
            clean = format_short_clean_response(msg, max_sentences=2)
            self._append_message("DEX", query)
            self._append_message("DEXORTO", clean)
            self.last_clean_response = clean
            self.active_input_text = ""
            if self.output_voice_enabled:
                self.state = "SPEAKING"
                self.wake_listener.resume()
                self.backend.play_tts(clean, on_finished=lambda: (
                    setattr(self, "state", "IDLE") if self.state == "SPEAKING" else None
                ))
            else:
                self.state = "IDLE"
                self.wake_listener.resume()
            return

        # If user didn't say anything specific, take NO action, use NO idle texts, stop until keyword called
        is_spec, clean_query = self.backend.is_specific_command(query)
        if not is_spec:
            print(f"[Query] Non-specific query filtered: '{query}' -> stopping until keyword called.")
            self.state = "IDLE"
            self.wake_listener.resume()
            return

        self.command_count += 1
        self._append_message("DEX", clean_query)
        self.active_input_text = ""

        # Native Hindi / Hinglish intent processing
        if getattr(self, "understand_hindi", True):
            hindi_handled, hindi_reply = parse_hindi_command_intent(clean_query)
            if hindi_handled:
                clean = format_short_clean_response(hindi_reply, max_sentences=2)
                self._append_message("DEXORTO", clean)
                self.last_clean_response = clean
                MemoryManager.record_session_interaction(clean_query, clean)
                if self.output_voice_enabled:
                    self.state = "SPEAKING"
                    self.wake_listener.resume()
                    self.backend.play_tts(clean, on_finished=lambda: (
                        setattr(self, "state", "IDLE") if self.state == "SPEAKING" else None
                    ))
                else:
                    self.state = "IDLE"
                    self.wake_listener.resume()
                return

        if self.linked_to_daemon:
            self.ipc_client.send_command({"cmd": "query", "text": clean_query})
            self.state = "THINKING"
            return

        self.state = "THINKING"
        self.wake_listener.resume()

        def _worker():
            reply = self.backend.ask_brain(clean_query)

            # Check Tavily search
            s_match = re.search(r'\{[^}]*"action"\s*:\s*"search"[^}]*"query"\s*:\s*"([^"]*)"[^}]*\}', reply)
            if s_match and self.backend.tavily_client:
                sterm = s_match.group(1)
                self.state = "SEARCHING"
                results = self.backend.search_tavily(sterm)
                if results:
                    followup = f"Web search results for '{sterm}':\n{results}\n\nAnswer in 1 concise sentence without markdown or lists."
                    self.state = "THINKING"
                    reply = self.backend.ask_brain(followup)

            clean = format_short_clean_response(reply, max_sentences=2)
            self._append_message("DEXORTO", clean)
            self.last_clean_response = clean
            self.backend.run_actions(reply, clean_query)
            MemoryManager.record_session_interaction(clean_query, clean)

            if self.output_voice_enabled:
                self.state = "SPEAKING"
                self.wake_listener.resume()
                self.backend.play_tts(clean, on_finished=lambda: (
                    setattr(self, "state", "IDLE") if self.state == "SPEAKING" else None
                ))
            else:
                self.state = "IDLE"
                self.wake_listener.resume()

        threading.Thread(target=_worker, daemon=True).start()

    # ══════════════════════════════════════════════════════
    # RENDERING METHODS
    # ══════════════════════════════════════════════════════

    def draw_hud_frame(self, rect, title="", accent=Palette.CYAN, refresh_rect=None):
        """Draws minimal slate-gray HUD card frame with subtle border and crisp header."""
        pygame.draw.rect(self.screen, Palette.CARD_BG, rect, border_radius=8)
        pygame.draw.rect(self.screen, Palette.CARD_BORDER, rect, 1, border_radius=8)

        # Header ribbon
        if title:
            t_surf = self.font_card_title.render(title, True, Palette.WHITE)
            self.screen.blit(t_surf, (rect.x + 12, rect.y + 7))

            # Optional refresh button [ ⟳ ] on right side of card header
            if refresh_rect:
                m_pos = pygame.mouse.get_pos()
                r_hover = refresh_rect.collidepoint(m_pos)
                r_col = Palette.CYAN if r_hover else Palette.WHITE_DIM
                rcx, rcy = refresh_rect.centerx, refresh_rect.centery
                pygame.draw.circle(self.screen, r_col, (rcx, rcy), 5, 1)
                pygame.draw.line(self.screen, r_col, (rcx + 2, rcy - 4), (rcx + 5, rcy - 1), 2)

    def draw_stat_box(self, rect, label, value, accent=Palette.WHITE):
        """Draws a minimal gray stat capsule as in the reference image."""
        pygame.draw.rect(self.screen, Palette.CARD_BG_ELEVATED, rect, border_radius=6)
        pygame.draw.rect(self.screen, Palette.CARD_BORDER, rect, 1, border_radius=6)
        lbl_surf = self.font_stat_lbl.render(label, True, Palette.STAT_LABEL)
        val_surf = self.font_stat_val.render(str(value), True, accent)
        self.screen.blit(lbl_surf, (rect.centerx - lbl_surf.get_width() // 2, rect.y + 4))
        self.screen.blit(val_surf, (rect.centerx - val_surf.get_width() // 2, rect.bottom - val_surf.get_height() - 4))

    def draw_smooth_progress_bar(self, x, y, w, h, pct, color=Palette.CYAN):
        """Draws a sleek minimal tech progress bar."""
        track_rect = pygame.Rect(x, y, w, h)
        pygame.draw.rect(self.screen, (16, 27, 39), track_rect, border_radius=max(2, h // 2))
        fill_w = max(0, min(w, int(w * (max(0, min(100, pct)) / 100.0))))
        if fill_w > 0:
            fill_rect = pygame.Rect(x, y, fill_w, h)
            pygame.draw.rect(self.screen, color, fill_rect, border_radius=max(2, h // 2))

    def draw_arc_reactor(self, cx, cy, radius, is_rec=False, is_spk=False):
        """Renders Stark Arc Reactor with concentric rotating tick rings and pulsing core."""
        num_ticks = 28
        angle_offset = self.anim_t * 0.8
        tick_color = Palette.RED if is_rec else (Palette.GREEN if is_spk else (28, 48, 68))
        for i in range(num_ticks):
            ang = angle_offset + (2 * math.pi / num_ticks) * i
            x1 = cx + int((radius + 5) * math.cos(ang))
            y1 = cy + int((radius + 5) * math.sin(ang))
            x2 = cx + int(radius * math.cos(ang))
            y2 = cy + int(radius * math.sin(ang))
            pygame.draw.line(self.screen, tick_color, (x1, y1), (x2, y2), 1)

        # Concentric tech tracks
        pygame.draw.circle(self.screen, (20, 36, 52), (cx, cy), radius - 4, 1)
        pygame.draw.circle(self.screen, Palette.CYAN_MUTED, (cx, cy), radius - 12, 1)
        pygame.draw.circle(self.screen, (16, 28, 42), (cx, cy), radius - 18, 1)

        # Inner dark aperture
        iris_r = radius - 24
        pygame.draw.circle(self.screen, (7, 11, 16), (cx, cy), iris_r)
        pygame.draw.circle(self.screen, (24, 38, 54), (cx, cy), iris_r, 1)

        # Horizontal Soundwave Bars (▪ ▪ ▪ ▪ ▪)
        bar_count = 5
        bar_w = max(6, int(radius * 0.16))
        bar_gap = max(3, int(radius * 0.08))
        total_w = bar_count * bar_w + (bar_count - 1) * bar_gap
        start_bx = cx - total_w // 2

        for i in range(bar_count):
            bx = start_bx + i * (bar_w + bar_gap)
            if is_spk:
                bh = 6 + int(math.sin(self.anim_t * 9.0 + i * 1.2) * 12 + 14)
                b_col = Palette.GREEN
            elif is_rec:
                bh = 6 + int(math.sin(self.anim_t * 8.0 + i * 0.9) * 10 + 12)
                b_col = Palette.RED
            elif self.state == "THINKING":
                bh = 4 + int(math.sin(self.anim_t * 5.0 + i * 0.7) * 7 + 8)
                b_col = Palette.CYAN
            else:
                bh = 4 + int(math.sin(self.anim_t * 2.0 + i * 0.5) * 3 + 4)
                b_col = Palette.CYAN

            bh = max(4, min(int(iris_r * 1.5), bh))
            bar_rect = pygame.Rect(bx, cy - bh // 2, bar_w, bh)
            pygame.draw.rect(self.screen, b_col, bar_rect, border_radius=3)

    def draw_gauge_bar(self, x, y, w, h, pct, label, val_str, color=Palette.CYAN):
        """Draws segmented telemetry bar gauge."""
        lbl = self.font_stat_lbl.render(label, True, Palette.WHITE_MUTED)
        val = self.font_stat_lbl.render(val_str, True, color)
        self.screen.blit(lbl, (x, y))
        self.screen.blit(val, (x + w - val.get_width(), y))
        self.draw_smooth_progress_bar(x, y + 16, w, h, pct, color)

    def draw_acoustic_radar(self, x, y, w, h, is_rec=False, is_spk=False):
        """Draws live animated acoustic equalizer spectrum."""
        bar_count = 16
        gap = 3
        bar_w = max(3, (w - (bar_count - 1) * gap) // bar_count)
        base_y = y + h - 4
        active_color = Palette.RED if is_rec else (Palette.GREEN if is_spk else Palette.CYAN)

        for i in range(bar_count):
            bx = x + i * (bar_w + gap)
            if is_spk:
                bh = 6 + int(math.sin(self.anim_t * 9.0 + i * 0.75) * (h * 0.35) + (h * 0.4))
            elif is_rec:
                bh = 6 + int(math.sin(self.anim_t * 7.5 + i * 0.55) * (h * 0.28) + (h * 0.32))
            else:
                bh = 3 + int(math.sin(self.anim_t * 2.2 + i * 0.4) * (h * 0.12) + (h * 0.14))

            bh = max(3, min(h - 6, bh))
            pygame.draw.rect(self.screen, active_color, (bx, base_y - bh, bar_w, bh), border_radius=1)

    def draw_header(self):
        """Draws top navigation bar matching the reference image."""
        pygame.draw.rect(self.screen, (7, 11, 16), self.header_rect)
        pygame.draw.line(self.screen, (20, 32, 45), (0, self.header_h - 1), (self.width, self.header_h - 1), 1)

        mouse_pos = pygame.mouse.get_pos()

        if self.mode == "fullscreen":
            # Left: D . E . X . O . R . T . O in spaced cyan font
            title_surf = self.font_hud_title.render("D . E . X . O . R . T . O", True, Palette.CYAN)
            self.screen.blit(title_surf, (16, 12))

            # Online Pill Badge
            online_rect = pygame.Rect(title_surf.get_width() + 28, 12, 68, 22)
            pygame.draw.rect(self.screen, (14, 22, 32), online_rect, border_radius=11)
            pygame.draw.rect(self.screen, (24, 38, 52), online_rect, 1, border_radius=11)
            pygame.draw.circle(self.screen, Palette.GREEN, (online_rect.x + 12, online_rect.centery), 4)
            on_txt = self.font_stat_lbl.render("Online", True, Palette.WHITE)
            self.screen.blit(on_txt, (online_rect.x + 22, online_rect.centery - on_txt.get_height() // 2))

            # Center: Live Time & Date Capsule
            now = datetime.now()
            time_str = now.strftime("%I:%M:%S %p")
            date_str = now.strftime("%B %d, %Y")
            clock_str = f"🕐  {time_str}  |  {date_str}"
            clk_surf = self.font_stat_val.render(clock_str, True, Palette.WHITE_MUTED)
            cw = clk_surf.get_width() + 28
            clk_rect = pygame.Rect(self.width // 2 - cw // 2, 10, cw, 26)
            pygame.draw.rect(self.screen, (12, 18, 26), clk_rect, border_radius=13)
            pygame.draw.rect(self.screen, (24, 38, 52), clk_rect, 1, border_radius=13)
            self.screen.blit(clk_surf, (clk_rect.centerx - clk_surf.get_width() // 2, clk_rect.centery - clk_surf.get_height() // 2))

            # Right: Weather Capsule
            temp_disp = self.weather_info.get("temp", "35°C")
            city_disp = self.weather_info.get("city", "Vadodara").split(",")[0]
            w_str = f"🌡  {temp_disp} {city_disp}"
            w_surf = self.font_stat_val.render(w_str, True, Palette.WHITE_MUTED)
            ww = w_surf.get_width() + 20
            w_rect = pygame.Rect(self.settings_btn_rect.x - ww - 12, 10, ww, 26)
            pygame.draw.rect(self.screen, (12, 18, 26), w_rect, border_radius=13)
            pygame.draw.rect(self.screen, (24, 38, 52), w_rect, 1, border_radius=13)
            self.screen.blit(w_surf, (w_rect.centerx - w_surf.get_width() // 2, w_rect.centery - w_surf.get_height() // 2))

        else:
            # Compact Mode Header
            title_surf = self.font_title.render("D . E . X . O . R . T . O", True, Palette.CYAN)
            self.screen.blit(title_surf, (14, 10))

            dot_color = Palette.RED if (self.state == "LISTENING" or self.is_recording) else Palette.GREEN
            pygame.draw.circle(self.screen, dot_color, (title_surf.get_width() + 26, 18), 4)

        # ── Window Controls ────────────────
        # 1. Close Button [ ✕ ]
        close_hover = self.close_btn_rect.collidepoint(mouse_pos)
        pygame.draw.rect(self.screen, Palette.RED if close_hover else (16, 22, 30), self.close_btn_rect, border_radius=6)
        if close_hover:
            pygame.draw.rect(self.screen, (255, 120, 120), self.close_btn_rect, 1, border_radius=6)
        cx, cy = self.close_btn_rect.centerx, self.close_btn_rect.centery
        d = 4 if self.mode == "compact" else 5
        x_col = Palette.WHITE if close_hover else Palette.WHITE_MUTED
        pygame.draw.line(self.screen, x_col, (cx - d, cy - d), (cx + d, cy + d), 2)
        pygame.draw.line(self.screen, x_col, (cx - d, cy + d), (cx + d, cy - d), 2)

        # 2. Mode Toggle Button [ 🗖 / 🗗 ]
        mode_hover = self.mode_btn_rect.collidepoint(mouse_pos)
        pygame.draw.rect(self.screen, (24, 36, 48) if mode_hover else (16, 22, 30), self.mode_btn_rect, border_radius=6)
        if mode_hover:
            pygame.draw.rect(self.screen, Palette.CYAN, self.mode_btn_rect, 1, border_radius=6)
        cx, cy = self.mode_btn_rect.centerx, self.mode_btn_rect.centery
        m_col = Palette.CYAN if mode_hover else Palette.WHITE_MUTED
        if self.mode == "compact":
            pygame.draw.rect(self.screen, m_col, pygame.Rect(cx - 5, cy - 5, 10, 10), 1)
            pygame.draw.line(self.screen, m_col, (cx - 5, cy - 3), (cx + 5, cy - 3), 1)
        else:
            pygame.draw.rect(self.screen, m_col, pygame.Rect(cx - 2, cy - 6, 8, 8), 1)
            pygame.draw.rect(self.screen, (16, 22, 30), pygame.Rect(cx - 6, cy - 2, 8, 8))
            pygame.draw.rect(self.screen, m_col, pygame.Rect(cx - 6, cy - 2, 8, 8), 1)

        # 3. Minimize Button [ — ]
        min_hover = self.minimize_btn_rect.collidepoint(mouse_pos)
        pygame.draw.rect(self.screen, (24, 36, 48) if min_hover else (16, 22, 30), self.minimize_btn_rect, border_radius=6)
        if min_hover:
            pygame.draw.rect(self.screen, Palette.WHITE, self.minimize_btn_rect, 1, border_radius=6)
        cx, cy = self.minimize_btn_rect.centerx, self.minimize_btn_rect.centery
        min_col = Palette.WHITE if min_hover else Palette.WHITE_MUTED
        pygame.draw.line(self.screen, min_col, (cx - 5, cy + 3), (cx + 5, cy + 3), 2)

        # 4. Settings Button [ ⚙ ]
        set_hover = self.settings_btn_rect.collidepoint(mouse_pos)
        pygame.draw.rect(self.screen, (24, 36, 48) if (set_hover or self.settings_open) else (16, 22, 30), self.settings_btn_rect, border_radius=6)
        set_col = Palette.GOLD if self.settings_open else (Palette.CYAN if set_hover else Palette.WHITE_MUTED)
        if set_hover or self.settings_open:
            pygame.draw.rect(self.screen, set_col, self.settings_btn_rect, 1, border_radius=6)
        cx, cy = self.settings_btn_rect.centerx, self.settings_btn_rect.centery
        r_in = 3
        r_out = 6
        spin = (self.anim_t * 2.0) if self.settings_open else 0.0
        for i in range(6):
            ang = spin + i * (math.pi / 3.0)
            tx1 = cx + int(r_in * math.cos(ang))
            ty1 = cy + int(r_in * math.sin(ang))
            tx2 = cx + int(r_out * math.cos(ang))
            ty2 = cy + int(r_out * math.sin(ang))
            pygame.draw.line(self.screen, set_col, (tx1, ty1), (tx2, ty2), 2)
        pygame.draw.circle(self.screen, set_col, (cx, cy), r_in + 1, 1)

    def draw_stats_card(self, rect):
        """Draws Card 1: System Stats with CPU/RAM progress bars and 3 stat boxes."""
        self.draw_hud_frame(rect, "⚙ System Stats", refresh_rect=self.stats_refresh_rect)

        bar_x = rect.x + 12
        bar_w = rect.width - 24
        y_cursor = rect.y + 30

        # CPU Usage Bar
        cpu_lbl = self.font_stat_lbl.render("CPU Usage", True, Palette.WHITE_MUTED)
        cpu_val = self.font_stat_lbl.render(f"{self.cpu_pct}%", True, Palette.CYAN)
        self.screen.blit(cpu_lbl, (bar_x, y_cursor))
        self.screen.blit(cpu_val, (bar_x + bar_w - cpu_val.get_width(), y_cursor))
        self.draw_smooth_progress_bar(bar_x, y_cursor + 14, bar_w, 6, self.cpu_pct, Palette.CYAN)

        y_cursor += 26

        # RAM Usage Bar
        ram_lbl = self.font_stat_lbl.render("RAM Usage", True, Palette.WHITE_MUTED)
        ram_val = self.font_stat_lbl.render(f"{self.ram_used_gb} GB", True, Palette.CYAN)
        self.screen.blit(ram_lbl, (bar_x, y_cursor))
        self.screen.blit(ram_val, (bar_x + bar_w - ram_val.get_width(), y_cursor))
        self.draw_smooth_progress_bar(bar_x, y_cursor + 14, bar_w, 6, self.ram_pct, Palette.CYAN)

        # 3 Stat Boxes Row
        box_y = y_cursor + 24
        box_h = max(24, rect.bottom - box_y - 8)
        num_boxes = 3
        box_gap = 6
        box_w = (bar_w - (num_boxes - 1) * box_gap) // num_boxes

        b1 = pygame.Rect(bar_x, box_y, box_w, box_h)
        b2 = pygame.Rect(bar_x + box_w + box_gap, box_y, box_w, box_h)
        b3 = pygame.Rect(bar_x + 2 * (box_w + box_gap), box_y, box_w, box_h)

        self.draw_stat_box(b1, "CPU", f"{self.cpu_pct}%", Palette.WHITE)
        self.draw_stat_box(b2, "Memory", f"{self.ram_pct}%", Palette.WHITE)
        disk_str = f"{int(self.disk_used_gb)}/{int(self.disk_total_gb)} GB" if self.disk_total_gb > 0 else "80/180 GB"
        self.draw_stat_box(b3, "Disk", disk_str, Palette.WHITE)

    def draw_weather_card(self, rect):
        """Draws Card 2: Weather with temperature, condition, procedural graphic, and 3 stat boxes."""
        self.draw_hud_frame(rect, "☁ Weather", refresh_rect=self.weather_refresh_rect)

        bar_x = rect.x + 12
        bar_w = rect.width - 24
        y_cursor = rect.y + 28

        # Big Temp
        temp_str = self.weather_info.get("temp", "35.0°C")
        t_surf = self.font_big_temp.render(temp_str, True, Palette.WHITE)
        self.screen.blit(t_surf, (bar_x, y_cursor))

        # City & Description
        city_str = self.weather_info.get("city", "Vadodara, IN")
        desc_str = self.weather_info.get("desc", "Sunny").capitalize()
        c_surf = self.font_stat_lbl.render(city_str, True, Palette.WHITE_MUTED)
        d_surf = self.font_stat_lbl.render(desc_str, True, Palette.WHITE_DIM)
        self.screen.blit(c_surf, (bar_x, y_cursor + 28))
        self.screen.blit(d_surf, (bar_x, y_cursor + 42))

        # Procedural Weather Icon on the right
        wx = rect.right - 54
        wy = y_cursor + 6
        pygame.draw.circle(self.screen, (180, 205, 230), (wx + 10, wy + 16), 9)
        pygame.draw.circle(self.screen, (210, 230, 250), (wx + 22, wy + 10), 13)
        pygame.draw.circle(self.screen, (180, 205, 230), (wx + 34, wy + 16), 9)
        pygame.draw.rect(self.screen, (180, 205, 230), (wx + 10, wy + 16, 24, 9), border_radius=2)
        pygame.draw.circle(self.screen, Palette.GOLD, (wx + 34, wy + 5), 6)

        # 3 Stat Boxes Row
        box_y = rect.bottom - 46
        box_h = 38
        num_boxes = 3
        box_gap = 6
        box_w = (bar_w - (num_boxes - 1) * box_gap) // num_boxes

        b1 = pygame.Rect(bar_x, box_y, box_w, box_h)
        b2 = pygame.Rect(bar_x + box_w + box_gap, box_y, box_w, box_h)
        b3 = pygame.Rect(bar_x + 2 * (box_w + box_gap), box_y, box_w, box_h)

        self.draw_stat_box(b1, "Humidity", self.weather_info.get("humidity", "22%"), Palette.WHITE)
        self.draw_stat_box(b2, "Wind", self.weather_info.get("wind", "5 km/h"), Palette.WHITE)
        self.draw_stat_box(b3, "Feels Like", self.weather_info.get("feels_like", "34.0°C"), Palette.WHITE)

    def draw_deck_card(self, rect):
        """Draws Card 3: Quick Protocols & Apps Deck with TODAY schedule and dex-bot suite."""
        self.draw_hud_frame(rect, "⚡ Quick Protocols & Apps")

        m_pos = pygame.mouse.get_pos()
        for btn in self.protocol_btns:
            r = btn["rect"]
            if r.bottom > rect.bottom - 4:
                continue
            hover = r.collidepoint(m_pos)
            accent = btn.get("accent", Palette.CYAN)
            btn_bg = (20, 31, 45) if hover else Palette.CARD_BG_ELEVATED
            btn_border = accent if hover else Palette.CARD_BORDER
            btn_txt_c = Palette.WHITE if hover else Palette.WHITE_MUTED

            pygame.draw.rect(self.screen, btn_bg, r, border_radius=5)
            pygame.draw.rect(self.screen, btn_border, r, 1, border_radius=5)
            pygame.draw.rect(self.screen, accent, (r.x + 2, r.y + 4, 2, r.height - 8), border_radius=1)

            b_surf = self.font_btn.render(btn["label"], True, btn_txt_c)
            self.screen.blit(b_surf, (r.x + 8, r.centery - b_surf.get_height() // 2))

    def draw_uptime_card(self, rect):
        """Draws Card 4: System Uptime with running timer and session diagnostics."""
        self.draw_hud_frame(rect, "⏱ System Uptime")

        bar_x = rect.x + 12
        bar_w = rect.width - 24
        y_cursor = rect.y + 28

        secs = int(time.time() - getattr(self, "start_time", time.time()))
        uptime_str = f"{secs//3600:02d}:{(secs%3600)//60:02d}:{secs%60:02d}"

        u_lbl = self.font_stat_lbl.render("System Running For:", True, Palette.WHITE_MUTED)
        u_val = self.font_mono_sm.render(uptime_str, True, Palette.WHITE)
        self.screen.blit(u_lbl, (bar_x, y_cursor))
        self.screen.blit(u_val, (bar_x + bar_w - u_val.get_width(), y_cursor))

        y_cursor += 18
        # 2 mini boxes: Session & Commands
        num_boxes = 2
        box_gap = 6
        box_w = (bar_w - (num_boxes - 1) * box_gap) // num_boxes
        box_h = 30

        b1 = pygame.Rect(bar_x, y_cursor, box_w, box_h)
        b2 = pygame.Rect(bar_x + box_w + box_gap, y_cursor, box_w, box_h)
        self.draw_stat_box(b1, "Session", "1", Palette.CYAN)
        self.draw_stat_box(b2, "Commands", str(self.command_count), Palette.CYAN)

        y_cursor += box_h + 8
        if y_cursor + 18 <= rect.bottom - 4:
            load_lbl = self.font_stat_lbl.render("System Load", True, Palette.STAT_LABEL)
            load_val = self.font_stat_lbl.render("Optimal (26%)", True, Palette.GREEN)
            self.screen.blit(load_lbl, (bar_x, y_cursor))
            self.screen.blit(load_val, (bar_x + bar_w - load_val.get_width(), y_cursor))
            self.draw_smooth_progress_bar(bar_x, y_cursor + 14, bar_w, 4, 26, Palette.GREEN)

    def draw_center_column(self, rect):
        """Draws Center Column: The Hero Arc Reactor & Voice HUD (matching reference UI)."""
        is_spk = (self.state == "SPEAKING")
        is_rec = (self.state == "LISTENING" or self.is_recording)

        cx = self.reactor_cx
        cy = self.reactor_cy
        r = self.reactor_r

        # 1. Subtle Outer Ambient Glow Ring
        glow_size = r * 2 + 40
        glow_surf = pygame.Surface((glow_size, glow_size), pygame.SRCALPHA)
        ring_col = (0, 210, 255, 30) if not is_rec else (255, 68, 85, 35)
        pygame.draw.circle(glow_surf, ring_col, (glow_size // 2, glow_size // 2), r + 16, 2)
        self.screen.blit(glow_surf, (cx - glow_size // 2, cy - glow_size // 2))

        # 2. Outer Rotating Segmented / Tick Ring
        num_ticks = 28
        ang_off = self.anim_t * 0.8
        tick_col = Palette.RED if is_rec else (Palette.GREEN if is_spk else (28, 48, 68))
        for i in range(num_ticks):
            ang = ang_off + (2 * math.pi / num_ticks) * i
            x1 = cx + int((r + 6) * math.cos(ang))
            y1 = cy + int((r + 6) * math.sin(ang))
            x2 = cx + int(r * math.cos(ang))
            y2 = cy + int(r * math.sin(ang))
            pygame.draw.line(self.screen, tick_col, (x1, y1), (x2, y2), 1)

        # 3. Concentric Technical Thin Circles
        pygame.draw.circle(self.screen, (20, 36, 52), (cx, cy), r - 4, 1)
        pygame.draw.circle(self.screen, Palette.CYAN_MUTED, (cx, cy), r - 12, 1)
        pygame.draw.circle(self.screen, (16, 28, 42), (cx, cy), r - 18, 1)

        # 4. Deep Dark Iris Aperture
        iris_r = r - 24
        pygame.draw.circle(self.screen, (7, 11, 16), (cx, cy), iris_r)
        pygame.draw.circle(self.screen, (24, 38, 54), (cx, cy), iris_r, 1)

        # 5. Center Horizontal Soundwave Equalizer Bars (▪ ▪ ▪ ▪ ▪)
        bar_count = 5
        bar_w = 12
        bar_gap = 6
        total_w = bar_count * bar_w + (bar_count - 1) * bar_gap
        start_bx = cx - total_w // 2

        for i in range(bar_count):
            bx = start_bx + i * (bar_w + bar_gap)
            if is_spk:
                bh = 6 + int(math.sin(self.anim_t * 9.0 + i * 1.2) * 12 + 14)
                b_col = Palette.GREEN
            elif is_rec:
                bh = 6 + int(math.sin(self.anim_t * 8.0 + i * 0.9) * 10 + 12)
                b_col = Palette.RED
            elif self.state == "THINKING":
                bh = 4 + int(math.sin(self.anim_t * 5.0 + i * 0.7) * 7 + 8)
                b_col = Palette.CYAN
            else:
                bh = 4 + int(math.sin(self.anim_t * 2.0 + i * 0.5) * 3 + 4)
                b_col = Palette.CYAN

            bh = max(4, min(36, bh))
            bar_rect = pygame.Rect(bx, cy - bh // 2, bar_w, bh)
            pygame.draw.rect(self.screen, b_col, bar_rect, border_radius=3)

        # 6. Spaced D.E.X.O.R.T.O Header below Arc Core
        title_y = cy + r + 24
        title_text = "D . E . X . O . R . T . O"
        t_surf = self.font_hud_title.render(title_text, True, Palette.WHITE)
        self.screen.blit(t_surf, (cx - t_surf.get_width() // 2, title_y))

        # 7. Status Badge Pill below title
        pill_y = title_y + 32
        is_muted = not self.output_voice_enabled
        _, _, badge_label, badge_color = self.emotion_engine.get_emotion(
            self.state, is_rec, is_spk, is_muted
        )
        status_str = f"●  {badge_label}"
        if self.state == "IDLE":
            status_str = f"●  Listening for wake word..."

        st_surf = self.font_badge.render(status_str, True, Palette.WHITE_MUTED)
        pw = st_surf.get_width() + 24
        ph = 26
        pill_rect = pygame.Rect(cx - pw // 2, pill_y, pw, ph)
        pygame.draw.rect(self.screen, (14, 22, 32), pill_rect, border_radius=13)
        pygame.draw.rect(self.screen, (24, 38, 52), pill_rect, 1, border_radius=13)

        dot_c = Palette.RED if is_rec else (Palette.GREEN if self.state == "IDLE" else Palette.CYAN)
        pygame.draw.circle(self.screen, dot_c, (pill_rect.x + 14, pill_rect.centery), 4)
        lbl_surf = self.font_badge.render(status_str[2:], True, Palette.WHITE)
        self.screen.blit(lbl_surf, (pill_rect.x + 24, pill_rect.centery - lbl_surf.get_height() // 2))

        # 8. Bottom 3 Control Buttons [ ⚡ ] [ 🎙 ] [ ⏹ ]
        m_pos = pygame.mouse.get_pos()

        # Left: Quick Apps / Protocols Toggle [ ⚡ ]
        d_hover = self.btn_deck_rect.collidepoint(m_pos)
        pygame.draw.rect(self.screen, (20, 31, 45) if d_hover else (13, 20, 29), self.btn_deck_rect, border_radius=8)
        pygame.draw.rect(self.screen, Palette.CYAN if d_hover else (24, 38, 52), self.btn_deck_rect, 1, border_radius=8)
        d_surf = self.font_btn.render("⚡", True, Palette.CYAN if d_hover else Palette.WHITE_MUTED)
        self.screen.blit(d_surf, (self.btn_deck_rect.centerx - d_surf.get_width() // 2, self.btn_deck_rect.centery - d_surf.get_height() // 2))

        # Center: Hero Mic Button [ 🎙 ]
        mic_hover = self.btn_mic_rect.collidepoint(m_pos)
        mic_col = Palette.RED if is_rec else (Palette.CYAN if mic_hover else Palette.CYAN_MUTED)
        mic_bg = (38, 14, 20) if is_rec else ((20, 34, 48) if mic_hover else (13, 20, 29))
        pygame.draw.rect(self.screen, mic_bg, self.btn_mic_rect, border_radius=8)
        pygame.draw.rect(self.screen, mic_col, self.btn_mic_rect, 1, border_radius=8)

        mcx = self.btn_mic_rect.centerx
        mcy = self.btn_mic_rect.centery
        icon_c = Palette.WHITE if is_rec else mic_col
        pygame.draw.rect(self.screen, icon_c, (mcx - 4, mcy - 8, 8, 11), border_radius=4)
        pygame.draw.arc(self.screen, icon_c, (mcx - 7, mcy - 5, 14, 11), math.pi, 2 * math.pi, 2)
        pygame.draw.line(self.screen, icon_c, (mcx, mcy + 6), (mcx, mcy + 10), 2)
        pygame.draw.line(self.screen, icon_c, (mcx - 5, mcy + 10), (mcx + 5, mcy + 10), 2)

        # Right: Stop / Abort Button [ ⏹ ]
        s_hover = self.btn_stop_rect.collidepoint(m_pos)
        is_busy = (self.state in ["SPEAKING", "LISTENING", "THINKING"])
        stop_col = Palette.RED if is_busy else (Palette.WHITE if s_hover else Palette.WHITE_MUTED)
        stop_bg = (38, 14, 20) if (is_busy and s_hover) else ((20, 31, 45) if s_hover else (13, 20, 29))
        pygame.draw.rect(self.screen, stop_bg, self.btn_stop_rect, border_radius=8)
        pygame.draw.rect(self.screen, stop_col, self.btn_stop_rect, 1, border_radius=8)

        scx = self.btn_stop_rect.centerx
        scy = self.btn_stop_rect.centery
        pygame.draw.rect(self.screen, stop_col, (scx - 6, scy - 6, 12, 12), border_radius=2)

    def draw_conversation_deck(self, rect):
        """Draws Right Column: Full Height Conversation Deck with Clear/Copy actions and Input Capsule."""
        pygame.draw.rect(self.screen, Palette.CARD_BG, rect, border_radius=10)
        pygame.draw.rect(self.screen, Palette.CARD_BORDER, rect, 1, border_radius=10)

        m_pos = pygame.mouse.get_pos()

        # Header: Title & Action Capsules
        c_title = self.font_card_title.render("Conversation", True, Palette.WHITE)
        self.screen.blit(c_title, (rect.x + 14, rect.y + 10))

        # [ 🗑 Clear ] Button
        cl_hover = self.conv_clear_rect.collidepoint(m_pos)
        pygame.draw.rect(self.screen, (24, 34, 46) if cl_hover else (16, 24, 34), self.conv_clear_rect, border_radius=11)
        pygame.draw.rect(self.screen, Palette.CYAN if cl_hover else Palette.CARD_BORDER, self.conv_clear_rect, 1, border_radius=11)
        cl_surf = self.font_stat_lbl.render("🗑 Clear", True, Palette.WHITE if cl_hover else Palette.WHITE_MUTED)
        self.screen.blit(cl_surf, (self.conv_clear_rect.centerx - cl_surf.get_width() // 2, self.conv_clear_rect.centery - cl_surf.get_height() // 2))

        # [ 📋 Extract Conversation ] Button
        ex_hover = self.conv_extract_rect.collidepoint(m_pos)
        pygame.draw.rect(self.screen, (24, 34, 46) if ex_hover else (16, 24, 34), self.conv_extract_rect, border_radius=11)
        pygame.draw.rect(self.screen, Palette.CYAN if ex_hover else Palette.CARD_BORDER, self.conv_extract_rect, 1, border_radius=11)
        ex_surf = self.font_stat_lbl.render("📋 Extract", True, Palette.WHITE if ex_hover else Palette.WHITE_MUTED)
        self.screen.blit(ex_surf, (self.conv_extract_rect.centerx - ex_surf.get_width() // 2, self.conv_extract_rect.centery - ex_surf.get_height() // 2))

        # Chat Stream Messages
        inner_rect = self.chat_card_rect
        self.screen.set_clip(inner_rect)

        font_to_use = self.font_text
        line_height = 18
        max_text_w = inner_rect.width - 24
        msg_gap = 10

        total_content_h = 0
        layout_cache = []

        for msg in self.messages:
            sender = msg["sender"]
            text = msg["text"]
            t_str = msg.get("time", "")
            lines = self.wrap_text(text, max_text_w, font_to_use)
            msg_h = 16 + len(lines) * line_height
            layout_cache.append((sender, lines, t_str, total_content_h, msg_h))
            total_content_h += msg_h + msg_gap

        self.max_scroll = max(0, total_content_h - inner_rect.height)
        self.scroll_y = max(0, min(self.scroll_y, self.max_scroll))

        for sender, lines, t_str, top_offset, msg_h in layout_cache:
            draw_y = inner_rect.y + top_offset - self.scroll_y
            if draw_y + msg_h < inner_rect.y or draw_y > inner_rect.bottom:
                continue

            is_user = (sender in ["DEX", "YOU"])
            bubble_bg = Palette.MSG_USER_BG if is_user else Palette.MSG_AI_BG
            bubble_border = Palette.MSG_USER_BORDER if is_user else Palette.MSG_AI_BORDER

            bubble_rect = pygame.Rect(inner_rect.x + 2, draw_y, inner_rect.width - 4, msg_h)
            pygame.draw.rect(self.screen, bubble_bg, bubble_rect, border_radius=8)
            pygame.draw.rect(self.screen, bubble_border, bubble_rect, 1, border_radius=8)

            accent_col = Palette.CYAN if is_user else Palette.GREEN
            pygame.draw.rect(self.screen, accent_col, (bubble_rect.x + 3, bubble_rect.y + 6, 2, bubble_rect.height - 12), border_radius=1)

            time_x = bubble_rect.right - 10
            if t_str:
                tm_surf = self.font_stat_lbl.render(t_str, True, Palette.WHITE_DIM)
                self.screen.blit(tm_surf, (time_x - tm_surf.get_width(), draw_y + 4))

            line_y = draw_y + 6
            for l in lines:
                text_col = Palette.WHITE if is_user else Palette.WHITE_MUTED
                l_surf = font_to_use.render(l, True, text_col)
                self.screen.blit(l_surf, (inner_rect.x + 12, line_y))
                line_y += line_height

        self.screen.set_clip(None)

        # Scrollbar
        if self.max_scroll > 0:
            sb_x = rect.right - 6
            sb_y = inner_rect.y
            sb_h = inner_rect.height
            thumb_h = max(20, int(sb_h * (inner_rect.height / max(total_content_h, 1))))
            thumb_y = sb_y + int((sb_h - thumb_h) * (self.scroll_y / max(self.max_scroll, 1)))
            pygame.draw.rect(self.screen, (16, 24, 34), (sb_x, sb_y, 3, sb_h), border_radius=1)
            pygame.draw.rect(self.screen, Palette.CYAN, (sb_x, thumb_y, 3, thumb_h), border_radius=1)

        # Bottom Input Capsule
        in_color = Palette.INPUT_FOCUSED if self.input_focused else Palette.INPUT_BORDER
        pygame.draw.rect(self.screen, Palette.INPUT_BG, self.input_rect, border_radius=8)
        pygame.draw.rect(self.screen, in_color, self.input_rect, 1, border_radius=8)

        input_text_area = pygame.Rect(self.input_rect.x + 12, self.input_rect.y + 10, self.input_rect.width - 50, 20)
        if self.active_input_text:
            in_surf = self.font_input.render(self.active_input_text, True, Palette.WHITE)
            clip_w = input_text_area.width
            if in_surf.get_width() > clip_w:
                sub_rect = pygame.Rect(in_surf.get_width() - clip_w, 0, clip_w, in_surf.get_height())
                in_surf = in_surf.subsurface(sub_rect)
            self.screen.blit(in_surf, (input_text_area.x, input_text_area.y))
        else:
            ph_surf = self.font_input.render("Type a message...", True, Palette.WHITE_DIM)
            self.screen.blit(ph_surf, (input_text_area.x, input_text_area.y))

        if self.input_focused and int(time.time() * 2) % 2 == 0:
            cur_x = input_text_area.x + (self.font_input.size(self.active_input_text)[0] if self.active_input_text else 0)
            cur_x = min(cur_x, input_text_area.right - 2)
            pygame.draw.line(self.screen, Palette.CYAN, (cur_x, self.input_rect.y + 8), (cur_x, self.input_rect.bottom - 8), 2)

        send_hover = self.send_btn_rect.collidepoint(m_pos)
        has_text = bool(self.active_input_text.strip())
        s_bg = Palette.SEND_BTN_HOVER if (send_hover and has_text) else (Palette.SEND_BTN if has_text else (20, 31, 45))
        pygame.draw.rect(self.screen, s_bg, self.send_btn_rect, border_radius=6)

        scx = self.send_btn_rect.centerx
        scy = self.send_btn_rect.centery
        arr_col = (7, 11, 16) if has_text else Palette.WHITE_DIM
        p1 = (scx - 5, scy - 6)
        p2 = (scx + 6, scy)
        p3 = (scx - 5, scy + 6)
        p4 = (scx - 2, scy)
        pygame.draw.polygon(self.screen, arr_col, [p1, p2, p3, p4])

    def draw_compact_mode(self):
        """Draws the compact floating widget view with sleek minimal slate styling."""
        self.draw_compact_hud_card()
        self.draw_chat_stream()
        self.draw_controls()
        self.draw_input_bar()

    def draw_compact_hud_card(self):
        """Draws top mini holographic Arc Reactor card in compact widget mode."""
        card = self.hud_card_rect
        self.draw_hud_frame(card, "▲ ARC CORE // COMPACT", accent=Palette.CYAN)

        is_spk = (self.state == "SPEAKING")
        is_rec = (self.state == "LISTENING" or self.is_recording)
        is_muted = not self.output_voice_enabled

        _, _, badge_label, badge_color = self.emotion_engine.get_emotion(
            self.state, is_rec, is_spk, is_muted
        )

        # Mini Arc Reactor on left
        mini_cx = card.x + 46
        mini_cy = card.y + 54
        mini_r = 32
        self.draw_arc_reactor(mini_cx, mini_cy, mini_r, is_rec=is_rec, is_spk=is_spk)

        # Concentric pulsing core iris
        core_color = Palette.RED if is_rec else (Palette.GREEN if is_spk else Palette.CYAN)
        pulse_r = int(10 + math.sin(self.anim_t * 5.0) * 2.0)
        pygame.draw.circle(self.screen, core_color, (mini_cx, mini_cy), pulse_r, 1)
        pygame.draw.circle(self.screen, (240, 255, 255), (mini_cx, mini_cy), 4)

        # Cardinal crosshair ticks
        pygame.draw.line(self.screen, core_color, (mini_cx - 16, mini_cy), (mini_cx + 16, mini_cy), 1)
        pygame.draw.line(self.screen, core_color, (mini_cx, mini_cy - 16), (mini_cx, mini_cy + 16), 1)

        # Right side content
        info_x = card.x + 92

        # Headline
        head_surf = self.font_title.render("DEXORTO AI // HUD", True, Palette.WHITE)
        self.screen.blit(head_surf, (info_x, card.y + 26))

        # Status Pill Badge
        badge_surf = self.font_badge.render(f"● {badge_label}", True, badge_color)
        bw = badge_surf.get_width() + 12
        pill_rect = pygame.Rect(info_x, card.y + 46, bw, 18)
        bg_tint = Palette.RED_DARK if badge_color == Palette.RED else (
            Palette.GREEN_DARK if badge_color == Palette.GREEN else (12, 18, 26)
        )
        pygame.draw.rect(self.screen, bg_tint, pill_rect, border_radius=9)
        pygame.draw.rect(self.screen, badge_color, pill_rect, 1, border_radius=9)
        self.screen.blit(badge_surf, (info_x + 6, card.y + 48))

        # Hindi mode indicator tag
        if getattr(self, "understand_hindi", True):
            h_surf = self.font_badge.render("HINDI: ON", True, Palette.CYAN)
            self.screen.blit(h_surf, (pill_rect.right + 8, card.y + 48))

        # Mini 16-band audio equalizer
        self.draw_acoustic_radar(info_x, card.y + 70, card.width - 100, 18, is_rec=is_rec, is_spk=is_spk)

        # Draw compact quick utilities bar
        mouse_pos = pygame.mouse.get_pos()
        for btn in getattr(self, "compact_tool_btns", []):
            r = btn["rect"]
            hover = r.collidepoint(mouse_pos)
            btn_bg = (20, 30, 44) if hover else (12, 16, 24)
            btn_border = Palette.CYAN if hover else (28, 38, 52)
            btn_txt_c = Palette.CYAN if hover else Palette.WHITE_MUTED
            pygame.draw.rect(self.screen, btn_bg, r, border_radius=4)
            pygame.draw.rect(self.screen, btn_border, r, 1, border_radius=4)
            b_surf = self.font_badge.render(btn["label"], True, btn_txt_c)
            self.screen.blit(b_surf, (r.centerx - b_surf.get_width() // 2, r.centery - b_surf.get_height() // 2))

    def draw_settings_overlay(self):
        """Draws interactive Settings & Feature Configuration overlay modal with app-style tabs."""
        # 1. Dark semi-transparent scrim backdrop
        scrim = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        scrim.fill((5, 7, 10, 220))
        self.screen.blit(scrim, (0, 0))

        # 2. Centered high-tech modal box
        m_w = min(520, self.width - 20)
        m_h = min(460, self.height - 20)
        modal_rect = pygame.Rect((self.width - m_w) // 2, (self.height - m_h) // 2, m_w, m_h)
        self.draw_hud_frame(modal_rect, "▲ SYSTEM FEATURE SETTINGS // CONFIG", accent=Palette.GOLD)

        # Modal Close button [ ✕ ] (Crisp Vector)
        self.settings_close_rect = pygame.Rect(modal_rect.right - 28, modal_rect.y + 5, 22, 22)
        m_pos = pygame.mouse.get_pos()
        close_hover = self.settings_close_rect.collidepoint(m_pos)
        pygame.draw.rect(self.screen, Palette.RED if close_hover else (25, 28, 36), self.settings_close_rect, border_radius=3)
        if close_hover:
            pygame.draw.rect(self.screen, (255, 120, 120), self.settings_close_rect, 1, border_radius=3)
        cx, cy = self.settings_close_rect.centerx, self.settings_close_rect.centery
        x_col = Palette.WHITE if close_hover else Palette.WHITE_MUTED
        pygame.draw.line(self.screen, x_col, (cx - 4, cy - 4), (cx + 4, cy + 4), 2)
        pygame.draw.line(self.screen, x_col, (cx - 4, cy + 4), (cx + 4, cy - 4), 2)

        # App-Style Tabs Bar: [ 🎙 AUDIO & VOICE ] [ ⚙ BEHAVIOR & AI ] [ 🖥 SYSTEM & UI ]
        tabs = [
            {"id": 0, "label": "🎙 AUDIO & VOICE"},
            {"id": 1, "label": "⚙ BEHAVIOR & AI"},
            {"id": 2, "label": "🖥 SYSTEM & TOOLS"}
        ]
        tab_w = (modal_rect.width - 24) // len(tabs)
        tab_y = modal_rect.y + 32
        self.settings_tab_rects = []
        for idx, tab_info in enumerate(tabs):
            tr = pygame.Rect(modal_rect.x + 12 + idx * tab_w, tab_y, tab_w - 4, 26)
            self.settings_tab_rects.append({"index": idx, "rect": tr})
            is_active = (self.settings_tab == idx)
            t_hover = tr.collidepoint(m_pos)
            t_bg = (24, 36, 52) if is_active else ((16, 22, 30) if t_hover else (10, 14, 20))
            t_border = Palette.CYAN if is_active else ((38, 48, 64) if t_hover else (22, 28, 38))
            t_txt_c = Palette.CYAN if is_active else (Palette.WHITE if t_hover else Palette.WHITE_MUTED)
            pygame.draw.rect(self.screen, t_bg, tr, border_radius=4)
            pygame.draw.rect(self.screen, t_border, tr, 1, border_radius=4)
            ts = self.font_badge.render(tab_info["label"], True, t_txt_c)
            self.screen.blit(ts, (tr.centerx - ts.get_width() // 2, tr.centery - ts.get_height() // 2))

        # Active persona & voice label lookup
        act_persona = PersonaManager.get_active_persona()
        p_name = act_persona.get("name", "JARVIS")
        p_desc = act_persona.get("description", "Articulate Stark AI companion")
        sens_mode = getattr(config, "MIC_SENSITIVITY_MODE", "balanced").capitalize()

        cur_voice = getattr(config, "TTS_VOICE", "en-US-AriaNeural")
        voice_short = "Female US (Aria)"
        for vopt in getattr(config, "VOICE_OPTIONS", []):
            if vopt["voice_key"] == cur_voice:
                voice_short = vopt["short_name"]
                break

        # Grouped Settings by Tab
        if self.settings_tab == 0:
            settings_defs = [
                {
                    "id": "persona_cycle",
                    "label": f"Persona: {p_name}",
                    "desc": f"{p_desc} (Built-in & Custom)",
                    "val": True,
                    "btn_label": "CYCLE",
                    "key_hint": "[P]"
                },
                {
                    "id": "voice_cycle",
                    "label": f"Voice: {voice_short}",
                    "desc": "Switch Female US, Male, Hindi, British JARVIS",
                    "val": True,
                    "btn_label": "SWITCH",
                    "key_hint": "[V]"
                },
                {
                    "id": "mic_sens",
                    "label": f"Mic Sensitivity: {sens_mode}",
                    "desc": "Calibrate vocal threshold & anti-bleed filter",
                    "val": True,
                    "btn_label": "TUNE",
                    "key_hint": "[S]"
                },
                {
                    "id": "voice_out",
                    "label": "Voice Audio Output (TTS)",
                    "desc": "Neural Edge-TTS voice replies enabled/muted",
                    "val": self.output_voice_enabled,
                    "key_hint": "[M]"
                },
            ]
        elif self.settings_tab == 1:
            settings_defs = [
                {
                    "id": "hindi",
                    "label": "Hindi & Hinglish Comprehension",
                    "desc": "Understands 'gaana bajao', 'kholo', 'band karo', etc.",
                    "val": self.understand_hindi,
                    "key_hint": "[H]"
                },
                {
                    "id": "hindi_tutor",
                    "label": "Interactive Hindi Tutor",
                    "desc": "Teaches conversational Hindi, phrases & pronunciation",
                    "val": getattr(config, "TEACH_HINDI", True),
                    "key_hint": "[T]"
                },
                {
                    "id": "barge_in",
                    "label": "Wake-Word Barge-In Interrupt",
                    "desc": "Interrupts speech instantly when saying 'Dexorto'",
                    "val": self.allow_barge_in,
                    "key_hint": ""
                },
                {
                    "id": "json_filter",
                    "label": "Auto JSON-to-Human Translation",
                    "desc": "Translates raw JSON tool outputs into natural words",
                    "val": self.auto_json_filter,
                    "key_hint": ""
                },
            ]
        else:
            settings_defs = [
                {
                    "id": "win_mode",
                    "label": f"Window Mode ({self.mode.upper()})",
                    "desc": "Switch between Fullscreen HUD and Floating Widget",
                    "val": (self.mode == "fullscreen"),
                    "key_hint": "[F11]"
                },
                {
                    "id": "prevent_dup",
                    "label": "Single-Instance App Guard",
                    "desc": "Focuses existing window instead of duplicating apps",
                    "val": self.prevent_duplicate_apps,
                    "key_hint": ""
                },
                {
                    "id": "reuse_tabs",
                    "label": "Browser Tab Reuse",
                    "desc": "Navigates active tab instead of opening new tabs",
                    "val": self.reuse_browser_tabs,
                    "key_hint": ""
                },
            ]

        self.settings_toggle_rects = []
        row_y = tab_y + 34
        row_h = 48
        btn_w = 78
        btn_h = 24

        for s in settings_defs:
            if row_y + row_h > modal_rect.bottom - 24:
                break

            # Row hover backdrop
            row_rect = pygame.Rect(modal_rect.x + 10, row_y, modal_rect.width - 20, row_h)
            is_hover = row_rect.collidepoint(m_pos)
            if is_hover:
                pygame.draw.rect(self.screen, (16, 24, 34), row_rect, border_radius=6)
            pygame.draw.line(self.screen, (24, 30, 42), (row_rect.x, row_rect.bottom - 1), (row_rect.right, row_rect.bottom - 1), 1)

            # Title
            t_text = f"{s['label']} {s['key_hint']}".strip()
            t_surf = self.font_text.render(t_text, True, Palette.WHITE if is_hover else Palette.WHITE_MUTED)
            self.screen.blit(t_surf, (row_rect.x + 10, row_y + 5))

            # Desc
            d_surf = self.font_sub.render(s["desc"], True, Palette.WHITE_DIM)
            self.screen.blit(d_surf, (row_rect.x + 10, row_y + 25))

            # Action / Toggle button
            t_btn_rect = pygame.Rect(row_rect.right - btn_w - 8, row_y + 12, btn_w, btn_h)
            self.settings_toggle_rects.append({"id": s["id"], "rect": t_btn_rect, "row_rect": row_rect})

            if "btn_label" in s:
                lbl_text = s["btn_label"]
                btn_bg = Palette.CYAN_DARK if is_hover else (18, 32, 42)
                border_c = Palette.CYAN
                lbl_col = Palette.CYAN
            else:
                is_on = s["val"]
                btn_bg = Palette.GREEN_DARK if is_on else (28, 16, 20)
                border_c = Palette.GREEN if is_on else (90, 36, 42)
                lbl_text = "ENABLED" if is_on else "DISABLED"
                if s["id"] == "win_mode":
                    lbl_text = "FULL" if is_on else "COMPACT"
                lbl_col = Palette.GREEN if is_on else Palette.RED

            pygame.draw.rect(self.screen, btn_bg, t_btn_rect, border_radius=12)
            pygame.draw.rect(self.screen, border_c, t_btn_rect, 1, border_radius=12)
            btn_lbl = self.font_badge.render(lbl_text, True, lbl_col)
            self.screen.blit(btn_lbl, (t_btn_rect.centerx - btn_lbl.get_width() // 2,
                                       t_btn_rect.centery - btn_lbl.get_height() // 2))

            row_y += row_h + 3

        # In Tab 2 (SYSTEM), draw Quick Utilities row
        if self.settings_tab == 2:
            quick_y = row_y + 8
            if quick_y + 44 <= modal_rect.bottom - 20:
                qlbl = self.font_sub.render("QUICK UTILITIES (DEX-BOT SUITE):", True, Palette.WHITE_MUTED)
                self.screen.blit(qlbl, (modal_rect.x + 12, quick_y))
                q_btns = [
                    {"id": "q_notes", "label": "📝 NOTES"},
                    {"id": "q_weather", "label": "🌤 WEATHER"},
                    {"id": "q_audit", "label": "⚡ RAM AUDIT"}
                ]
                qw = (modal_rect.width - 24 - 16) // 3
                for qidx, qb in enumerate(q_btns):
                    qrect = pygame.Rect(modal_rect.x + 12 + qidx * (qw + 8), quick_y + 18, qw, 26)
                    self.settings_toggle_rects.append({"id": qb["id"], "rect": qrect, "row_rect": qrect})
                    qhover = qrect.collidepoint(m_pos)
                    pygame.draw.rect(self.screen, (20, 30, 42) if qhover else (12, 16, 24), qrect, border_radius=4)
                    pygame.draw.rect(self.screen, Palette.CYAN if qhover else (28, 38, 52), qrect, 1, border_radius=4)
                    q_surf = self.font_badge.render(qb["label"], True, Palette.CYAN if qhover else Palette.WHITE_MUTED)
                    self.screen.blit(q_surf, (qrect.centerx - q_surf.get_width() // 2, qrect.centery - q_surf.get_height() // 2))

        # 4. Bottom hint bar
        hint_str = "ESC: Close  •  TAB / 1-3: Switch Tab  •  F11: Mode  •  V: Voice  •  H: Hindi"
        h_surf = self.font_sub.render(hint_str, True, Palette.GOLD)
        self.screen.blit(h_surf, (modal_rect.centerx - h_surf.get_width() // 2, modal_rect.bottom - 18))


    def draw_chat_stream(self):
        """Draws Section 02: Holographic Comms Matrix."""
        card = self.chat_card_rect
        if self.mode == "fullscreen":
            self.draw_hud_frame(card, "▲ SECTION 02 // HOLOGRAPHIC COMMS MATRIX", accent=Palette.GREEN)
            top_pad = 28
        else:
            self.draw_hud_frame(card, "▲ COMMS MATRIX", accent=Palette.GREEN)
            top_pad = 26

        inner_rect = pygame.Rect(card.x + 10, card.y + top_pad, card.width - 20, card.height - top_pad - 10)
        self.screen.set_clip(inner_rect)

        font_to_use = self.font_mono if self.mode == "fullscreen" else self.font_text
        line_height = 20 if self.mode == "fullscreen" else 18
        max_text_w = inner_rect.width - 16
        msg_gap = 12

        total_content_h = 0
        layout_cache = []

        for msg in self.messages:
            sender = msg["sender"]
            text = msg["text"]
            t_str = msg.get("time", "")
            color = msg.get("color", Palette.WHITE)
            lines = self.wrap_text(text, max_text_w, font_to_use)
            msg_h = 18 + len(lines) * line_height
            layout_cache.append((sender, lines, t_str, total_content_h, msg_h, color))
            total_content_h += msg_h + msg_gap

        self.max_scroll = max(0, total_content_h - inner_rect.height)
        self.scroll_y = max(0, min(self.scroll_y, self.max_scroll))

        for sender, lines, t_str, top_offset, msg_h, color in layout_cache:
            draw_y = inner_rect.y + top_offset - self.scroll_y
            if draw_y + msg_h < inner_rect.y or draw_y > inner_rect.bottom:
                continue

            is_user = (sender in ["DEX", "YOU"])
            is_jarvis = (sender == "DEXORTO")

            if is_user:
                badge_tag = "DEX"
                badge_color = Palette.CYAN
                bubble_bg = Palette.MSG_USER_BG
            elif is_jarvis:
                badge_tag = "DEXORTO"
                badge_color = Palette.GREEN
                bubble_bg = Palette.MSG_AI_BG
            else:
                badge_tag = sender
                badge_color = Palette.WHITE_DIM
                bubble_bg = Palette.MSG_SYS_BG

            # Subtle message bubble background
            bubble_rect = pygame.Rect(inner_rect.x + 2, draw_y - 2, inner_rect.width - 4, msg_h + 4)
            pygame.draw.rect(self.screen, bubble_bg, bubble_rect, border_radius=6)

            # Left accent bar (thin colored strip)
            accent_strip = pygame.Rect(inner_rect.x + 2, draw_y - 2, 3, msg_h + 4)
            pygame.draw.rect(self.screen, badge_color, accent_strip, border_radius=1)

            # Sender badge pill
            b_surf = self.font_badge.render(badge_tag, True, badge_color)
            pill_w = b_surf.get_width() + 12
            pill_rect = pygame.Rect(inner_rect.x + 10, draw_y, pill_w, 16)
            pill_bg = (*badge_color[:3], 25) if len(badge_color) >= 3 else badge_color
            # Draw pill background (opaque approximation)
            dark_pill = tuple(max(0, c // 8) for c in badge_color[:3])
            pygame.draw.rect(self.screen, dark_pill, pill_rect, border_radius=8)
            pygame.draw.rect(self.screen, badge_color, pill_rect, 1, border_radius=8)
            self.screen.blit(b_surf, (inner_rect.x + 16, draw_y + 1))

            # Timestamp
            if t_str:
                time_surf = self.font_sub.render(t_str, True, Palette.WHITE_DIM)
                self.screen.blit(time_surf, (inner_rect.right - time_surf.get_width() - 12, draw_y + 2))

            # Full multi-line text (no truncation)
            line_y = draw_y + 20
            for l in lines:
                text_color = color if not is_user else Palette.WHITE_MUTED
                l_surf = font_to_use.render(l, True, text_color)
                self.screen.blit(l_surf, (inner_rect.x + 12, line_y))
                line_y += line_height

        self.screen.set_clip(None)

        # Sci-Fi Scrollbar
        if self.max_scroll > 0:
            sb_x = card.right - 6
            sb_y = card.y + top_pad
            sb_h = card.height - top_pad - 10
            thumb_h = max(20, int(sb_h * (inner_rect.height / max(total_content_h, 1))))
            thumb_y = sb_y + int((sb_h - thumb_h) * (self.scroll_y / max(self.max_scroll, 1)))
            pygame.draw.rect(self.screen, (24, 32, 45), (sb_x, sb_y, 3, sb_h), border_radius=1)
            pygame.draw.rect(self.screen, Palette.CYAN, (sb_x, thumb_y, 3, thumb_h), border_radius=1)

    def draw_controls(self):
        """Draws the voice buttons dock: Speaker toggle, Hero Mic, Stop/Replay."""
        mouse_pos = pygame.mouse.get_pos()

        # 1. Voice Toggle Button
        spk_hover = self.btn_spk_rect.collidepoint(mouse_pos)
        spk_active = self.output_voice_enabled
        spk_color = Palette.GREEN if spk_active else Palette.RED
        spk_bg = Palette.GREEN_DARK if (spk_active and spk_hover) else (
            Palette.RED_DARK if spk_hover else (12, 15, 22)
        )
        pygame.draw.rect(self.screen, spk_bg, self.btn_spk_rect, border_radius=4)
        pygame.draw.rect(self.screen, spk_color, self.btn_spk_rect, 1, border_radius=4)
        lbl_spk = "🔊 SPEAKER: ON" if spk_active else "🔇 SPEAKER: OFF"
        s_surf = self.font_btn.render(lbl_spk, True, spk_color)
        self.screen.blit(s_surf, (self.btn_spk_rect.centerx - s_surf.get_width() // 2,
                                  self.btn_spk_rect.centery - s_surf.get_height() // 2))

        # 2. Hero Mic Button
        mic_hover = self.btn_mic_rect.collidepoint(mouse_pos)
        is_rec = (self.state == "LISTENING" or self.is_recording)
        center_x = self.btn_mic_rect.centerx
        center_y = self.btn_mic_rect.centery
        mic_r = 20 if self.mode == "fullscreen" else 18

        # Animated Sonar Ring Pulse when recording
        if is_rec:
            self.pulse_phase += 0.08
            r1 = int(mic_r + 4 + (self.pulse_phase % 1.0) * 16)
            a1 = int(180 * (1.0 - (self.pulse_phase % 1.0)))
            pulse_surf = pygame.Surface((r1 * 2, r1 * 2), pygame.SRCALPHA)
            pygame.draw.circle(pulse_surf, (255, 59, 71, a1), (r1, r1), r1, 2)
            self.screen.blit(pulse_surf, (center_x - r1, center_y - r1))

        mic_color = Palette.RED if is_rec else (Palette.GREEN_HOVER if mic_hover else Palette.GREEN)
        mic_bg = Palette.RED_DARK if is_rec else (Palette.GREEN_DARK if mic_hover else (12, 15, 22))

        pygame.draw.circle(self.screen, mic_bg, (center_x, center_y), mic_r)
        pygame.draw.circle(self.screen, mic_color, (center_x, center_y), mic_r, 2)

        icon_color = Palette.WHITE if is_rec else mic_color
        pygame.draw.rect(self.screen, icon_color, (center_x - 3, center_y - 7, 6, 10), border_radius=3)
        pygame.draw.arc(self.screen, icon_color, (center_x - 6, center_y - 4, 12, 10), math.pi, 2 * math.pi, 2)
        pygame.draw.line(self.screen, icon_color, (center_x, center_y + 5), (center_x, center_y + 9), 2)
        pygame.draw.line(self.screen, icon_color, (center_x - 4, center_y + 9), (center_x + 4, center_y + 9), 2)

        # 3. Stop / Replay Button
        stop_hover = self.btn_stop_rect.collidepoint(mouse_pos)
        is_busy = (self.state in ["SPEAKING", "LISTENING", "THINKING"])
        stop_lbl = "⏹ ABORT" if is_busy else "↻ REPLAY"
        stop_color = Palette.RED if is_busy else Palette.WHITE_MUTED
        stop_bg = Palette.RED_DARK if (is_busy and stop_hover) else (12, 15, 22)

        pygame.draw.rect(self.screen, stop_bg, self.btn_stop_rect, border_radius=4)
        pygame.draw.rect(self.screen, stop_color, self.btn_stop_rect, 1, border_radius=4)
        st_surf = self.font_btn.render(stop_lbl, True, stop_color)
        self.screen.blit(st_surf, (self.btn_stop_rect.centerx - st_surf.get_width() // 2,
                                   self.btn_stop_rect.centery - st_surf.get_height() // 2))

    def draw_input_bar(self):
        """Draws command input capsule with blinking cursor and send button."""
        mouse_pos = pygame.mouse.get_pos()
        in_color = Palette.CYAN if self.input_focused else Palette.INPUT_BORDER

        # Send button area (right side of input)
        send_w = 36
        input_text_rect = pygame.Rect(self.input_rect.x, self.input_rect.y, self.input_rect.width - send_w - 4, self.input_rect.height)
        self.send_btn_rect = pygame.Rect(self.input_rect.right - send_w, self.input_rect.y, send_w, self.input_rect.height)

        # Input capsule background
        pygame.draw.rect(self.screen, Palette.INPUT_BG, self.input_rect, border_radius=6)
        pygame.draw.rect(self.screen, in_color, self.input_rect, 1, border_radius=6)

        # Send button
        has_text = bool(self.active_input_text.strip())
        send_hover = self.send_btn_rect.collidepoint(mouse_pos)
        if has_text:
            send_color = Palette.SEND_BTN_HOVER if send_hover else Palette.SEND_BTN
        else:
            send_color = Palette.WHITE_DIM

        # Draw send arrow icon (→)
        scx, scy = self.send_btn_rect.centerx, self.send_btn_rect.centery
        arr_len = 7
        pygame.draw.line(self.screen, send_color, (scx - arr_len, scy), (scx + arr_len - 2, scy), 2)
        pygame.draw.line(self.screen, send_color, (scx + arr_len - 5, scy - 4), (scx + arr_len - 1, scy), 2)
        pygame.draw.line(self.screen, send_color, (scx + arr_len - 5, scy + 4), (scx + arr_len - 1, scy), 2)

        # Separator line before send button
        pygame.draw.line(self.screen, in_color, (self.send_btn_rect.x, self.input_rect.y + 4), (self.send_btn_rect.x, self.input_rect.bottom - 4), 1)

        prefix = "» " if self.mode == "fullscreen" else "> "
        px_w = 0
        if prefix:
            px_surf = self.font_input.render(prefix, True, Palette.GREEN)
            px_w = px_surf.get_width()
            self.screen.blit(px_surf, (self.input_rect.x + 10, self.input_rect.y + 8))

        font_in = self.font_input if self.mode == "fullscreen" else self.font_text

        if self.active_input_text:
            in_surf = font_in.render(self.active_input_text, True, Palette.WHITE)
            clip_w = input_text_rect.width - px_w - 20
            if in_surf.get_width() > clip_w:
                sub_rect = pygame.Rect(in_surf.get_width() - clip_w, 0, clip_w, in_surf.get_height())
                in_surf = in_surf.subsurface(sub_rect)
            self.screen.blit(in_surf, (self.input_rect.x + 10 + px_w, self.input_rect.y + 7))
        else:
            ph_text = "Ask anything or type a command..."
            ph_surf = font_in.render(ph_text, True, Palette.WHITE_DIM)
            self.screen.blit(ph_surf, (self.input_rect.x + 10 + px_w, self.input_rect.y + 7))

        if self.input_focused and int(time.time() * 2) % 2 == 0:
            cx = self.input_rect.x + 10 + px_w + (
                font_in.size(self.active_input_text)[0] if self.active_input_text else 0
            )
            cx = min(cx, input_text_rect.right - 6)
            pygame.draw.line(self.screen, Palette.GREEN, (cx, self.input_rect.y + 6), (cx, self.input_rect.bottom - 7), 2)

    def draw_status_bar(self):
        """Draws a professional bottom status bar with key info (fullscreen only)."""
        if self.mode != "fullscreen":
            return

        bar_h = 22
        bar_rect = pygame.Rect(0, self.height - bar_h, self.width, bar_h)
        pygame.draw.rect(self.screen, Palette.STATUS_BG, bar_rect)
        pygame.draw.line(self.screen, Palette.STATUS_BORDER, (0, bar_rect.y), (self.width, bar_rect.y), 1)

        # Left section: Wake word status
        wake_on = self.wake_listener and self.wake_listener.active and not self.wake_listener.paused
        wake_dot_c = Palette.GREEN if wake_on else Palette.RED
        pygame.draw.circle(self.screen, wake_dot_c, (14, bar_rect.centery), 3)
        wake_lbl = f"Wake: {'Active' if wake_on else 'Off'}"
        w_surf = self.font_sub.render(wake_lbl, True, Palette.WHITE_MUTED)
        self.screen.blit(w_surf, (22, bar_rect.y + 4))

        # Second section: Current voice
        cur_voice = getattr(config, "TTS_VOICE", "en-US-AriaNeural")
        voice_short = "Aria"
        for vopt in getattr(config, "VOICE_OPTIONS", []):
            if vopt["voice_key"] == cur_voice:
                voice_short = vopt["short_name"].split("(")[1].rstrip(")") if "(" in vopt["short_name"] else vopt["short_name"]
                break
        v_surf = self.font_sub.render(f"Voice: {voice_short}", True, Palette.WHITE_DIM)
        self.screen.blit(v_surf, (140, bar_rect.y + 4))

        # Third section: Persona
        p_name = getattr(config, "ACTIVE_PERSONA", "jarvis").capitalize()
        p_surf = self.font_sub.render(f"Persona: {p_name}", True, Palette.WHITE_DIM)
        self.screen.blit(p_surf, (280, bar_rect.y + 4))

        # Center section: State
        state_text = self.state.capitalize()
        state_color = Palette.GREEN if self.state == "IDLE" else (Palette.RED if self.state == "LISTENING" else Palette.CYAN)
        s_surf = self.font_sub.render(state_text, True, state_color)
        self.screen.blit(s_surf, (self.width // 2 - s_surf.get_width() // 2, bar_rect.y + 4))

        # Right section: RAM + Time
        ram_str = f"RAM: {self.ram_pct}%" if hasattr(self, "ram_pct") else "RAM: --"
        r_surf = self.font_sub.render(ram_str, True, Palette.WHITE_DIM)
        self.screen.blit(r_surf, (self.width - 200, bar_rect.y + 4))

        time_str = time.strftime("%H:%M")
        t_surf = self.font_sub.render(time_str, True, Palette.WHITE_MUTED)
        self.screen.blit(t_surf, (self.width - 50, bar_rect.y + 4))

    # ── Main Run Loop ────────────────────────────────────
    def run(self):
        clock = pygame.time.Clock()
        running = True

        while running:
            self.anim_t += 0.05
            self._update_telemetry()

            # Check external exit / reload signal
            exit_sig = os.path.join(str(SCRIPT_DIR), ".exit_signal")
            if os.path.exists(exit_sig):
                try:
                    sig_mtime = os.path.getmtime(exit_sig)
                    if sig_mtime > getattr(self, "start_time", 0):
                        print("[Widget] Received external exit signal. Terminating cleanly.")
                        try:
                            os.remove(exit_sig)
                        except Exception:
                            pass
                        running = False
                        break
                    else:
                        try:
                            os.remove(exit_sig)
                        except Exception:
                            pass
                except Exception:
                    pass

            # Check external command / query injection
            cmd_file = os.path.join(str(SCRIPT_DIR), ".ext_cmd")
            if os.path.exists(cmd_file):
                try:
                    with open(cmd_file, "r", encoding="utf-8") as _cf:
                        _caction = _cf.read().strip()
                    try:
                        os.remove(cmd_file)
                    except Exception:
                        pass
                    if _caction:
                        self.submit_query(_caction)
                except Exception:
                    pass

            # Apply X11 window hints upon startup
            if not self.x11_configured and self.x11_retry_count < 30:
                self.x11_retry_count += 1
                if self.x11.configure_window(
                    self.caption, mode=self.mode, pos_x=self.current_win_x, pos_y=self.current_win_y
                ):
                    self.x11_configured = True

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        # 0. Intercept Clicks on Settings Modal (if open)
                        if self.settings_open:
                            if hasattr(self, "settings_close_rect") and self.settings_close_rect.collidepoint(event.pos):
                                self.settings_open = False
                                continue

                            # Tab switching in Settings Modal
                            handled_tab = False
                            for tr in getattr(self, "settings_tab_rects", []):
                                if tr["rect"].collidepoint(event.pos):
                                    self.settings_tab = tr["index"]
                                    handled_tab = True
                                    break
                            if handled_tab:
                                continue

                            handled_setting = False
                            for t in getattr(self, "settings_toggle_rects", []):
                                if t["rect"].collidepoint(event.pos) or t["row_rect"].collidepoint(event.pos):
                                    sid = t["id"]
                                    if sid == "hindi":
                                        self.understand_hindi = not self.understand_hindi
                                        setattr(config, "UNDERSTAND_HINDI", self.understand_hindi)
                                        self._persist_setting("understand_hindi", self.understand_hindi)
                                        status = "ENABLED" if self.understand_hindi else "DISABLED"
                                        self._append_message("SYSTEM", f"Hindi comprehension {status}.")
                                    elif sid == "barge_in":
                                        self.allow_barge_in = not self.allow_barge_in
                                        setattr(config, "ALLOW_BARGE_IN", self.allow_barge_in)
                                        self._persist_setting("allow_barge_in", self.allow_barge_in)
                                        status = "ENABLED" if self.allow_barge_in else "DISABLED"
                                        self._append_message("SYSTEM", f"Wake-word barge-in {status}.")
                                    elif sid == "json_filter":
                                        self.auto_json_filter = not self.auto_json_filter
                                        setattr(config, "AUTO_JSON_FILTER", self.auto_json_filter)
                                        self._persist_setting("auto_json_filter", self.auto_json_filter)
                                        status = "ENABLED" if self.auto_json_filter else "DISABLED"
                                        self._append_message("SYSTEM", f"Auto JSON filter {status}.")
                                    elif sid == "prevent_dup":
                                        self.prevent_duplicate_apps = not self.prevent_duplicate_apps
                                        setattr(config, "PREVENT_DUPLICATE_APPS", self.prevent_duplicate_apps)
                                        self._persist_setting("prevent_duplicate_apps", self.prevent_duplicate_apps)
                                        status = "ENABLED" if self.prevent_duplicate_apps else "DISABLED"
                                        self._append_message("SYSTEM", f"Single-instance guard {status}.")
                                    elif sid == "reuse_tabs":
                                        self.reuse_browser_tabs = not self.reuse_browser_tabs
                                        setattr(config, "REUSE_BROWSER_TABS", self.reuse_browser_tabs)
                                        self._persist_setting("reuse_browser_tabs", self.reuse_browser_tabs)
                                        status = "ENABLED" if self.reuse_browser_tabs else "DISABLED"
                                        self._append_message("SYSTEM", f"Browser tab reuse {status}.")
                                    elif sid == "persona_cycle":
                                        self.cycle_persona("cycle")
                                    elif sid == "mic_sens":
                                        ok, mode, msg = set_mic_sensitivity("cycle")
                                        self._append_message("SYSTEM", msg)
                                    elif sid == "voice_cycle":
                                        self.cycle_voice_model("cycle")
                                    elif sid == "hindi_tutor":
                                        new_v = not getattr(config, "TEACH_HINDI", True)
                                        setattr(config, "TEACH_HINDI", new_v)
                                        self._persist_setting("teach_hindi", new_v)
                                        status = "ENABLED" if new_v else "DISABLED"
                                        self._append_message("SYSTEM", f"Interactive Hindi tutor {status}.")
                                    elif sid == "voice_out":
                                        self.toggle_output_voice()
                                        self._persist_setting("output_voice_enabled", self.output_voice_enabled)
                                    elif sid == "win_mode":
                                        self.toggle_window_mode()
                                    elif sid == "q_notes":
                                        self.settings_open = False
                                        self.submit_query("list notes")
                                    elif sid == "q_weather":
                                        self.settings_open = False
                                        self.submit_query("what is the weather")
                                    elif sid == "q_audit":
                                        self.settings_open = False
                                        self.submit_query("audit system")
                                    handled_setting = True
                                    break

                            if handled_setting:
                                continue

                            # Click outside modal closes settings
                            m_w = min(520, self.width - 20)
                            m_h = min(460, self.height - 20)
                            modal_rect = pygame.Rect((self.width - m_w) // 2, (self.height - m_h) // 2, m_w, m_h)
                            if not modal_rect.collidepoint(event.pos):
                                self.settings_open = False
                                continue

                        # Fullscreen Left Column Card Refresh & Action Clicks
                        if self.mode == "fullscreen":
                            if hasattr(self, "stats_refresh_rect") and self.stats_refresh_rect.collidepoint(event.pos):
                                self._update_telemetry()
                                gc.collect()
                                self._append_message("SYSTEM", "Hardware telemetry refreshed.")
                                continue
                            elif hasattr(self, "weather_refresh_rect") and self.weather_refresh_rect.collidepoint(event.pos):
                                self._fetch_weather_async()
                                self._append_message("SYSTEM", "Weather telemetry refreshing...")
                                continue
                            elif hasattr(self, "conv_clear_rect") and self.conv_clear_rect.collidepoint(event.pos):
                                self.messages = [{
                                    "sender": "DEXORTO",
                                    "text": "Conversation cleared. How can I assist you, Dex?",
                                    "time": time.strftime("%H:%M"),
                                    "color": Palette.CYAN
                                }]
                                self.scroll_y = 0
                                continue
                            elif hasattr(self, "conv_extract_rect") and self.conv_extract_rect.collidepoint(event.pos):
                                transcript = [f"[{m.get('time', '')}] {m.get('sender', '')}: {m.get('text', '')}" for m in self.messages]
                                ToolExecutor.copy_to_clipboard("\n".join(transcript))
                                self._append_message("SYSTEM", "Full conversation extracted & copied to clipboard.")
                                continue
                            elif hasattr(self, "btn_deck_rect") and self.btn_deck_rect.collidepoint(event.pos):
                                self.settings_open = not self.settings_open
                                continue

                        # 1. Tactical Protocol Buttons (Fullscreen Section 01)
                        if self.mode == "fullscreen":
                            handled_proto = False
                            for pbtn in self.protocol_btns:
                                if pbtn["rect"].collidepoint(event.pos):
                                    pid = pbtn["id"]
                                    handled_proto = True
                                    if pid == "tasks":
                                        self.submit_query("what is my task today")
                                    elif pid == "notes":
                                        self.submit_query("list notes")
                                    elif pid == "weather":
                                        self.submit_query("what is the weather")
                                    elif pid == "calc":
                                        self.active_input_text = "calculate "
                                        self.input_focused = True
                                    elif pid == "audit":
                                        self.submit_query("audit system")
                                    elif pid == "music":
                                        self.submit_query("play some music on spotify")
                                    elif pid == "insta":
                                        self.submit_query("open instagram")
                                    elif pid == "teach_hindi":
                                        self.submit_query("teach me hindi")
                                    elif pid == "terminal":
                                        ToolExecutor.execute_tool("open_app", {"app_name": "terminal"})
                                    elif pid == "settings":
                                        self.settings_open = not self.settings_open
                                    break
                            if handled_proto:
                                continue
                        else:
                            # Compact Mode Quick Utilities Bar
                            handled_ctool = False
                            for cbtn in getattr(self, "compact_tool_btns", []):
                                if cbtn["rect"].collidepoint(event.pos):
                                    cid = cbtn["id"]
                                    handled_ctool = True
                                    if cid == "tasks":
                                        self.submit_query("what is my task today")
                                    elif cid == "notes":
                                        self.submit_query("list notes")
                                    elif cid == "weather":
                                        self.submit_query("what is the weather")
                                    elif cid == "calc":
                                        self.active_input_text = "calculate "
                                        self.input_focused = True
                                    elif cid == "audit":
                                        self.submit_query("audit system")
                                    elif cid == "music":
                                        self.submit_query("play some music on spotify")
                                    break
                            if handled_ctool:
                                continue

                        # 2. Window Header Buttons
                        if self.close_btn_rect.collidepoint(event.pos):
                            running = False

                        elif self.mode_btn_rect.collidepoint(event.pos):
                            self.toggle_window_mode()

                        elif self.minimize_btn_rect.collidepoint(event.pos):
                            self.minimize_window()

                        elif self.settings_btn_rect.collidepoint(event.pos):
                            self.settings_open = not self.settings_open

                        # 3. Hero Mic Button
                        elif self.btn_mic_rect.collidepoint(event.pos):
                            self.toggle_input_voice()

                        # 4. Speaker Output Toggle Button
                        elif self.btn_spk_rect.collidepoint(event.pos):
                            self.toggle_output_voice()

                        # 5. Stop / Replay Button
                        elif self.btn_stop_rect.collidepoint(event.pos):
                            if self.state in ["SPEAKING", "LISTENING", "THINKING"]:
                                self.stop_actions()
                            else:
                                self.replay_last()

                        # 6. Text Input Capsule & Send Button
                        elif hasattr(self, "send_btn_rect") and self.send_btn_rect.collidepoint(event.pos):
                            if self.active_input_text.strip():
                                self.submit_query(self.active_input_text)
                        elif self.input_rect.collidepoint(event.pos):
                            self.input_focused = True

                        # 7. Compact Mode Header Dragging
                        elif self.mode == "compact" and self.header_rect.collidepoint(event.pos):
                            self.is_dragging = True
                            self.drag_offset_x = event.pos[0]
                            self.drag_offset_y = event.pos[1]
                        else:
                            self.input_focused = False

                    # Mouse Wheel Scrolling
                    elif event.button == 4:
                        self.scroll_y = max(0, self.scroll_y - 36)
                    elif event.button == 5:
                        self.scroll_y = min(self.max_scroll, self.scroll_y + 36)

                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1:
                        self.is_dragging = False

                elif event.type == pygame.MOUSEMOTION:
                    if self.is_dragging and self.mode == "compact":
                        ptr = self.x11.get_pointer_pos()
                        if ptr:
                            new_x = ptr[0] - self.drag_offset_x
                            new_y = ptr[1] - self.drag_offset_y
                            self.current_win_x = new_x
                            self.current_win_y = new_y
                            self.x11.move_window(new_x, new_y)

                elif event.type == pygame.MOUSEWHEEL:
                    self.scroll_y = max(0, min(self.max_scroll, self.scroll_y - event.y * 30))

                elif event.type == pygame.KEYDOWN:
                    # Settings toggle shortcut [F2]
                    if event.key == pygame.K_F2:
                        self.settings_open = not self.settings_open
                        continue

                    # If settings modal is open, intercept keys
                    if self.settings_open:
                        if event.key == pygame.K_ESCAPE:
                            self.settings_open = False
                            continue
                        elif event.key in [pygame.K_1, pygame.K_KP1]:
                            self.settings_tab = 0
                            continue
                        elif event.key in [pygame.K_2, pygame.K_KP2]:
                            self.settings_tab = 1
                            continue
                        elif event.key in [pygame.K_3, pygame.K_KP3]:
                            self.settings_tab = 2
                            continue
                        elif event.key == pygame.K_TAB:
                            self.settings_tab = (self.settings_tab + 1) % 3
                            continue
                        elif event.key == pygame.K_v:
                            self.cycle_voice_model("cycle")
                            continue
                        elif event.key == pygame.K_h:
                            self.understand_hindi = not self.understand_hindi
                            setattr(config, "UNDERSTAND_HINDI", self.understand_hindi)
                            status = "ENABLED" if self.understand_hindi else "DISABLED"
                            self._append_message("SYSTEM", f"Hindi comprehension {status}.")
                            continue
                        elif event.key == pygame.K_t:
                            new_v = not getattr(config, "TEACH_HINDI", True)
                            setattr(config, "TEACH_HINDI", new_v)
                            status = "ENABLED" if new_v else "DISABLED"
                            self._append_message("SYSTEM", f"Interactive Hindi tutor {status}.")
                            continue
                        elif event.key == pygame.K_p:
                            self.cycle_persona()
                            continue
                        elif event.key == pygame.K_s:
                            ok, mode, msg = set_mic_sensitivity("cycle")
                            self._append_message("SYSTEM", msg)
                            continue
                        elif event.key == pygame.K_m:
                            self.toggle_output_voice()
                            continue
                        elif event.key == pygame.K_F11:
                            self.toggle_window_mode()
                            continue

                    if self.input_focused:
                        if event.key == pygame.K_RETURN:
                            if self.active_input_text.strip():
                                self.submit_query(self.active_input_text)
                        elif event.key == pygame.K_BACKSPACE:
                            if event.mod & pygame.KMOD_CTRL:
                                # Ctrl+Backspace: delete preceding word
                                if re.search(r'\S', self.active_input_text):
                                    self.active_input_text = re.sub(r'\s*\S+\s*$', '', self.active_input_text)
                                else:
                                    self.active_input_text = ""
                            else:
                                self.active_input_text = self.active_input_text[:-1]
                        elif event.key == pygame.K_u and (event.mod & pygame.KMOD_CTRL):
                            # Ctrl+U: clear active message box
                            self.active_input_text = ""
                        elif event.key == pygame.K_v and (event.mod & pygame.KMOD_CTRL):
                            # Ctrl+V: paste from clipboard
                            try:
                                import pygame.scrap as scrap
                                if not scrap.get_init():
                                    scrap.init()
                                cb = scrap.get(pygame.SCRAP_TEXT)
                                if cb:
                                    clean_paste = cb.decode('utf-8', 'ignore').rstrip('\x00').strip('\r\n')
                                    self.active_input_text += clean_paste
                            except Exception:
                                pass
                        elif event.key == pygame.K_ESCAPE:
                            self.input_focused = False
                        elif event.key == pygame.K_F11:
                            self.toggle_window_mode()
                        else:
                            if event.unicode and len(event.unicode) == 1 and ord(event.unicode) >= 32:
                                self.active_input_text += event.unicode
                    else:
                        # Global Hotkeys
                        if event.key == pygame.K_c and (event.mod & pygame.KMOD_CTRL):
                            if getattr(self, "last_clean_response", ""):
                                ToolExecutor.copy_to_clipboard(self.last_clean_response)
                                self._append_message("SYSTEM", "Last response copied to clipboard.")
                        elif event.key == pygame.K_F11:
                            self.toggle_window_mode()
                        elif event.key == pygame.K_SPACE:
                            self.toggle_input_voice()
                        elif event.key == pygame.K_p:
                            self.cycle_persona()
                        elif event.key == pygame.K_s:
                            ok, mode, msg = set_mic_sensitivity("cycle")
                            self._append_message("SYSTEM", msg)
                        elif event.key == pygame.K_v:
                            self.cycle_voice_model("cycle")
                        elif event.key == pygame.K_t:
                            new_v = not getattr(config, "TEACH_HINDI", True)
                            setattr(config, "TEACH_HINDI", new_v)
                            status = "ENABLED" if new_v else "DISABLED"
                            self._append_message("SYSTEM", f"Interactive Hindi tutor {status}.")
                        elif event.key == pygame.K_h:
                            self.understand_hindi = not self.understand_hindi
                            setattr(config, "UNDERSTAND_HINDI", self.understand_hindi)
                            status = "ENABLED" if self.understand_hindi else "DISABLED"
                            self._append_message("SYSTEM", f"Hindi comprehension {status}.")
                        elif event.key == pygame.K_m:
                            self.toggle_output_voice()
                        elif event.key == pygame.K_ESCAPE:
                            self.stop_actions()
                        elif event.key == pygame.K_q:
                            running = False
                        elif event.key == pygame.K_TAB:
                            self.input_focused = True

            # ── Render UI According to Mode (Minimal Gray JARVIS HUD) ──
            self.screen.fill(Palette.BG)
            self.draw_header()

            if self.mode == "fullscreen":
                # Left Column: 4 System Cards
                self.draw_stats_card(self.card_stats_rect)
                self.draw_weather_card(self.card_weather_rect)
                self.draw_deck_card(self.card_deck_rect)
                self.draw_uptime_card(self.card_uptime_rect)

                # Center Column: Hero Arc Reactor & Voice HUD
                self.draw_center_column(self.center_col_rect)

                # Right Column: Full Height Conversation Deck
                self.draw_conversation_deck(self.right_col_rect)
            else:
                self.draw_compact_mode()

            self.draw_status_bar()

            # Render "Thinking..." indicator when processing
            if self.state == "THINKING":
                think_text = "Thinking" + "." * (int(self.anim_t * 3) % 4)
                think_surf = self.font_badge.render(think_text, True, Palette.CYAN)
                if self.mode == "fullscreen":
                    self.screen.blit(think_surf, (self.input_rect.x, self.input_rect.y - 18))
                else:
                    self.screen.blit(think_surf, (self.input_rect.x + 4, self.input_rect.y - 16))

            # Render Settings Overlay Modal on top if open
            if self.settings_open:
                self.draw_settings_overlay()

            pygame.display.flip()
            # Adaptive frame rate: 15 FPS when idle to reduce CPU & RAM consumption, 30 FPS when active
            fps = 15 if (self.state == "IDLE" and not self.input_focused and not self.settings_open) else 30
            clock.tick(fps)

        # Cleanup
        self.wake_listener.stop()
        self.stop_actions()
        self.ipc_client.close()
        pygame.quit()


if __name__ == "__main__":
    app = DexortoDualApp()
    app.run()
