"""
JARVIS - AI Voice Assistant
============================
Speech-to-Text  : Groq Whisper (free cloud)
LLM Brain       : Google Gemini Flash (free cloud)
Text-to-Speech  : Edge-TTS (free, no key needed)
Web Search      : Tavily (free, 1000/month)
"""

import os
import sys
from pathlib import Path

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

for _p in _extra_paths:
    if os.path.exists(_p) and _p in sys.path:
        sys.path.remove(_p)
    if os.path.exists(_p):
        sys.path.insert(0, _p)

import config
import json
import re
import asyncio
import tempfile
import subprocess
import threading
import time
import io
import wave
import struct

import speech_recognition as sr
from google import genai
from groq import Groq
import edge_tts
import pygame

try:
    from tavily import TavilyClient
    HAS_TAVILY = True
except ImportError:
    TavilyClient = None
    HAS_TAVILY = False

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

import config
import requests
from jarvis_ipc import JarvisIPCServer
from browser_controller import BrowserController
from assistant_tools import (
    is_specific_command,
    TaskManager,
    format_short_clean_response,
    parse_hindi_command_intent,
    filter_json_to_human_words,
    change_voice,
    HindiTutor,
    PersonaManager,
    set_mic_sensitivity,
    MemoryManager,
    get_effective_system_prompt,
    manage_memory
)

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


