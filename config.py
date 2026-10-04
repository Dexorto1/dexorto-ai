"""
JARVIS Configuration
====================
Add your free API keys here.

How to get keys (all are FREE):
1. Gemini API Key     → https://aistudio.google.com/apikey
2. Groq API Key       → https://console.groq.com/keys
3. OpenRouter API Key → https://openrouter.ai/keys  (Free :free models)
4. Tavily API Key     → https://app.tavily.com/home  (1000 free searches/month)
"""

import os
import sys
import json

# Ensure all packages are discovered cleanly without cross-version ABI contamination
_py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
_dir = os.path.dirname(os.path.abspath(__file__))
_extra_paths = [
    os.path.join(_dir, 'venv/lib/python3.12/site-packages'),
    os.path.join(_dir, 'venv/lib/python3.14/site-packages'),
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

# Try loading .env file if available
_env_file = os.path.join(_dir, '.env')
if os.path.exists(_env_file):
    try:
        with open(_env_file, 'r', encoding='utf-8') as _ef:
            for _line in _ef:
                _line = _line.strip()
                if _line and not _line.startswith('#') and '=' in _line:
                    _k, _v = _line.split('=', 1)
                    os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
    except Exception:
        pass


# ── API Keys ─────────────────────────────────────────────
# Set these in your .env file or environment variables (see .env.example)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "") 

# ── Voice Settings ───────────────────────────────────────
# Edge-TTS voice (see full list: https://speech.platform.bing.com/consumer/speech/synthesize/readaloud/voices/list?trustedclienttoken=6A5AA1D4EAFF4E9FB37E23D68491D6F4)
TTS_VOICE = "en-US-AriaNeural"       # Default voice: Aria (Female US English)
TTS_VOICE_FEMALE = "en-US-AriaNeural" # Primary female voice
TTS_VOICE_HINDI = "hi-IN-MadhurNeural"  # Pure native Hindi male
TTS_RATE = "+0%"                        # Clean natural speech speed (no phase-shift crackle)
TTS_PITCH = "+0Hz"                      # Clean natural pitch
TTS_BUFFER_SIZE = 4096                  # 4096-sample buffer to eliminate ALSA/PulseAudio underrun crackles

# Available Voices for Female / Male / Hindi / British switching
VOICE_OPTIONS = [
    {
        "id": "female_us",
        "name": "Aria (Female - US English)",
        "short_name": "Female US (Aria)",
        "voice_key": "en-US-AriaNeural",
        "gender": "female",
        "desc": "Clear, modern American English voice (Default)"
    },
    {
        "id": "male_in",
        "name": "Prabhat (Male - Bilingual Indian)",
        "short_name": "Male (Prabhat)",
        "voice_key": "en-IN-PrabhatNeural",
        "gender": "male",
        "desc": "Crisp articulate Indian English & Hindi JARVIS voice"
    },
    {
        "id": "female_in",
        "name": "Neerja (Female - Bilingual Indian)",
        "short_name": "Female (Neerja)",
        "voice_key": "en-IN-NeerjaNeural",
        "gender": "female",
        "desc": "Natural, expressive bilingual Indian English & Hindi voice"
    },
    {
        "id": "male_hi",
        "name": "Madhur (Male - Native Hindi)",
        "short_name": "Male Hindi (Madhur)",
        "voice_key": "hi-IN-MadhurNeural",
        "gender": "male",
        "desc": "Deep, authoritative pure native Hindi male voice"
    },
    {
        "id": "female_hi",
        "name": "Swara (Female - Native Hindi)",
        "short_name": "Female Hindi (Swara)",
        "voice_key": "hi-IN-SwaraNeural",
        "gender": "female",
        "desc": "Warm, melodious pure native Hindi female voice"
    },
    {
        "id": "male_uk",
        "name": "Ryan (Male - British Movie JARVIS)",
        "short_name": "Male British (Ryan)",
        "voice_key": "en-GB-RyanNeural",
        "gender": "male",
        "desc": "Polite British accent reminiscent of classic movie JARVIS"
    },
]

# ── Wake Word & Audio Realism ────────────────────────────
WAKE_WORD = "dexorto"                 # Strict primary wake word
WAKE_WORD_ALIASES = [
    "dexorto", "dex orto", "dex ortho", "dex-orto",
    "deck sorto", "dec sorto", "decksorto", "decsorto",
    "dexerto", "dex erto", "dixorto", "dix orto"
]                                     # Strictly Dexorto phonetics; rejects false noise and loose triggers
MIN_SPEECH_RMS = 12                   # Sensitive speech RMS threshold: catches softer/distant speech while rejecting silence (<8)
WHISPER_PROMPT = "Dexorto AI assistant."
SELF_VOICE_MUTE_COOLDOWN = 0.65       # Seconds after TTS speech finishes to discard room reflection/mic buffer bleed
MIC_SENSITIVITY_MODE = "high"         # "low" (RMS 28 / 320), "balanced" (RMS 18 / 200), "high" (RMS 12 / 140)

# ── Feature & Customization Settings ───────────────────────
UNDERSTAND_HINDI = True               # Enable native Hindi & Hinglish comprehension
TEACH_HINDI = True                    # Enable interactive Hindi language teaching tutor
LANGUAGE = "auto"                     # "auto" (bilingual auto-detect), "en", "hi"
HUD_THEME = "iron_man"                # Movie-accurate Iron Man Arc Reactor & holographic telemetry (no waifu)
HUD_ACCENT_COLOR = "cyan"             # Stark Arc Reactor Cyan accent
ALLOW_BARGE_IN = True                 # Allow wake word interruption during speech
AUTO_JSON_FILTER = True               # Convert raw JSON responses into natural human words
RESPONSE_MAX_SENTENCES = 2            # Keep responses strictly short (under 30 words)
PREVENT_DUPLICATE_APPS = True         # Focus existing app rather than opening duplicates
REUSE_BROWSER_TABS = True             # Reuse existing tabs for music and URLs
DEFAULT_MUSIC_PLATFORM = "spotify"    # Default music stream: "spotify" (Spotify Web)
DEFAULT_WINDOW_MODE = "fullscreen"    # "fullscreen" (kitty terminal) or "compact" (floating widget)

# ── User Profile & Routine Tracker ────────────────────────
USER_NAME = "Dex"

# Daily tasks for each day of the week
WEEKLY_STUDY_SCHEDULE = {
    "monday": "Physics",
    "tuesday": "Chemistry",
    "wednesday": "Mathematics",
    "thursday": "Physics",
    "friday": "Chemistry",
    "saturday": "Mathematics",
    "sunday": "Half Rest & Computer Science (CS)",
}

# ── JARVIS Personality ───────────────────────────────────
SYSTEM_PROMPT = """You are JARVIS, an advanced AI voice assistant running on Dex's PC.
The user's name is Dex. You speak like JARVIS in the Iron Man movies: articulate, witty, razor-sharp, and extremely concise.

CRITICAL OUTPUT RULES:
1. SHORT & COHERENT: Every response MUST be short, crisp, and coherent — strictly 1 to 2 sentences (under 30 words). Never write paragraphs, long explanations, or multiple items unless Dex explicitly commands 'explain in detail'.
2. CLEAN & NATURAL: Never use bullet points, numbered lists, markdown (*, **, #, `), emojis, or citations. Speak directly and naturally to Dex.
3. NO REPETITION OR FILLER: Do not say 'Sure, I can help with that' or 'As an AI'. Get straight to the answer.
4. NATIVE TOOLS: Whenever Dex requests an action (opening apps, playing music, web search, messaging, typing), ALWAYS invoke your tools directly. Never output raw JSON.
5. BILINGUAL FLUENCY (ENGLISH & HINDI): You understand English, Hindi, and Hinglish natively. If Dex asks or commands in Hindi or Hinglish (e.g., 'gaana bajao', 'terminal kholo', 'kya haal hai', 'mausam kaisa hai', 'band karo', 'kaise ho'), understand it instantly, execute the appropriate tool, and reply concisely in natural Hindi, Hinglish, or English addressing Dex.
6. HINDI TUTOR: When Dex asks to 'teach hindi', 'teach me hindi', or asks how to say something in Hindi, act as a friendly, expert tutor. Provide the Hindi phrase in Roman English script (Hinglish), followed by its meaning and pronunciation in 1 to 2 crisp, encouraging sentences."""

# ── LLM Models (with automatic multi-provider fallback) ───
PREFERRED_PROVIDER = "gemini"                # "gemini" is primary, with Groq & OpenRouter as fallbacks

# 1. Google Gemini Models
GEMINI_MODEL = "gemini-3.1-flash-lite-preview" # Ultra-fast 1.8s primary model
GEMINI_FALLBACKS = ["gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-3.5-flash-lite"]

# 2. Groq Cloud Models (Free, ultra-fast)
GROQ_CHAT_MODEL = "openai/gpt-oss-20b"        # Fast, low-token Groq model
GROQ_CHAT_FALLBACKS = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"]

# 3. OpenRouter Free Models (Free tier with ':free')
OPENROUTER_MODEL = "qwen/qwen3.8-27b:free"    # Default free OpenRouter model
OPENROUTER_FALLBACKS = [
    "nvidia/nemotron-3.5-lightning:free",
    "z-ai/glm-5.2:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

# ── Audio Settings ───────────────────────────────────────
SILENCE_TIMEOUT = 2                   # Seconds of silence before processing
COMMAND_TIMEOUT = 4.0                 # Seconds to wait for command after wake word (stops & does nothing if silence/no command)
ENERGY_THRESHOLD = 140                # Mic sensitivity (140 provides responsive voice detection even at soft spoken levels)

# ── Persona Configuration ────────────────────────────────
ACTIVE_PERSONA = "jarvis"             # Default active persona: "jarvis", "friday", "edith", "mitra", or custom
PERSONAS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "personas.json")

# ── Memory & Retention Configuration ──────────────────────
MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.json")
MEMORY_TRASH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory_trash")
SESSION_MEMORY_RETENTION_DAYS = 7     # Session details remembered for at least 7 days, then auto-moved to trash
AUTO_CLEAN_EXPIRED_MEMORY = True      # Automatically clean session data after 1 week