# ── Colors for terminal output ───────────────────────────
class C:
    CYAN    = "\033[96m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    RED     = "\033[91m"
    MAGENTA = "\033[95m"
    BOLD    = "\033[1m"
    RESET   = "\033[0m"


def banner():
    print(f"""{C.CYAN}{C.BOLD}
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
    {C.RESET}{C.GREEN}AI Voice Assistant for PC{C.RESET}
    {C.YELLOW}Say "{config.WAKE_WORD}" to activate | "exit/quit" to stop{C.RESET}
    """)


# ══════════════════════════════════════════════════════════
# Speech-to-Text (Groq Whisper - free cloud)
# ══════════════════════════════════════════════════════════
class SpeechToText:
    def __init__(self):
        self.groq_client = Groq(api_key=config.GROQ_API_KEY)
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = getattr(config, "ENERGY_THRESHOLD", 140)
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.dynamic_energy_adjustment_damping = 0.15
        self.recognizer.dynamic_energy_ratio = 1.5

        # Natural speaking pause thresholds (comfortable, realistic input)
        self.recognizer.pause_threshold = 0.75         # Natural pause threshold so user isn't cut off
        self.recognizer.non_speaking_duration = 0.3
        self.recognizer.phrase_threshold = 0.2
        self.mic = sr.Microphone()

        # Fast calibration for ambient noise
        print(f"{C.YELLOW}🎤 Calibrating microphone (fast)...{C.RESET}")
        try:
            with self.mic as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.3)
            configured_thresh = getattr(config, "ENERGY_THRESHOLD", 140)
            self.recognizer.energy_threshold = max(60, min(self.recognizer.energy_threshold, 250, configured_thresh))
            print(f"{C.GREEN}✓ Microphone calibrated (Energy threshold: {self.recognizer.energy_threshold}){C.RESET}")
        except Exception as e:
            print(f"{C.RED}Mic calibration note: {e}{C.RESET}")

        if HAS_WEBRTCVAD:
            try:
                self.vad = webrtcvad.Vad(getattr(config, "VAD_AGGRESSIVENESS", 2))
            except Exception:
                self.vad = None
        else:
            self.vad = None

    def listen(self) -> str | None:
        """Listen to microphone and return transcribed text with 100ms delay and responsive 3.5s timeout."""
        try:
            time.sleep(0.1)  # 100ms delay then speech recognition starts
            with self.mic as source:
                audio = self.recognizer.listen(
                    source,
                    timeout=getattr(config, "COMMAND_TIMEOUT", 4.0),
                    phrase_time_limit=7
                )

            # Fast silence check
            raw_bytes = audio.get_raw_data()
            min_rms = getattr(config, "MIN_SPEECH_RMS", 12)
            if is_audio_silent(raw_bytes, min_rms=min_rms):
                return None

            # 1. Ultra-fast Groq Whisper Turbo (~150ms transcription)
            if self.groq_client:
                try:
                    wav_data = audio.get_wav_data()
                    audio_file = io.BytesIO(wav_data)
                    audio_file.name = "audio.wav"
                    prompt_text = getattr(config, "WHISPER_PROMPT", "Dexorto AI assistant.")
                    lang = getattr(config, "LANGUAGE", "auto")
                    lang_param = {} if (not lang or lang == "auto") else {"language": lang}
                    transcription = self.groq_client.audio.transcriptions.create(
                        model="whisper-large-v3-turbo",
                        file=audio_file,
                        temperature=0.0,
                        prompt=prompt_text,
                        **lang_param
                    )
                    if transcription and transcription.text:
                        candidate = transcription.text.strip()
                        if not is_whisper_hallucination(candidate) and not self._is_self_voice_echo(candidate):
                            has_pending = bool(TaskManager.get_pending_app()) if hasattr(TaskManager, "get_pending_app") else False
                            is_spec, clean_cand = is_specific_command(candidate, has_pending_action=has_pending)
                            if is_spec:
                                return clean_cand
                except Exception as ge:
                    print(f"{C.YELLOW}Groq STT note: {ge}{C.RESET}")

            # 2. Resilient Google STT fallback
            try:
                candidate = self.recognizer.recognize_google(audio).strip()
                if not is_whisper_hallucination(candidate) and not self._is_self_voice_echo(candidate):
                    has_pending = bool(TaskManager.get_pending_app()) if hasattr(TaskManager, "get_pending_app") else False
                    is_spec, clean_cand = is_specific_command(candidate, has_pending_action=has_pending)
                    if is_spec:
                        return clean_cand
            except Exception:
                pass

            return None

        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return None
        except Exception as e:
            print(f"{C.RED}STT Error: {e}{C.RESET}")
            return None

    def _is_self_voice_echo(self, text: str) -> bool:
        """Prevents assistant from triggering on its own spoken audio output."""
        last_spk = getattr(self, "last_spoken_text", "")
        if not text or not last_spk:
            return False
        is_spk = getattr(self, "is_speaking", False)
        end_t = getattr(self, "last_speech_end_time", 0.0)
        if not is_spk and (time.time() - end_t > 2.5):
            return False
        c_text = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower()).strip()
        c_last = re.sub(r'[^a-zA-Z0-9\s]', '', last_spk.lower()).strip()
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

    def listen_for_wake_word(self) -> tuple[bool, str]:
        """Listen specifically for the strict wake word with turbo latency and inline command extraction."""
        # Acoustic cooldown check
        cooldown = getattr(config, "SELF_VOICE_MUTE_COOLDOWN", 0.65)
        if time.time() - getattr(self, "last_speech_end_time", 0.0) < cooldown:
            return False, ""

        if getattr(self, "is_speaking", False):
            if not getattr(config, "ALLOW_BARGE_IN", True):
                return False, ""
            min_rms = max(24, int(getattr(config, "MIN_SPEECH_RMS", 12) * 1.8))
        else:
            min_rms = getattr(config, "MIN_SPEECH_RMS", 12)

        try:
            with self.mic as source:
                audio = self.recognizer.listen(source, timeout=2.5, phrase_time_limit=3.5)

            # Fast silence check
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
                    lang = getattr(config, "LANGUAGE", "auto")
                    lang_param = {} if (not lang or lang == "auto") else {"language": lang}
                    transcription = self.groq_client.audio.transcriptions.create(
                        model="whisper-large-v3-turbo",
                        file=audio_file,
                        temperature=0.0,
                        prompt=prompt_text,
                        **lang_param
                    )
                    if transcription and transcription.text:
                        candidate = transcription.text.strip()
                        if not is_whisper_hallucination(candidate) and not self._is_self_voice_echo(candidate):
                            text = candidate
                except Exception:
                    pass

            if not text:
                try:
                    candidate = self.recognizer.recognize_google(audio).strip()
                    if not is_whisper_hallucination(candidate) and not self._is_self_voice_echo(candidate):
                        text = candidate
                except Exception:
                    return False, ""

            if not text:
                return False, ""

            # Check strict wake word and command
            detected, inline_cmd = self._parse_wake_and_command(text)
            return detected, inline_cmd

        except sr.WaitTimeoutError:
            return False, ""
        except Exception:
            return False, ""

    def _parse_wake_and_command(self, text: str) -> tuple[bool, str]:
        """Parses strict wake word and extracts any command spoken in the same breath."""
        if not text:
            return False, ""
        t = text.strip()

        # 1. Starts with wake word
        m_start = WAKE_PATTERN_START.search(t)
        if m_start:
            cmd = m_start.group(1).strip().lstrip(",.?! ").rstrip(",.?! ")
            return True, cmd

        # 2. Ends with wake word
        m_end = WAKE_PATTERN_END.search(t)
        if m_end:
            cmd = m_end.group(1).strip().lstrip(",.?! ").rstrip(",.?! ")
            return True, cmd

        # 3. Contains strict wake word
        m_strict = WAKE_PATTERN_STRICT.search(t)
        if m_strict:
            cmd = WAKE_PATTERN_STRICT.sub("", t).strip().lstrip(",.?! ").rstrip(",.?! ")
            return True, cmd

        return False, ""


# ══════════════════════════════════════════════════════════
# LLM Brain (Google Gemini Flash - free cloud)
# ══════════════════════════════════════════════════════════
class Brain:
    def __init__(self):
        # 1. Google Gemini
        self.gemini_client = None
        try:
            if config.GEMINI_API_KEY:
                self.gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
        except Exception as e:
            print(f"{C.RED}Gemini init error: {e}{C.RESET}")

        # 2. Groq Cloud
        self.groq_client = None
        try:
            if config.GROQ_API_KEY:
                self.groq_client = Groq(api_key=config.GROQ_API_KEY)
        except Exception as e:
            print(f"{C.RED}Groq init error: {e}{C.RESET}")

        # 3. OpenRouter (Free models)
        self.openrouter_key = getattr(config, "OPENROUTER_API_KEY", "")
        self.has_openrouter = bool(self.openrouter_key and self.openrouter_key != "YOUR_OPENROUTER_KEY_HERE")

        self.history_gemini = []
        self.history_groq = []
        providers = ["Gemini", "Groq"]
        if self.has_openrouter:
            providers.append("OpenRouter (Free)")
        print(f"{C.GREEN}✓ Brain ({' + '.join(providers)} Auto-Fallback) ready{C.RESET}")

    def _call_gemini(self, user_input: str) -> str | None:
        if not self.gemini_client:
            return None
        models_to_try = [config.GEMINI_MODEL] + getattr(config, "GEMINI_FALLBACKS", [])
        eff_prompt = get_effective_system_prompt()
        for m in models_to_try:
            try:
                self.history_gemini.append({"role": "user", "parts": [{"text": user_input}]})
                resp = self.gemini_client.models.generate_content(
                    model=m,
                    contents=self.history_gemini,
                    config=genai.types.GenerateContentConfig(
                        system_instruction=eff_prompt,
                        automatic_function_calling=genai.types.AutomaticFunctionCallingConfig(disable=True),
                        max_output_tokens=90
                    ),
                )
                reply = format_short_clean_response(resp.text.strip(), max_sentences=2)
                self.history_gemini.append({"role": "model", "parts": [{"text": reply}]})
                print(f"{C.GREEN}✓ Answered via Gemini ({m}){C.RESET}")
                return reply
            except Exception as e:
                print(f"{C.YELLOW}Gemini ({m}) notice: {e} - trying fallback...{C.RESET}")
                if self.history_gemini and self.history_gemini[-1].get("role") == "user":
                    self.history_gemini.pop()
        return None

    def _call_groq(self, user_input: str) -> str | None:
        if not self.groq_client:
            return None
        groq_models = [getattr(config, "GROQ_CHAT_MODEL", "openai/gpt-oss-20b")] + getattr(config, "GROQ_CHAT_FALLBACKS", ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"])
        eff_prompt = get_effective_system_prompt()
        for gm in groq_models:
            try:
                messages = [{"role": "system", "content": eff_prompt}]
                for msg in self.history_groq[-4:]:
                    messages.append(msg)
                messages.append({"role": "user", "content": user_input})

                resp = self.groq_client.chat.completions.create(
                    model=gm,
                    messages=messages,
                    max_tokens=90
                )
                reply = format_short_clean_response(resp.choices[0].message.content.strip(), max_sentences=2)
                self.history_groq.append({"role": "user", "content": user_input})
                self.history_groq.append({"role": "assistant", "content": reply})
                print(f"{C.GREEN}✓ Answered via Groq ({gm}){C.RESET}")
                return reply
            except Exception as ge:
                print(f"{C.YELLOW}Groq ({gm}) notice: {ge}{C.RESET}")
        return None

    def _call_openrouter(self, user_input: str) -> str | None:
        if not self.has_openrouter:
            return None
        openrouter_models = [getattr(config, "OPENROUTER_MODEL", "qwen/qwen3.8-27b:free")] + getattr(config, "OPENROUTER_FALLBACKS", [])
        eff_prompt = get_effective_system_prompt()
        for om in openrouter_models:
            try:
                headers = {
                    "Authorization": f"Bearer {self.openrouter_key}",
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "Dexorto JARVIS Voice Assistant",
                    "Content-Type": "application/json"
                }
                messages = [{"role": "system", "content": eff_prompt}]
                for msg in self.history_groq[-4:]:
                    messages.append(msg)
                messages.append({"role": "user", "content": user_input})

                payload = {
                    "model": om,
                    "messages": messages,
                    "max_tokens": 90,
                    "temperature": 0.7
                }
                resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=12)
                if resp.status_code == 200:
                    ans = format_short_clean_response(resp.json()["choices"][0]["message"]["content"].strip(), max_sentences=2)
                    self.history_groq.append({"role": "user", "content": user_input})
                    self.history_groq.append({"role": "assistant", "content": ans})
                    print(f"{C.GREEN}✓ Answered via OpenRouter ({om}){C.RESET}")
                    return ans
                else:
                    print(f"{C.YELLOW}OpenRouter ({om}) HTTP {resp.status_code}: {resp.text[:100]}{C.RESET}")
            except Exception as oe:
                print(f"{C.YELLOW}OpenRouter ({om}) notice: {oe}{C.RESET}")
        return None

    def think(self, user_input: str) -> str:
        """Send user input to LLM with 3-tier fallback (Gemini -> Groq -> OpenRouter)."""
        preferred = getattr(config, "PREFERRED_PROVIDER", "auto").lower()

        # Route according to preference
        if preferred == "openrouter":
            providers = [self._call_openrouter, self._call_gemini, self._call_groq]
        elif preferred == "groq":
            providers = [self._call_groq, self._call_gemini, self._call_openrouter]
        else:  # "auto" or "gemini"
            providers = [self._call_gemini, self._call_groq, self._call_openrouter]

        for provider_func in providers:
            result = provider_func(user_input)
            if result:
                return format_short_clean_response(result, max_sentences=2)

        return "I am having trouble connecting to AI services right now. Please check your internet connection or API keys."

    def reset(self):
        """Reset conversation history."""
        self.history_gemini = []
        self.history_groq = []


# ══════════════════════════════════════════════════════════
# Web Search (Tavily - free, 1000 searches/month)
# ══════════════════════════════════════════════════════════
class WebSearch:
    def __init__(self):
        self.enabled = False
        try:
            if config.TAVILY_API_KEY and config.TAVILY_API_KEY != "YOUR_TAVILY_API_KEY_HERE":
                self.client = TavilyClient(api_key=config.TAVILY_API_KEY)
                self.enabled = True
                print(f"{C.GREEN}✓ Web Search (Tavily) ready{C.RESET}")
            else:
                print(f"{C.YELLOW}⚠ Web Search disabled (no Tavily API key in config.py){C.RESET}")
        except Exception as e:
            print(f"{C.YELLOW}⚠ Web Search disabled: {e}{C.RESET}")

    def search(self, query: str) -> str | None:
        """Search the web and return a summary of results."""
        if not self.enabled:
            return None

        try:
            print(f"{C.MAGENTA}🔍 Searching: {query}{C.RESET}")
            results = self.client.search(
                query=query,
                search_depth="basic",
                max_results=5,
            )

            # Format results for the LLM
            formatted = []
            for i, result in enumerate(results.get("results", []), 1):
                title = result.get("title", "")
                content = result.get("content", "")
                url = result.get("url", "")
                formatted.append(f"{i}. {title}\n   {content}\n   Source: {url}")

            if formatted:
                return "\n\n".join(formatted)
            return "No results found."

        except Exception as e:
            print(f"{C.RED}Search Error: {e}{C.RESET}")
            return None

    @staticmethod
    def extract_search_query(response: str) -> str | None:
        """Extract search query from JARVIS response JSON command."""
        pattern = r'\{[^{}]*"action"\s*:\s*"search"[^{}]*"query"\s*:\s*"([^"]*)"[^{}]*\}'
        match = re.search(pattern, response, re.DOTALL)
        if match:
            return match.group(1)
        pattern2 = r'\{[^{}]*"query"\s*:\s*"([^"]*)"[^{}]*"action"\s*:\s*"search"[^{}]*\}'
        match2 = re.search(pattern2, response, re.DOTALL)
        if match2:
            return match2.group(1)
        return None


# ══════════════════════════════════════════════════════════
# Text-to-Speech (Edge-TTS - free, no key needed)
# ══════════════════════════════════════════════════════════
class TextToSpeech:
    def __init__(self):
        self.audio_available = False
        self.is_speaking = False
        self.last_spoken_text = ""
        self.last_speech_end_time = 0.0
        try:
            buf_size = getattr(config, "TTS_BUFFER_SIZE", 4096)
            if not pygame.mixer.get_init():
                pygame.mixer.pre_init(frequency=24000, size=-16, channels=2, buffer=buf_size)
                pygame.mixer.init(frequency=24000, size=-16, channels=2, buffer=buf_size)
            self.audio_available = True
        except pygame.error:
            print(f"{C.YELLOW}⚠ No audio device — TTS will be silent (text output only){C.RESET}")
        self.temp_dir = tempfile.mkdtemp()
        if self.audio_available:
            print(f"{C.GREEN}✓ Voice (Edge-TTS) ready [24kHz / Buffer {getattr(config, 'TTS_BUFFER_SIZE', 4096)}]{C.RESET}")
        else:
            print(f"{C.GREEN}✓ Voice (text-only mode){C.RESET}")

    def stop(self):
        """Immediately stop TTS audio playback."""
        self.is_speaking = False
        self.last_speech_end_time = time.time()
        if self.audio_available and pygame.mixer.get_init():
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

    def speak(self, text: str, interrupt_event: threading.Event = None) -> bool:
        """Convert text to speech and play it. Returns True if completed normally, False if interrupted."""
        # Clean text for TTS
        text = self._clean_for_speech(text)
        if not text:
            return True

        if not self.audio_available:
            return True

        try:
            self.is_speaking = True
            self.last_spoken_text = text.lower()
            return asyncio.run(self._generate_and_play(text, interrupt_event=interrupt_event))
        except Exception as e:
            print(f"{C.RED}TTS Error: {e}{C.RESET}")
            return True
        finally:
            self.is_speaking = False
            self.last_speech_end_time = time.time()

    async def _generate_and_play(self, text: str, interrupt_event: threading.Event = None) -> bool:
        """Generate audio with Edge-TTS and play with pygame."""
        output_file = os.path.join(self.temp_dir, "response.mp3")

        voice_to_use = getattr(config, "TTS_VOICE", "en-US-AriaNeural")
        if re.search(r'[\u0900-\u097F]', text):
            voice_to_use = getattr(config, "TTS_VOICE_HINDI", "hi-IN-MadhurNeural")

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice_to_use,
            rate=getattr(config, "TTS_RATE", "+0%"),
            pitch=getattr(config, "TTS_PITCH", "+0Hz")
        )
        await communicate.save(output_file)

        if not self.is_speaking or (interrupt_event and interrupt_event.is_set()):
            try:
                os.remove(output_file)
            except OSError:
                pass
            return False

        # Play audio
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            pygame.mixer.music.load(output_file)
            pygame.mixer.music.set_volume(1.0)
            pygame.mixer.music.play()

        interrupted = False
        # Wait for audio to finish, checking interruption flag
        while pygame.mixer.music.get_busy() and self.is_speaking:
            if interrupt_event and interrupt_event.is_set():
                interrupted = True
                self.stop()
                break
            time.sleep(0.03)

        pygame.mixer.music.unload()

        # Cleanup
        try:
            os.remove(output_file)
        except OSError:
            pass

        return not interrupted

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Remove markdown, code blocks, URLs, emojis, and JSON from text for natural speech."""
        if not text:
            return ""
        return format_short_clean_response(text, max_sentences=2)


# ══════════════════════════════════════════════════════════
# System Commands (open apps, URLs, etc.)
# ══════════════════════════════════════════════════════════
class CommandExecutor:
    """Execute system commands from JARVIS responses."""

    # Common app name → Linux command mappings
    APP_MAP = {
        "firefox": "firefox",
        "browser": "firefox",
        "chrome": "google-chrome",
        "files": "nautilus",
        "file manager": "nautilus",
        "terminal": "gnome-terminal",
        "calculator": "gnome-calculator",
        "settings": "gnome-control-center",
        "text editor": "gedit",
        "code": "code",
        "vscode": "code",
        "music": "rhythmbox",
        "videos": "totem",
        "gimp": "gimp",
        "libreoffice": "libreoffice",
    }

    @classmethod
    def extract_and_run(cls, response: str, user_input: str = "") -> bool:
        """Extract JSON commands from response or fallback to direct user input intent."""
        executed = False

        # 1. First check JSON in response (supporting multiline formatting)
        json_pattern = r'\{[^{}]*"action"[^{}]*\}'
        matches = re.findall(json_pattern, response, re.DOTALL)
        for match in matches:
            try:
                cmd = json.loads(match)
                action = cmd.get("action", "")
                target = cmd.get("target", "")

                # Check Browser Interactions (play_music, compose_message, type_text, browser)
                if BrowserController.execute_action(cmd):
                    executed = True
                elif action == "open_app":
                    cls._open_app(target)
                    executed = True
                elif action == "open_url":
                    cls._open_url(target)
                    executed = True
                elif action == "system":
                    cls._system_cmd(target)
                    executed = True
            except (json.JSONDecodeError, Exception):
                continue

        # 2. Check direct Browser Natural Language Intent (playing song, typing message in inbox)
        if not executed and user_input:
            if BrowserController.handle_natural_intent(user_input):
                return True

        # 3. If nothing executed from JSON, check direct user intent
        if not executed and user_input:
            low = user_input.lower().strip()

            # Direct URL or website requests
            url_match = re.search(r'\b(https?://\S+|www\.\S+|\w+\.(com|org|net|io|edu|gov))\b', low)
            if url_match:
                url = url_match.group(0)
                if not url.startswith("http"):
                    url = "https://" + url
                cls._open_url(url)
                return True

            if "youtube" in low:
                cls._open_url("https://youtube.com")
                return True
            elif "google" in low and ("search" in low or "open" in low):
                cls._open_url("https://google.com")
                return True
            elif "github" in low:
                cls._open_url("https://github.com")
                return True
            elif "reddit" in low:
                cls._open_url("https://reddit.com")
                return True

            # Direct App requests
            for app_key in cls.APP_MAP:
                if f"open {app_key}" in low or f"launch {app_key}" in low or f"start {app_key}" in low:
                    cls._open_app(app_key)
                    return True

        return executed

    @classmethod
    def _open_app(cls, app_name: str):
        """Open an application."""
        app_name_lower = app_name.lower()
        command = cls.APP_MAP.get(app_name_lower, app_name_lower)
        print(f"{C.MAGENTA}⚡ Opening: {command}{C.RESET}")
        try:
            subprocess.Popen(
                [command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            # Try with xdg-open as fallback
            try:
                subprocess.Popen(
                    ["xdg-open", command],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                print(f"{C.RED}Could not open: {app_name}{C.RESET}")

    @classmethod
    def _open_url(cls, url: str):
        """Open a URL in default browser."""
        print(f"{C.MAGENTA}🌐 Opening: {url}{C.RESET}")
        subprocess.Popen(
            ["xdg-open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @classmethod
    def _system_cmd(cls, command: str):
        """Execute system commands."""
        command = command.lower()
        if "shutdown" in command:
            print(f"{C.RED}⚠ Shutting down in 60s... (cancel: shutdown -c){C.RESET}")
            subprocess.run(["shutdown", "+1"])
        elif "restart" in command or "reboot" in command:
            print(f"{C.RED}⚠ Restarting...{C.RESET}")
            subprocess.run(["reboot"])
        elif "lock" in command:
            subprocess.run(["loginctl", "lock-session"])
        else:
            print(f"{C.YELLOW}Unknown system command: {command}{C.RESET}")


# ══════════════════════════════════════════════════════════
# Main JARVIS Loop
# ══════════════════════════════════════════════════════════
class Jarvis:
    def __init__(self):
        banner()
        print(f"{C.CYAN}Initializing systems...{C.RESET}\n")

        self.stt = SpeechToText()
        self.brain = Brain()
        self.tts = TextToSpeech()
        self.stt.tts_ref = self.tts
        self.search = WebSearch()
        self.running = True
        self.output_muted = False
        self.force_listen = False
        self.injected_query = None

        # Start IPC Server to communicate with the Desktop Widget
        self.ipc = JarvisIPCServer(on_command_callback=self._handle_ipc_cmd)

        print(f"\n{C.GREEN}{C.BOLD}✓ All systems online! (IPC Server active){C.RESET}")
        print(f"{C.CYAN}{'─' * 50}{C.RESET}\n")

    def _handle_ipc_cmd(self, msg: dict):
        """Handle command received from Desktop Widget."""
        cmd = msg.get("cmd") or msg.get("action")
        if cmd == "trigger_listen":
            print(f"{C.MAGENTA}[IPC] Widget requested listen!{C.RESET}")
            time.sleep(0.1)  # 100ms delay then speech recognition starts
            self.force_listen = True
        elif cmd == "toggle_mute":
            self.output_muted = not self.output_muted
            print(f"{C.YELLOW}[IPC] Output mute toggled: {self.output_muted}{C.RESET}")
            if self.output_muted:
                self.tts.stop()
            self.ipc.broadcast({"event": "mute_changed", "muted": self.output_muted})
        elif cmd == "stop":
            print(f"{C.RED}[IPC] Widget requested STOP!{C.RESET}")
            self.tts.stop()
        elif cmd == "replay":
            print(f"{C.CYAN}[IPC] Widget requested replay!{C.RESET}")
            if hasattr(self, "last_response") and self.last_response and not self.output_muted:
                self.tts.speak(self.last_response)
        elif cmd == "change_voice":
            target = msg.get("target", "cycle")
            ok, new_key, reply_msg = change_voice(target)
            if ok:
                self.tts.voice = new_key
                self.tts.speak(reply_msg)
                self.ipc.broadcast({"event": "voice_changed", "voice": new_key, "message": reply_msg})
        elif cmd == "change_persona":
            target = msg.get("target", "cycle")
            ok, p, reply_msg = PersonaManager.set_active_persona(target) if target != "cycle" else PersonaManager.cycle_persona()
            if ok:
                self.tts.voice = getattr(config, "TTS_VOICE", "en-US-AriaNeural")
                self.tts.speak(reply_msg)
                self.ipc.broadcast({"event": "persona_changed", "persona": p, "message": reply_msg})
        elif cmd == "set_sensitivity":
            mode = msg.get("mode", "cycle")
            ok, m, reply_msg = set_mic_sensitivity(mode)
            if ok:
                self.tts.speak(reply_msg)
                self.ipc.broadcast({"event": "sensitivity_changed", "mode": m, "message": reply_msg})
        elif cmd == "query":
            text = msg.get("text", "")
            if text:
                print(f"{C.CYAN}[IPC] Widget submitted query: {text}{C.RESET}")
                self.injected_query = text

    def run(self):
        """Main loop: listen → think → speak."""
        # Greeting
        greeting = "JARVIS online. All systems are operational. How can I help you?"
        print(f"{C.GREEN}🤖 JARVIS: {greeting}{C.RESET}")
        self.last_response = greeting
        self.ipc.broadcast({
            "event": "status", "state": "IDLE",
            "detail": "READY // SAY 'DEXORTO' OR TAP HERO MIC",
            "response": greeting
        })
        if not self.output_muted:
            self.tts.speak(greeting)

        while self.running:
            try:
                user_input = None

                # Check if query was injected via Widget
                if self.injected_query:
                    user_input = self.injected_query
                    self.injected_query = None
                else:
                    # Phase 1: Listen for wake word (unless force_listen requested)
                    inline_cmd = ""
                    if not self.force_listen:
                        print(f"\n{C.YELLOW}💤 Listening for \"{config.WAKE_WORD}\"...{C.RESET}", end="", flush=True)
                        self.ipc.broadcast({"event": "status", "state": "IDLE", "detail": f"LISTENING FOR '{config.WAKE_WORD.upper()}'..."})

                        wake_detected, inline_cmd = self.stt.listen_for_wake_word()
                        if not wake_detected:
                            continue

                    self.force_listen = False

                    # Wake word detected!
                    if inline_cmd:
                        print(f"\r{C.CYAN}✨ Wake word + inline command: '{inline_cmd}'{' ' * 10}{C.RESET}")
                        user_input = inline_cmd
                    else:
                        print(f"\r{C.CYAN}✨ Wake word detected!{' ' * 20}{C.RESET}")
                        self.ipc.broadcast({"event": "wake", "state": "LISTENING", "detail": "LISTENING..."})

                        # Phase 2: Listen for command
                        print(f"{C.YELLOW}🎤 Listening for command...{C.RESET}")
                        self.ipc.broadcast({"event": "status", "state": "LISTENING", "detail": "LISTENING..."})
                        user_input = self.stt.listen()

                    # Validate specific command
                    has_pending = bool(TaskManager.get_pending_app()) if hasattr(TaskManager, "get_pending_app") else False
                    is_spec, clean_input = is_specific_command(user_input or "", has_pending_action=has_pending)
                    if not is_spec:
                        # User didn't say anything specific: take NO action, speak NO idle text, return to IDLE
                        print(f"{C.YELLOW}[Voice] No specific command heard. Stopping until keyword called.{C.RESET}")
                        self.ipc.broadcast({"event": "status", "state": "IDLE", "detail": "READY"})
                        continue

                    user_input = clean_input

                print(f"{C.CYAN}👤 You: {user_input}{C.RESET}")
                self.ipc.broadcast({"event": "transcribed", "prompt": user_input})

                # Check for exit commands
                if any(word in user_input.lower() for word in ["exit", "quit", "stop", "goodbye", "shut down jarvis"]):
                    farewell = "Goodbye! Shutting down."
                    print(f"{C.GREEN}🤖 JARVIS: {farewell}{C.RESET}")
                    self.ipc.broadcast({"event": "status", "state": "IDLE", "detail": "SHUTTING DOWN...", "response": farewell})
                    if not self.output_muted:
                        self.tts.speak(farewell)
                    self.running = False
                    break

                # Check for reset command
                if "reset" in user_input.lower() and "conversation" in user_input.lower():
                    self.brain.reset()
                    msg = "Conversation history cleared. Fresh start!"
                    print(f"{C.GREEN}🤖 JARVIS: {msg}{C.RESET}")
                    self.ipc.broadcast({"event": "status", "state": "IDLE", "detail": "CONVERSATION CLEARED", "response": msg})
                    if not self.output_muted:
                        self.tts.speak(msg)
                    continue

                # Check for /rem slash command (permanent remember)
                m_rem = re.match(r'^[/\\]\s*rem(?:ember)?(?:\s+forever)?\b\s*[:,-]?\s*(.*)$', user_input, re.I)
                if m_rem:
                    content = m_rem.group(1).strip()
                    if content:
                        ok, item, msg = MemoryManager.add_permanent_memory(content, source="slash_rem")
                    else:
                        msg = "Please specify what you want me to remember forever, Dex."
                    clean_rem = format_short_clean_response(msg, max_sentences=2)
                    print(f"{C.GREEN}🤖 JARVIS: {clean_rem}{C.RESET}")
                    self.ipc.broadcast({
                        "event": "speaking",
                        "state": "SPEAKING",
                        "detail": "SPEAKING RESPONSE...",
                        "response": clean_rem
                    })
                    if not self.output_muted:
                        self.tts.speak(clean_rem)
                    self.ipc.broadcast({"event": "status", "state": "IDLE", "detail": "LISTENING FOR WAKE WORD..."})
                    continue

                # Native Hindi / Hinglish intent processing
                if getattr(config, "UNDERSTAND_HINDI", True):
                    hindi_handled, hindi_reply = parse_hindi_command_intent(user_input)
                    if hindi_handled:
                        clean_hindi = format_short_clean_response(hindi_reply, max_sentences=2)
                        print(f"{C.GREEN}🤖 JARVIS: {clean_hindi}{C.RESET}")
                        MemoryManager.record_session_interaction(user_input, clean_hindi)
                        self.ipc.broadcast({
                            "event": "speaking",
                            "state": "SPEAKING",
                            "detail": "SPEAKING RESPONSE...",
                            "response": clean_hindi
                        })
                        if not self.output_muted:
                            self.tts.speak(clean_hindi)
                        self.ipc.broadcast({"event": "status", "state": "IDLE", "detail": "LISTENING FOR WAKE WORD..."})
                        continue

                # Phase 3: Think (LLM)
                print(f"{C.MAGENTA}🧠 Thinking...{C.RESET}")
                self.ipc.broadcast({"event": "status", "state": "THINKING", "detail": "THINKING // GEMINI 3.6 FLASH..."})
                response = self.brain.think(user_input)

                # Phase 3.5: Check if JARVIS wants to search the web
                search_query = WebSearch.extract_search_query(response)
                if search_query and self.search.enabled:
                    self.ipc.broadcast({"event": "status", "state": "SEARCHING", "detail": f"SEARCHING TAVILY // '{search_query[:20]}'..."})
                    if not self.output_muted:
                        self.tts.speak("Let me look that up.")
                    search_results = self.search.search(search_query)
                    if search_results:
                        followup = (
                            f"Here are the web search results for '{search_query}':\n\n"
                            f"{search_results}\n\n"
                            f"Based on these results, answer the user's original question in 1 to 2 clean sentences without markdown or lists."
                        )
                        print(f"{C.MAGENTA}🧠 Analyzing results...{C.RESET}")
                        self.ipc.broadcast({"event": "status", "state": "THINKING", "detail": "SYNTHESIZING SEARCH RESULTS..."})
                        response = self.brain.think(followup)

                print(f"{C.GREEN}🤖 JARVIS: {response}{C.RESET}")
                self.last_response = response

                # Phase 4: Execute any commands found in response
                CommandExecutor.extract_and_run(response, user_input)

                # Phase 5: Speak the response
                clean_for_display = format_short_clean_response(response, max_sentences=2)
                MemoryManager.record_session_interaction(user_input, clean_for_display)
                self.ipc.broadcast({
                    "event": "speaking",
                    "state": "SPEAKING",
                    "detail": "SPEAKING RESPONSE...",
                    "response": clean_for_display
                })

                interrupted_by_wake = False
                inline_cmd_from_wake = ""

                if not self.output_muted:
                    interrupt_ev = threading.Event()
                    wake_res = [False, ""]

                    def _barge_in_listener():
                        while not interrupt_ev.is_set() and self.tts.is_speaking:
                            try:
                                detected, inline_cmd = self.stt.listen_for_wake_word()
                                if detected and not interrupt_ev.is_set() and self.tts.is_speaking:
                                    wake_res[0] = True
                                    wake_res[1] = inline_cmd
                                    interrupt_ev.set()
                                    self.tts.stop()
                                    break
                            except Exception:
                                time.sleep(0.1)

                    barge_in_thread = threading.Thread(target=_barge_in_listener, daemon=True)
                    barge_in_thread.start()

                    completed = self.tts.speak(response, interrupt_event=interrupt_ev)
                    interrupt_ev.set()

                    if wake_res[0] or not completed:
                        interrupted_by_wake = True
                        inline_cmd_from_wake = wake_res[1]

                if interrupted_by_wake:
                    print(f"\n{C.CYAN}⚡ Interrupted by wake word! Shifting immediately to wake word...{C.RESET}")
                    self.ipc.broadcast({"event": "wake", "state": "LISTENING", "detail": "LISTENING..."})
                    if inline_cmd_from_wake:
                        has_pending = bool(TaskManager.get_pending_app()) if hasattr(TaskManager, "get_pending_app") else False
                        is_spec, clean_input = is_specific_command(inline_cmd_from_wake, has_pending_action=has_pending)
                        if is_spec:
                            self.injected_query = clean_input
                    else:
                        self.force_listen = True
                else:
                    self.ipc.broadcast({
                        "event": "speech_done",
                        "state": "IDLE",
                        "detail": "READY // SAY 'DEXORTO' OR TAP HERO MIC"
                    })

            except KeyboardInterrupt:
                print(f"\n{C.YELLOW}Interrupted. Shutting down...{C.RESET}")
                self.running = False
                break
            except Exception as e:
                print(f"{C.RED}Error: {e}{C.RESET}")
                continue

        print(f"\n{C.CYAN}JARVIS offline.{C.RESET}")


# ══════════════════════════════════════════════════════════
# Text Mode (fallback if no microphone)
# ══════════════════════════════════════════════════════════
class JarvisTextMode:
    """Text-only mode — type instead of speaking."""

    def __init__(self):
        banner()
        print(f"{C.YELLOW}📝 Running in TEXT MODE (no microphone needed){C.RESET}\n")

        self.brain = Brain()
        self.tts = TextToSpeech()
        self.search = WebSearch()
        self.running = True
        self.output_muted = False
        self.injected_query = None

        # Start IPC server so widget can communicate even in text mode
        self.ipc = JarvisIPCServer(on_command_callback=self._handle_ipc_cmd)

        print(f"\n{C.GREEN}{C.BOLD}✓ All systems online! (Text Mode + IPC){C.RESET}")
        print(f"{C.CYAN}{'─' * 50}{C.RESET}\n")

    def _handle_ipc_cmd(self, msg: dict):
        cmd = msg.get("cmd") or msg.get("action")
        if cmd == "query":
            text = msg.get("text", "")
            if text:
                self.injected_query = text
        elif cmd == "toggle_mute":
            self.output_muted = not self.output_muted
            self.ipc.broadcast({"event": "mute_changed", "muted": self.output_muted})
        elif cmd == "change_voice":
            target = msg.get("target", "cycle")
            ok, new_key, reply_msg = change_voice(target)
            if ok:
                self.tts.voice = new_key
                self.tts.speak(reply_msg)
                self.ipc.broadcast({"event": "voice_changed", "voice": new_key, "message": reply_msg})
        elif cmd == "stop":
            self.tts.stop()

    def run(self):
        greeting = "JARVIS online in text mode. Type your commands."
        print(f"{C.GREEN}🤖 JARVIS: {greeting}{C.RESET}")
        self.ipc.broadcast({
            "event": "status", "state": "IDLE",
            "detail": "READY (TEXT MODE) // SEND QUERY",
            "response": greeting
        })
        self.tts.speak(greeting)

        while self.running:
            try:
                user_input = input(f"\n{C.CYAN}👤 You: {C.RESET}").strip()

                if not user_input:
                    continue

                if user_input.lower() in ["exit", "quit", "stop", "bye"]:
                    self.tts.speak("Goodbye!")
                    break

                print(f"{C.MAGENTA}🧠 Thinking...{C.RESET}")
                response = self.brain.think(user_input)

                # Check if JARVIS wants to search the web
                search_query = WebSearch.extract_search_query(response)
                if search_query and self.search.enabled:
                    search_results = self.search.search(search_query)
                    if search_results:
                        followup = (
                            f"Here are the web search results for '{search_query}':\n\n"
                            f"{search_results}\n\n"
                            f"Based on these results, answer the user's original question concisely."
                        )
                        print(f"{C.MAGENTA}🧠 Analyzing results...{C.RESET}")
                        response = self.brain.think(followup)

                print(f"{C.GREEN}🤖 JARVIS: {response}{C.RESET}")

                CommandExecutor.extract_and_run(response, user_input)
                self.tts.speak(response)

            except KeyboardInterrupt:
                print(f"\n{C.YELLOW}Goodbye!{C.RESET}")
                break
            except EOFError:
                break

        print(f"\n{C.CYAN}JARVIS offline.{C.RESET}")


# ══════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    if "--text" in sys.argv:
        jarvis = JarvisTextMode()
    else:
        try:
            jarvis = Jarvis()
        except Exception as e:
            print(f"{C.RED}Could not initialize microphone: {e}{C.RESET}")
            print(f"{C.YELLOW}Falling back to text mode...{C.RESET}\n")
            jarvis = JarvisTextMode()

    jarvis.run()
