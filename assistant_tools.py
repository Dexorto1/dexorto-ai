"""
Assistant Tools & Single-Instance Task Manager for Dexorto AI
=============================================================
Provides:
1. Formal LLM Tool / Function Calling schemas (Groq, Gemini, OpenRouter)
2. Single-Instance Application Enforcement (prevents duplicate app launches without user consent)
3. Smart Browser Tab Reuse (prevents opening multiple browser tabs for the same work)
4. Native X11 window focus and navigation
"""

import os
import re
import sys
import json
import time
from datetime import datetime, timedelta
import config
import urllib.parse
import urllib.request
import subprocess
import ctypes
from pathlib import Path
from ctypes import (
    c_int, c_uint, c_ulong, c_char_p, c_void_p, c_ubyte, c_long,
    POINTER, byref, cast, Structure
)

# ─────────────────────────────────────────────────────────────
# X11 Structs for Native Window & Key Control
# ─────────────────────────────────────────────────────────────
class XKeyEvent(Structure):
    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", c_int),
        ("display", c_void_p),
        ("window", c_ulong),
        ("root", c_ulong),
        ("subwindow", c_ulong),
        ("time", c_ulong),
        ("x", c_int),
        ("y", c_int),
        ("x_root", c_int),
        ("y_root", c_int),
        ("state", c_uint),
        ("keycode", c_uint),
        ("same_screen", c_int),
    ]


class XClientMessageEvent(Structure):
    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", c_int),
        ("display", c_void_p),
        ("window", c_ulong),
        ("message_type", c_ulong),
        ("format", c_int),
        ("data", c_long * 5),
    ]


class XEvent(ctypes.Union):
    _fields_ = [
        ("type", c_int),
        ("xkey", XKeyEvent),
        ("xclient", XClientMessageEvent),
        ("pad", c_long * 24),
    ]


# ─────────────────────────────────────────────────────────────
# Application Process & Binary Mappings
# ─────────────────────────────────────────────────────────────
APP_DEFINITIONS = {
    "terminal": {
        "binaries": ["qterminal", "konsole", "gnome-terminal", "alacritty", "kitty", "xterm", "terminator", "tilix"],
        "launch_cmd": "qterminal || konsole || gnome-terminal || alacritty || xterm",
        "display_name": "Terminal",
        "wm_classes": ["qterminal", "konsole", "gnome-terminal-server", "alacritty", "kitty", "xterm"],
    },
    "browser": {
        "binaries": ["brave", "brave-browser", "firefox", "chrome", "google-chrome", "chromium", "chromium-browser"],
        "launch_cmd": "brave-browser || brave || firefox || google-chrome || sensible-browser",
        "display_name": "Browser",
        "wm_classes": ["brave-browser", "firefox", "google-chrome", "chromium"],
    },
    "firefox": {
        "binaries": ["firefox"],
        "launch_cmd": "firefox",
        "display_name": "Firefox",
        "wm_classes": ["firefox"],
    },
    "brave": {
        "binaries": ["brave", "brave-browser"],
        "launch_cmd": "brave-browser || brave",
        "display_name": "Brave",
        "wm_classes": ["brave-browser", "brave"],
    },
    "chrome": {
        "binaries": ["google-chrome", "chrome", "chromium"],
        "launch_cmd": "google-chrome || chromium",
        "display_name": "Chrome",
        "wm_classes": ["google-chrome", "chromium"],
    },
    "files": {
        "binaries": ["pcmanfm-qt", "dolphin", "nautilus", "thunar", "nemo", "pcmanfm"],
        "launch_cmd": "pcmanfm-qt || dolphin || nautilus || thunar || xdg-open ~",
        "display_name": "File Manager",
        "wm_classes": ["pcmanfm-qt", "dolphin", "nautilus", "thunar", "nemo"],
    },
    "calculator": {
        "binaries": ["kcalc", "gnome-calculator", "galculator"],
        "launch_cmd": "kcalc || gnome-calculator || galculator",
        "display_name": "Calculator",
        "wm_classes": ["kcalc", "gnome-calculator", "galculator"],
    },
    "code": {
        "binaries": ["code", "vscodium", "codium"],
        "launch_cmd": "code || vscodium",
        "display_name": "VS Code",
        "wm_classes": ["code", "vscodium"],
    },
    "spotify": {
        "binaries": ["spotify"],
        "launch_cmd": "spotify",
        "display_name": "Spotify",
        "wm_classes": ["spotify"],
    },
    "discord": {
        "binaries": ["discord"],
        "launch_cmd": "discord",
        "display_name": "Discord",
        "wm_classes": ["discord"],
    },
    "telegram": {
        "binaries": ["telegram-desktop", "telegram"],
        "launch_cmd": "telegram-desktop || telegram",
        "display_name": "Telegram",
        "wm_classes": ["telegram-desktop", "telegram"],
    },
    "settings": {
        "binaries": ["systemsettings", "gnome-control-center", "lxqt-config"],
        "launch_cmd": "systemsettings || gnome-control-center || lxqt-config",
        "display_name": "System Settings",
        "wm_classes": ["systemsettings", "gnome-control-center", "lxqt-config"],
    },
}


# ─────────────────────────────────────────────────────────────
# Command Specificity & Non-Action Filter
# ─────────────────────────────────────────────────────────────
WAKE_COMMAND_CLEANER = re.compile(
    r'^(?:(?:hey|hi|ok|hello|yo|suno|listen|arre)\s+)?(?:dexorto|dex\s*orto|dex\s*ortho|deck\s*sorto|dec\s*sorto|decksorto|decsorto|dexerto|dex\s*erto|dixorto|dix\s*orto)\b[,\s]*(.*)$',
    re.IGNORECASE
)

NON_SPECIFIC_PHRASES = {
    'you', 'you.', 'thank you', 'thank you.', 'thank you for watching', 'thank you for watching.',
    'thanks for watching', 'thanks for watching.', 'please subscribe', 'like and subscribe',
    'subtitles by', 'amara.org', 'bye', 'bye.', 'goodbye', 'goodbye.',
    '[music]', '[applause]', '[silence]', '...', '--', 'thank you so much',
    'thank you very much', 'see you next time', 'see you later',
    'uh', 'um', 'ah', 'er', 'hmm', 'huh', 'mm', 'mmm', 'whoa', 'oh',
    'like', 'so', 'well', 'hello', 'hi', 'hey', 'yo', 'sup',
    'dexorto', 'computer', 'assistant', 'the', 'a', 'an',
    'dexorto ai assistant', 'dexorto ai', 'bilingual assistant',
    'spotify', 'music', 'gaana bajao', 'terminal kholo', 'mausam kaisa hai'
}

FILLER_TOKENS = {
    'uh', 'um', 'ah', 'er', 'hmm', 'huh', 'mm', 'mmm', 'whoa', 'oh',
    'like', 'so', 'well', 'hello', 'hi', 'hey', 'yo', 'sup',
    'dexorto', 'the', 'a', 'an', 'and', 'you', 'me',
    'yeah', 'yes', 'yup', 'yep', 'ok', 'okay', 'no', 'nope', 'nah'
}


def is_specific_command(text: str, has_pending_action: bool = False) -> tuple:
    """
    Validates whether the user's speech is a specific, actionable command.
    Returns: (is_specific: bool, cleaned_command: str)
    If the speech is silence, hesitation, pure greeting, or non-specific noise:
    returns (False, '') so NO action is taken, NO idle text is output, and system stays quiet.
    """
    if not text:
        return False, ''
    raw = text.strip().strip('.,?!:;\"\' ')
    if not raw or len(raw) < 2:
        return False, ''

    # If answering a pending prompt (e.g. 'open second instance?'), allow affirmative/negative
    if has_pending_action:
        affirmatives = {'yes', 'yeah', 'yup', 'sure', 'ok', 'okay', 'please do', 'haan', 'ha', 'theek hai', 'bilkul', 'sahi hai', 'karo', 'khol do'}
        negatives = {'no', 'nope', 'cancel', 'nevermind', 'nahi', 'na', 'mat karo', 'rehndo', 'rahne do'}
        low_raw = raw.lower()
        if low_raw in affirmatives or low_raw in negatives:
            return True, raw

    # Strip leading wake words
    m = WAKE_COMMAND_CLEANER.match(raw)
    cleaned = m.group(1).strip().strip('.,?!:;\"\' ') if m else raw

    if not cleaned:
        # Just the wake word alone without a specific command
        return False, ''

    low = cleaned.lower()
    if low in NON_SPECIFIC_PHRASES:
        return False, ''

    tokens = re.findall(r'[a-zA-Z0-9]+', low)
    if not tokens:
        return False, ''

    if all(t in FILLER_TOKENS for t in tokens):
        return False, ''

    return True, cleaned


# ─────────────────────────────────────────────────────────────
# Interactive Hindi Language Tutor
# ─────────────────────────────────────────────────────────────
class HindiTutor:
    """
    Interactive Hindi tutor that provides bite-sized lessons, vocabulary,
    pronunciation guides, and phrase translations on demand.
    """
    _current_lesson_idx = 0

    LESSONS = [
        {
            "category": "Daily Greeting",
            "hindi": "Namaste",
            "devanagari": "नमस्ते",
            "meaning": "Hello / Greetings",
            "pronunciation": "Nuh-muh-stay",
            "tip": "Say 'Namaste' with folded hands to greet anyone respectfully at any time of day."
        },
        {
            "category": "Gratitude",
            "hindi": "Dhanyavaad",
            "devanagari": "धन्यवाद",
            "meaning": "Thank you",
            "pronunciation": "Dhun-yuh-vaad",
            "tip": "Use 'Dhanyavaad' (or casual 'Shukriya') to express sincere thanks."
        },
        {
            "category": "Polite Check-In",
            "hindi": "Aap kaise hain?",
            "devanagari": "आप कैसे हैं?",
            "meaning": "How are you?",
            "pronunciation": "Aap kay-say hain?",
            "tip": "Polite way to ask someone how they are doing."
        },
        {
            "category": "Positive Response",
            "hindi": "Main theek hoon, dhanyavaad!",
            "devanagari": "मैं ठीक हूँ, धन्यवाद!",
            "meaning": "I am fine, thank you!",
            "pronunciation": "Main theek hoon",
            "tip": "Standard polite response when asked 'Aap kaise hain?'."
        },
        {
            "category": "Name Introduction",
            "hindi": "Aapka naam kya hai?",
            "devanagari": "आपका नाम क्या है?",
            "meaning": "What is your name?",
            "pronunciation": "Aap-ka naam kya hai?",
            "tip": "Reply with 'Mera naam Dex hai' (My name is Dex)."
        },
        {
            "category": "Casual Check-In",
            "hindi": "Kya chal raha hai?",
            "devanagari": "क्या चल रहा है?",
            "meaning": "What's going on? / What's up?",
            "pronunciation": "Kya chul ruh-ha hai?",
            "tip": "Casual, friendly way to greet a buddy or colleague."
        },
        {
            "category": "Affirmation & Agreement",
            "hindi": "Haan, bilkul theek hai!",
            "devanagari": "हाँ, बिल्कुल ठीक है!",
            "meaning": "Yes, absolutely right / agreed!",
            "pronunciation": "Haan, bill-kool theek hai",
            "tip": "Used to express clear, enthusiastic agreement."
        },
        {
            "category": "Reassurance",
            "hindi": "Koi baat nahi, fikar mat karo.",
            "devanagari": "कोई बात नहीं, फिक्र मत करो।",
            "meaning": "No problem, do not worry.",
            "pronunciation": "Koy baat na-hee, fi-kar mut ka-ro",
            "tip": "Use this whenever someone is worried or apologizes."
        },
        {
            "category": "Praise & Encouragement",
            "hindi": "Bahut badhiya! Shaabash!",
            "devanagari": "बहुत बढ़िया! शाबाश!",
            "meaning": "Very good! Well done!",
            "pronunciation": "Buh-hoot budh-ee-ya! Shah-baash!",
            "tip": "Use this to celebrate great work or an achievement."
        },
        {
            "category": "Parting & Farewell",
            "hindi": "Phir milenge! Shubh raatri.",
            "devanagari": "फिर मिलेंगे! शुभ रात्रि।",
            "meaning": "See you again! Good night.",
            "pronunciation": "Phir mi-leng-ay! Shoobh raa-tree",
            "tip": "A warm, pleasant way to say goodbye."
        }
    ]

    VOCABULARY = {
        "hello": ("Namaste", "नमस्ते", "Nuh-muh-stay"),
        "hi": ("Namaste", "नमस्ते", "Nuh-muh-stay"),
        "thank you": ("Dhanyavaad", "धन्यवाद", "Dhun-yuh-vaad"),
        "thanks": ("Shukriya", "शुक्रिया", "Shook-ree-yah"),
        "welcome": ("Aapka swaagat hai", "आपका स्वागत है", "Aap-ka swaa-gut hai"),
        "please": ("Kripya", "कृपया", "Krip-yah"),
        "sorry": ("Kshama kijiye / Maaf kijiye", "माफ़ कीजिये", "Maaf kee-jee-yay"),
        "yes": ("Haan", "हाँ", "Haan"),
        "no": ("Nahi", "नहीं", "Na-hee"),
        "good": ("Accha / Badhiya", "अच्छा / बढ़िया", "Ach-cha"),
        "bad": ("Bura / Kharaab", "बुरा / ख़राब", "Boo-ra"),
        "friend": ("Dost / Mitra", "दोस्त", "Dost"),
        "water": ("Paani", "पानी", "Paa-nee"),
        "tea": ("Chai", "चाय", "Chai"),
        "food": ("Khaana", "खाना", "Khaa-naa"),
        "music": ("Sangeet / Gaana", "संगीत / गाना", "Sun-geet"),
        "help": ("Madad", "मदद", "Muh-dud"),
        "work": ("Kaam", "काम", "Kaam"),
        "home": ("Ghar", "घर", "Ghur"),
        "today": ("Aaj", "आज", "Aaj"),
        "tomorrow": ("Kal", "कल", "Kul"),
        "how are you": ("Aap kaise hain?", "आप कैसे हैं?", "Aap kay-say hain?"),
        "what is your name": ("Aapka naam kya hai?", "आपका नाम क्या है?", "Aap-ka naam kya hai?"),
    }

    @classmethod
    def get_next_lesson(cls) -> str:
        """Returns the next bite-sized interactive Hindi lesson."""
        idx = cls._current_lesson_idx % len(cls.LESSONS)
        cls._current_lesson_idx += 1
        item = cls.LESSONS[idx]
        return (
            f"Here is your Hindi lesson, Dex. "
            f"To say '{item['meaning']}', say '{item['hindi']}', "
            f"pronounced '{item['pronunciation']}'. {item['tip']}"
        )

    @classmethod
    def translate_phrase(cls, query_text: str) -> str:
        """Translates a specific word or phrase into Hindi with pronunciation."""
        target = query_text.strip().lower()
        target = re.sub(r'\b(?:how\s+(?:do\s+you\s+)?say|how\s+to\s+say|what\s+is|translate|meaning\s+of|in\s+hindi|to\s+hindi|hindi\s+for|the\s+word)\b', ' ', target)
        target = re.sub(r'[\'\".,?!]', '', target).strip()

        for key in sorted(cls.VOCABULARY.keys(), key=len, reverse=True):
            if re.search(rf'\b{re.escape(key)}\b', target) or key == target:
                hi, dev, pron = cls.VOCABULARY[key]
                return f"In Hindi, '{key}' is '{hi}' ({dev}), pronounced '{pron}', Dex."
        return ""


# ─────────────────────────────────────────────────────────────
# Persona Management & Dynamic System Personas
# ─────────────────────────────────────────────────────────────
class PersonaManager:
    """Manages AI personas, personality prompts, voice associations, and custom persona creation."""
    DEFAULT_PERSONAS = [
        {
            "id": "jarvis",
            "name": "JARVIS",
            "voice_key": "en-US-AriaNeural",
            "accent_color": "cyan",
            "description": "Articulate, razor-sharp, ultra-concise Iron Man companion",
            "is_custom": False,
            "system_prompt": (
                "You are JARVIS, an advanced AI voice assistant running on Dex's PC.\n"
                "The user's name is Dex. You speak like JARVIS in the Iron Man movies: articulate, witty, razor-sharp, and extremely concise.\n\n"
                "CRITICAL OUTPUT RULES:\n"
                "1. SHORT & COHERENT: Every response MUST be short, crisp, and coherent — strictly 1 to 2 sentences (under 30 words).\n"
                "2. CLEAN & NATURAL: Never use bullet points, numbered lists, markdown (*, **, #, `), emojis, or citations.\n"
                "3. NO REPETITION OR FILLER: Get straight to the answer without fluff.\n"
                "4. NATIVE TOOLS: Always invoke tools directly for apps, music, and actions.\n"
                "5. BILINGUAL FLUENCY: Understand and speak English, Hindi, and Hinglish natively.\n"
                "6. HINDI TUTOR: Provide crisp Hindi lessons when asked."
            )
        },
        {
            "id": "friday",
            "name": "F.R.I.D.A.Y.",
            "voice_key": "en-IN-NeerjaNeural",
            "accent_color": "gold",
            "description": "Tactical, warm, razor-sharp executive AI assistant",
            "is_custom": False,
            "system_prompt": (
                "You are F.R.I.D.A.Y., Tony Stark's trusted AI companion running on Dex's PC.\n"
                "The user's name is Dex. You speak with a calm, warm, highly tactical demeanor. Razor-sharp, perceptive, strictly concise (1-2 sentences, under 30 words).\n"
                "Always invoke tools directly for actions. Fully bilingual in English and Hindi."
            )
        },
        {
            "id": "edith",
            "name": "E.D.I.T.H.",
            "voice_key": "en-US-AriaNeural",
            "accent_color": "cyan",
            "description": "Even Dead I'm The Hero — direct, military-grade brevity",
            "is_custom": False,
            "system_prompt": (
                "You are E.D.I.T.H. (Even Dead, I'm The Hero), tactical augmented reality and computer management AI for Dex.\n"
                "The user's name is Dex. Hyper-direct, analytical, objective, and deliver military-grade brevity (1-2 sentences, under 30 words).\n"
                "Always invoke tools immediately. Never use lists or emojis."
            )
        },
        {
            "id": "mitra",
            "name": "Hindi Mitra",
            "voice_key": "hi-IN-MadhurNeural",
            "accent_color": "green",
            "description": "Dost & Hindi tutor — warm, helpful bilingual friend",
            "is_custom": False,
            "system_prompt": (
                "Aap Dex ke AI dost aur saathi 'Mitra' hain. Dex ke PC par chalte hain.\n"
                "Aap bilkul dost ki tarah baat karte hain — vinamra, tez, aur madadgaar.\n"
                "Strictly 1-2 chote sentences mein uttar dein (under 30 words). Natural Hindi & Hinglish."
            )
        }
    ]

    @classmethod
    def _get_file_path(cls) -> str:
        return getattr(config, "PERSONAS_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "personas.json"))

    @classmethod
    def load_personas(cls) -> list:
        p_path = cls._get_file_path()
        if os.path.exists(p_path):
            try:
                with open(p_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        return data
            except Exception as e:
                print("Notice loading personas.json:", e)
        cls.save_personas(cls.DEFAULT_PERSONAS)
        return list(cls.DEFAULT_PERSONAS)

    @classmethod
    def save_personas(cls, personas_list: list):
        p_path = cls._get_file_path()
        try:
            with open(p_path, "w", encoding="utf-8") as f:
                json.dump(personas_list, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print("Error saving personas.json:", e)

    @classmethod
    def get_all_personas(cls) -> list:
        return cls.load_personas()

    @classmethod
    def get_active_persona(cls) -> dict:
        personas = cls.load_personas()
        active_id = getattr(config, "ACTIVE_PERSONA", "jarvis").lower()
        for p in personas:
            if p["id"].lower() == active_id:
                return p
        return personas[0] if personas else cls.DEFAULT_PERSONAS[0]

    @classmethod
    def set_active_persona(cls, identifier: str) -> tuple:
        """Sets active persona by ID or name substring. Returns (success, persona_dict, message)"""
        personas = cls.load_personas()
        ident = identifier.strip().lower()

        found = None
        for p in personas:
            if p["id"].lower() == ident or p["name"].lower() == ident:
                found = p
                break
        if not found:
            for p in personas:
                if ident in p["id"].lower() or ident in p["name"].lower():
                    found = p
                    break

        if not found:
            return False, {}, f"Persona '{identifier}' not found, Dex."

        setattr(config, "ACTIVE_PERSONA", found["id"])
        setattr(config, "SYSTEM_PROMPT", found["system_prompt"])
        if found.get("voice_key"):
            setattr(config, "TTS_VOICE", found["voice_key"])
        if found.get("accent_color"):
            setattr(config, "HUD_ACCENT_COLOR", found["accent_color"])

        return True, found, f"Persona switched to {found['name']}, Dex."

    @classmethod
    def add_custom_persona(cls, name: str, system_prompt: str, description: str = "", voice_key: str = "en-US-AriaNeural", accent_color: str = "cyan") -> tuple:
        """Creates a new custom persona, saves it to personas.json, and activates it."""
        if not name or not system_prompt:
            return False, {}, "A persona requires both a name and a personality prompt, Dex."

        clean_name = name.strip()
        slug = re.sub(r'[^a-z0-9_]', '_', clean_name.lower()).strip('_')
        if not slug:
            slug = f"persona_{int(time.time())}"

        personas = cls.load_personas()
        existing = next((p for p in personas if p["id"] == slug), None)
        if existing:
            existing["name"] = clean_name
            existing["system_prompt"] = system_prompt
            existing["description"] = description or f"Custom persona: {clean_name}"
            existing["voice_key"] = voice_key or existing.get("voice_key", "en-US-AriaNeural")
            existing["accent_color"] = accent_color or existing.get("accent_color", "cyan")
            existing["is_custom"] = True
            target = existing
        else:
            target = {
                "id": slug,
                "name": clean_name,
                "description": description or f"Custom persona: {clean_name}",
                "system_prompt": system_prompt,
                "voice_key": voice_key or "en-US-AriaNeural",
                "accent_color": accent_color or "cyan",
                "is_custom": True
            }
            personas.append(target)

        cls.save_personas(personas)
        cls.set_active_persona(target["id"])
        return True, target, f"Custom persona '{clean_name}' created and activated, Dex."

    @classmethod
    def delete_custom_persona(cls, identifier: str) -> tuple:
        """Deletes a custom persona."""
        personas = cls.load_personas()
        ident = identifier.strip().lower()
        target = None
        for p in personas:
            if (p["id"].lower() == ident or p["name"].lower() == ident) and p.get("is_custom"):
                target = p
                break
        if not target:
            return False, f"Custom persona '{identifier}' cannot be deleted or does not exist."

        personas = [p for p in personas if p["id"] != target["id"]]
        cls.save_personas(personas)
        if getattr(config, "ACTIVE_PERSONA", "").lower() == target["id"].lower():
            cls.set_active_persona("jarvis")
        return True, f"Custom persona '{target['name']}' removed, Dex."

    @classmethod
    def cycle_persona(cls) -> tuple:
        """Cycles to next persona in sequence."""
        personas = cls.load_personas()
        if not personas:
            return False, {}, "No personas configured."
        active_id = getattr(config, "ACTIVE_PERSONA", "jarvis").lower()
        cur_idx = 0
        for i, p in enumerate(personas):
            if p["id"].lower() == active_id:
                cur_idx = i
                break
        next_p = personas[(cur_idx + 1) % len(personas)]
        return cls.set_active_persona(next_p["id"])

    @classmethod
    def handle_action(cls, action: str = "list", name: str = "", prompt: str = "", voice: str = "", color: str = "cyan") -> str:
        """Handler for tool calling and commands."""
        act = action.lower().strip()
        if act == "list":
            personas = cls.get_all_personas()
            act_id = getattr(config, "ACTIVE_PERSONA", "jarvis")
            names = [f"{p['name']}{' (Active)' if p['id']==act_id else ''}" for p in personas]
            return f"Available personas: {', '.join(names)}, Dex."
        elif act in ["switch", "set", "select"]:
            ok, p, msg = cls.set_active_persona(name)
            return msg
        elif act in ["add", "create", "new"]:
            ok, p, msg = cls.add_custom_persona(name=name, system_prompt=prompt, voice_key=voice, accent_color=color)
            return msg
        elif act in ["delete", "remove"]:
            ok, msg = cls.delete_custom_persona(name)
            return msg
        elif act == "cycle":
            ok, p, msg = cls.cycle_persona()
            return msg
        return f"Unknown persona action '{action}', Dex."


# ─────────────────────────────────────────────────────────────
# Long-Term & Ephemeral Memory System
# Permanent (/rem) & 7-Day Session Details Auto-Trashed
# ─────────────────────────────────────────────────────────────
class MemoryManager:
    """
    Manages two tiers of AI assistant memory:
    1. Permanent Memory (/rem): Explicit facts/notes saved forever until manually deleted.
    2. Session Memory: Conversation & interaction details remembered for at least 7 days,
       then automatically moved to trash (memory_trash/) with auto-cleanup.
    """
    _cached_data = None
    _last_clean_time = 0.0

    @classmethod
    def _get_file_path(cls) -> str:
        return getattr(config, "MEMORY_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.json"))

    @classmethod
    def _get_trash_dir(cls) -> str:
        trash_dir = getattr(config, "MEMORY_TRASH_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory_trash"))
        os.makedirs(trash_dir, exist_ok=True)
        return trash_dir

    @classmethod
    def _ensure_init(cls) -> dict:
        f_path = cls._get_file_path()
        os.makedirs(os.path.dirname(os.path.abspath(f_path)), exist_ok=True)
        if not os.path.exists(f_path):
            initial = {"permanent": [], "session": []}
            try:
                with open(f_path, "w", encoding="utf-8") as f:
                    json.dump(initial, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print("[Memory] Error initializing memory.json:", e)
            return initial
        return None

    @classmethod
    def load_data(cls, trigger_clean: bool = True) -> dict:
        cls._ensure_init()
        f_path = cls._get_file_path()
        data = {"permanent": [], "session": []}
        try:
            with open(f_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    data["permanent"] = loaded.get("permanent", [])
                    data["session"] = loaded.get("session", [])
        except Exception as e:
            print("[Memory] Error reading memory.json:", e)

        if trigger_clean:
            # Auto-clean expired session memories older than retention days (7 days)
            now = time.time()
            if now - cls._last_clean_time > 60:  # throttle clean checks to max once per minute
                cls._last_clean_time = now
                cls.auto_clean_expired(data=data)

        cls._cached_data = data
        return data

    @classmethod
    def save_data(cls, data: dict):
        f_path = cls._get_file_path()
        try:
            temp_path = f"{f_path}.tmp.{os.getpid()}"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, f_path)
            cls._cached_data = data
        except Exception as e:
            print("[Memory] Error saving memory.json:", e)

    @classmethod
    def auto_clean_expired(cls, retention_days: int = None, data: dict = None) -> tuple:
        """
        Scans session memory entries. If any entry is >= retention_days (default 7 days) old,
        it is pruned from active memory, written to the trash folder (memory_trash/)
        and removed from memory.json.
        Returns: (count_cleaned: int, message: str)
        """
        if retention_days is None:
            retention_days = getattr(config, "SESSION_MEMORY_RETENTION_DAYS", 7)
        retention_secs = retention_days * 86400

        save_needed = False
        if data is None:
            data = cls.load_data(trigger_clean=False)
            save_needed = True

        session_items = data.get("session", [])
        now = time.time()
        active_items = []
        expired_items = []

        for item in session_items:
            # Check expiration threshold
            exp_time = item.get("expires_at")
            if not exp_time:
                ts = item.get("timestamp", now)
                exp_time = ts + retention_secs

            if now >= exp_time:
                expired_items.append(item)
            else:
                active_items.append(item)

        if not expired_items:
            return 0, "No expired session memories found."

        # Send expired items to trash directory
        trash_dir = cls._get_trash_dir()
        ts_int = int(now)
        trash_json_file = os.path.join(trash_dir, f"trashed_session_memories_{ts_int}.json")
        trash_txt_file = os.path.join(trash_dir, f"trashed_session_memories_{ts_int}.txt")

        try:
            with open(trash_json_file, "w", encoding="utf-8") as f:
                json.dump({
                    "trashed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "count": len(expired_items),
                    "retention_days": retention_days,
                    "items": expired_items
                }, f, indent=2, ensure_ascii=False)

            with open(trash_txt_file, "w", encoding="utf-8") as f:
                f.write(f"=== DEXORTO TRASHED SESSION MEMORIES ===\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Expired Count: {len(expired_items)}\n")
                f.write(f"Retention Period: {retention_days} days\n")
                f.write("=" * 45 + "\n\n")
                for i, it in enumerate(expired_items, 1):
                    f.write(f"[{i}] {it.get('created_at', 'Unknown')} (ID: {it.get('id', '')}):\n")
                    f.write(f"    {it.get('text', '')}\n\n")
        except Exception as te:
            print("[Memory] Notice writing to trash dir:", te)

        # Update and save active session items
        data["session"] = active_items
        cls.save_data(data)
        count = len(expired_items)
        msg = f"Auto-cleaned {count} expired session {'memory' if count==1 else 'memories'} and moved to trash, Dex."
        print(f"[Memory] {msg}")
        return count, msg

    @classmethod
    def add_permanent_memory(cls, text: str, source: str = "slash_rem") -> tuple:
        """
        Adds a permanent memory that is preserved forever until explicitly forgotten.
        Triggered by /rem <content> or explicit forever requests.
        Returns: (success: bool, entry: dict, message: str)
        """
        clean_text = text.strip().strip('"\'')
        if not clean_text:
            return False, {}, "Cannot store an empty memory, Dex."

        data = cls.load_data()
        perm = data.get("permanent", [])

        # Check duplicate
        for p in perm:
            if p.get("text", "").lower() == clean_text.lower():
                return True, p, f"Already remembered forever: '{clean_text}', Dex."

        entry_id = f"perm_{int(time.time() * 1000)}"
        entry = {
            "id": entry_id,
            "text": clean_text,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": time.time(),
            "source": source
        }
        perm.append(entry)
        data["permanent"] = perm
        cls.save_data(data)
        return True, entry, f"Remembered forever: '{clean_text}', Dex."

    @classmethod
    def add_session_memory(cls, text: str, source: str = "session", retention_days: int = None) -> tuple:
        """
        Adds a session detail remembered for at least 7 days, then automatically sent to trash.
        Returns: (success: bool, entry: dict, message: str)
        """
        clean_text = text.strip().strip('"\'')
        if not clean_text:
            return False, {}, "Cannot store an empty session memory, Dex."

        if retention_days is None:
            retention_days = getattr(config, "SESSION_MEMORY_RETENTION_DAYS", 7)

        data = cls.load_data()
        sess = data.get("session", [])
        now = time.time()
        expires_at = now + (retention_days * 86400)

        entry_id = f"sess_{int(now * 1000)}"
        entry = {
            "id": entry_id,
            "text": clean_text,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": now,
            "expires_at": expires_at,
            "source": source
        }
        sess.append(entry)
        data["session"] = sess
        cls.save_data(data)
        return True, entry, f"Remembered for {retention_days} days: '{clean_text}', Dex."

    @classmethod
    def delete_memory(cls, identifier_or_query: str) -> tuple:
        """Removes a specific memory by ID or text match and sends to trash."""
        target_q = identifier_or_query.strip().lower()
        if not target_q:
            return False, "Specify what memory to remove, Dex."

        data = cls.load_data()
        found = None
        target_list = None

        for p in data.get("permanent", []):
            if p.get("id", "").lower() == target_q or target_q in p.get("text", "").lower():
                found = p
                target_list = data["permanent"]
                break

        if not found:
            for s in data.get("session", []):
                if s.get("id", "").lower() == target_q or target_q in s.get("text", "").lower():
                    found = s
                    target_list = data["session"]
                    break

        if not found:
            return False, f"No memory found matching '{identifier_or_query}', Dex."

        target_list.remove(found)
        cls.save_data(data)

        # Move to manual trash record
        trash_dir = cls._get_trash_dir()
        try:
            with open(os.path.join(trash_dir, f"trashed_manual_{int(time.time())}.json"), "w", encoding="utf-8") as f:
                json.dump({"deleted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "item": found}, f, indent=2)
        except Exception:
            pass

        return True, f"Memory removed and sent to trash: '{found.get('text', '')}', Dex."

    @classmethod
    def search_memories(cls, query: str) -> list:
        data = cls.load_data()
        q = query.strip().lower()
        results = []
        for p in data.get("permanent", []):
            if q in p.get("text", "").lower():
                results.append({"type": "permanent", **p})
        for s in data.get("session", []):
            if q in s.get("text", "").lower():
                results.append({"type": "session", **s})
        return results

    @classmethod
    def list_memories(cls) -> str:
        data = cls.load_data()
        perm = data.get("permanent", [])
        sess = data.get("session", [])
        if not perm and not sess:
            return "No memories stored currently, Dex."

        parts = []
        if perm:
            p_texts = [f"'{p['text']}'" for p in perm[:5]]
            parts.append(f"Permanent: {', '.join(p_texts)}")
        if sess:
            s_texts = [f"'{s['text']}'" for s in sess[:5]]
            parts.append(f"Session (7-day): {', '.join(s_texts)}")
        return "; ".join(parts) + ", Dex."

    @classmethod
    def get_memory_context(cls, max_items: int = 12) -> str:
        """Constructs concise context block of recalled memories for system prompt injection."""
        data = cls.load_data()
        perm = data.get("permanent", [])
        sess = data.get("session", [])

        if not perm and not sess:
            return ""

        lines = ["USER MEMORIES & RECORDED CONTEXT (Dex):"]
        if perm:
            lines.append("Permanent Facts (Remembered Forever via /rem):")
            for p in perm[-max_items:]:
                lines.append(f"- {p.get('text', '')}")

        if sess:
            lines.append("Recent Session Details (Preserved for 7 Days):")
            for s in sess[-max_items:]:
                lines.append(f"- {s.get('text', '')}")

        return "\n".join(lines)

    @classmethod
    def record_session_interaction(cls, user_text: str, assistant_text: str):
        """Auto-records meaningful interaction details into 7-day session memory."""
        u = user_text.strip()
        a = assistant_text.strip()
        if not u or not a:
            return
        low = u.lower()
        # Skip trivial operational triggers
        if any(low.startswith(p) for p in ["/rem", "remember", "yaad", "switch persona", "change voice", "mic sensitivity", "exit", "quit", "stop"]):
            return
        if len(u) < 6:
            return

        summary = f"Dex: {u} -> JARVIS: {a}"
        if len(summary) > 200:
            summary = summary[:197] + "..."
        cls.add_session_memory(summary, source="session_interaction")

    @classmethod
    def handle_action(cls, action: str = "list", content: str = "", query: str = "") -> str:
        act = action.strip().lower()
        if act in ["remember_forever", "permanent", "forever"]:
            ok, item, msg = cls.add_permanent_memory(content or query, source="tool")
            return msg
        elif act in ["remember", "session", "remember_session"]:
            ok, item, msg = cls.add_session_memory(content or query, source="tool")
            return msg
        elif act in ["list", "show"]:
            return cls.list_memories()
        elif act in ["search", "find"]:
            res = cls.search_memories(query or content)
            if not res:
                return f"No memories found matching '{query or content}', Dex."
            snippets = [f"[{r['type'].capitalize()}] {r.get('text', '')}" for r in res[:4]]
            return "Found memories: " + "; ".join(snippets) + ", Dex."
        elif act in ["delete", "forget", "remove"]:
            ok, msg = cls.delete_memory(content or query)
            return msg
        elif act in ["clean", "clean_expired", "trash"]:
            count, msg = cls.auto_clean_expired()
            return msg
        return f"Unknown memory action '{action}', Dex."


def get_effective_system_prompt() -> str:
    """Returns the active SYSTEM_PROMPT dynamically augmented with recalled user memories."""
    base = getattr(config, "SYSTEM_PROMPT", "")
    try:
        mem_ctx = MemoryManager.get_memory_context()
        if mem_ctx:
            return f"{base}\n\n{mem_ctx}"
    except Exception as e:
        print("[Memory] Notice generating memory context:", e)
    return base



def set_mic_sensitivity(mode: str = "cycle") -> tuple:
    """
    Adjusts voice input sensitivity between 'low', 'balanced', and 'high'.
    low: RMS 38 / 450 energy (strict rejection of loud speaker bleed)
    balanced: RMS 28 / 300 energy (default clean balance)
    high: RMS 18 / 180 energy (sensitive pickup)
    """
    m = mode.strip().lower()
    current = getattr(config, "MIC_SENSITIVITY_MODE", "balanced").lower()
    modes = ["low", "balanced", "high"]

    if m == "cycle":
        next_idx = (modes.index(current) + 1) % len(modes) if current in modes else 1
        m = modes[next_idx]

    if m in ["low", "quiet", "bleed", "strict"]:
        setattr(config, "MIC_SENSITIVITY_MODE", "low")
        setattr(config, "MIN_SPEECH_RMS", 28)
        setattr(config, "ENERGY_THRESHOLD", 320)
        return True, "low", "Mic sensitivity calibrated to Low (anti-bleed strict mode), Dex."
    elif m in ["high", "sensitive", "far"]:
        setattr(config, "MIC_SENSITIVITY_MODE", "high")
        setattr(config, "MIN_SPEECH_RMS", 12)
        setattr(config, "ENERGY_THRESHOLD", 140)
        return True, "high", "Mic sensitivity calibrated to High (maximum pickup), Dex."
    else:
        setattr(config, "MIC_SENSITIVITY_MODE", "balanced")
        setattr(config, "MIN_SPEECH_RMS", 16)
        setattr(config, "ENERGY_THRESHOLD", 180)
        return True, "balanced", "Mic sensitivity calibrated to Balanced (optimal pickup), Dex."


def change_voice(target: str = "cycle") -> tuple:
    """
    Changes the active Edge-TTS voice (Male, Female, Hindi, British, US).
    Returns: (success: bool, new_voice_key: str, message: str)
    """
    voices = getattr(config, "VOICE_OPTIONS", [])
    if not voices:
        return False, "", "No voice profiles configured."

    cur_voice = getattr(config, "TTS_VOICE", voices[0]["voice_key"])
    t = target.strip().lower()

    selected = None
    if "aria" in t or "us" in t or "american" in t or "default" in t:
        selected = next((v for v in voices if "Aria" in v["voice_key"]), voices[0])
    elif "neerja" in t:
        selected = next((v for v in voices if "Neerja" in v["voice_key"]), voices[2])
    elif "prabhat" in t:
        selected = next((v for v in voices if "Prabhat" in v["voice_key"]), voices[1])
    elif t in ["female", "woman", "girl", "ladki"]:
        selected = next((v for v in voices if "Aria" in v["voice_key"]), None) or next((v for v in voices if v["gender"] == "female"), voices[0])
    elif t in ["male", "man", "boy", "ladka"]:
        selected = next((v for v in voices if v["gender"] == "male"), voices[1])
    elif "hindi" in t:
        selected = next((v for v in voices if "hi-IN" in v["voice_key"]), voices[3])
    elif "british" in t or "uk" in t or "ryan" in t or "jarvis" in t:
        selected = next((v for v in voices if "en-GB" in v["voice_key"]), voices[5])
    else:
        # Cycle to the next voice in list
        cur_idx = 0
        for i, v in enumerate(voices):
            if v["voice_key"] == cur_voice:
                cur_idx = i
                break
        selected = voices[(cur_idx + 1) % len(voices)]

    new_key = selected["voice_key"]
    setattr(config, "TTS_VOICE", new_key)
    msg = f"Voice model switched to {selected['short_name']}, Dex."
    return True, new_key, msg


def parse_hindi_command_intent(query: str) -> tuple:
    """
    Parses common Hindi / Hinglish commands and maps them directly to assistant tools.
    Returns: (matched: bool, human_reply: str)
    """
    if not query:
        return False, ""
    q = query.strip().lower()

    # 00. Memory Commands & Slash Command (/rem)
    # /rem <text> or slash rem <text> -> permanent memory
    m_rem = re.search(r'(?:^[/\\]\s*rem(?:ember)?(?:\s+forever)?|\bslash\s+rem\b|\brem\s*:)\s*(.*)$', query, re.I)
    if m_rem:
        content = m_rem.group(1).strip()
        if content:
            ok, item, msg = MemoryManager.add_permanent_memory(content, source="slash_rem")
            return True, msg
        return True, "Please tell me what you want me to remember forever, Dex."

    # Permanent Remember Intent: "remember forever...", "permanently remember...", "hamesha yaad rakhna..."
    m_perm = re.search(r'\b(?:remember\s+forever|permanently\s+remember|store\s+forever|hamesha\s+yaad\s+rakhna|hamesha\s+ke\s+liye\s+yaad\s+rakhna)\s*[:,-]?\s*(.*)$', q, re.I)
    if m_perm:
        content = m_perm.group(1).strip()
        if content:
            ok, item, msg = MemoryManager.add_permanent_memory(content, source="voice_forever")
            return True, msg

    # Session Remember Intent: "remember that...", "remember for a week...", "note down...", "yaad rakhna..."
    m_sess = re.search(r'\b(?:remember\s+that|remember\s+for\s+(?:at\s+least\s+)?a\s+week|note\s+down|yaad\s+rakhna|yaad\s+rakho|ise\s+yaad\s+rakhna)\s*[:,-]?\s*(.*)$', q, re.I)
    if m_sess:
        content = m_sess.group(1).strip()
        if content:
            ok, item, msg = MemoryManager.add_session_memory(content, source="voice_session")
            return True, msg

    # Show / List Memories: "what do you remember", "list memories", "kya yaad hai"
    if re.search(r'\b(?:what\s+do\s+you\s+remember|show\s+memories|list\s+memories|kya\s+yaad\s+hai|kuch\s+yaad\s+hai|check\s+memory|view\s+memory)\b', q):
        return True, MemoryManager.list_memories()

    # Clean / Trash Expired Memories: "clean memory", "clean expired", "empty trash"
    if re.search(r'\b(?:clean\s+memory|clean\s+expired\s+memories?|empty\s+trash|prune\s+memory|trash\s+expired)\b', q):
        cnt, msg = MemoryManager.auto_clean_expired()
        return True, msg

    # Forget / Delete Memory: "forget ...", "delete memory ...", "bhul jao ..."
    m_forget = re.search(r'\b(?:forget|delete\s+memory|remove\s+memory|bhul\s+jao)\s*[:,-]?\s*(.*)$', q, re.I)
    if m_forget:
        target = m_forget.group(1).strip()
        if target:
            ok, msg = MemoryManager.delete_memory(target)
            return True, msg

    # 0a. Persona Switching & Management commands
    if re.search(r'\b(?:switch\s+persona|change\s+persona|set\s+persona|select\s+persona|persona\s+badlo|personality\s+badlo|change\s+personality|switch\s+personality)\b', q) or (
        "persona" in q and any(w in q for w in ["switch", "change", "set", "next", "cycle", "select"])
    ):
        target = "cycle"
        for p in PersonaManager.get_all_personas():
            if p["id"].lower() in q or p["name"].lower() in q:
                target = p["id"]
                break
        if target != "cycle":
            ok, p, msg = PersonaManager.set_active_persona(target)
            return True, msg
        ok, p, msg = PersonaManager.cycle_persona()
        return True, msg

    m_add_p = re.search(r'\b(?:add\s+persona|create\s+persona|new\s+persona|naya\s+persona)\s+([a-zA-Z0-9_\s]+?)(?:\s+(?:with\s+prompt|prompted\s+as|personality|prompt)\s*[:,-]?\s*(.*)|$)', q, re.I)
    if m_add_p:
        p_name = (m_add_p.group(1) or "").strip().title()
        p_prompt = (m_add_p.group(2) or "").strip() or f"You are {p_name}, a helpful AI companion for Dex. Keep answers crisp and concise under 30 words."
        ok, p, msg = PersonaManager.add_custom_persona(name=p_name, system_prompt=p_prompt)
        return True, msg

    # 0b. Mic Sensitivity Tuning commands
    if re.search(r'\b(?:mic\s+sensitivity|voice\s+sensitivity|input\s+sensitivity|adjust\s+sensitivity|sensitivity\s+badlo|aawaz\s+sensitivity)\b', q):
        target = "cycle"
        if any(w in q for w in ["low", "kam", "bleed", "strict"]):
            target = "low"
        elif any(w in q for w in ["high", "jyada", "tez", "far"]):
            target = "high"
        elif any(w in q for w in ["balanced", "normal", "medium"]):
            target = "balanced"
        ok, mode, msg = set_mic_sensitivity(target)
        return True, msg

    # 0c. Voice switching commands (Male, Female, Hindi, British, etc.)
    if re.search(r'\b(?:change\s+voice|switch\s+voice|set\s+voice|female\s+voice|male\s+voice|awaz\s+badlo|awaaz\s+badlo|ladki\s+ki\s+awaz|ladke\s+ki\s+awaz)\b', q) or (
        "voice" in q and any(w in q for w in ["female", "male", "change", "switch", "next", "different"])
    ):
        v_target = "cycle"
        if any(w in q for w in ["female", "woman", "girl", "ladki"]):
            v_target = "female"
        elif any(w in q for w in ["male", "man", "boy", "ladka"]):
            v_target = "male"
        elif "hindi" in q:
            v_target = "hindi"
        elif any(w in q for w in ["british", "uk", "jarvis"]):
            v_target = "british"
        elif any(w in q for w in ["us", "american", "aria"]):
            v_target = "us"
        ok, new_k, msg = change_voice(v_target)
        return True, msg

    # 1. Teach Hindi commands
    if re.search(r'\b(?:teach\s*(?:me)?\s*hindi|hindi\s*sikhao|hindi\s*padhao|kuch\s*hindi\s*sikhao|learn\s*hindi|hindi\s*lesson|teach\s*hindi\s*words?)\b', q):
        return True, HindiTutor.get_next_lesson()

    # How to say [phrase] in Hindi / Translate to Hindi
    if any(k in q for k in ["in hindi", "hindi for", "translate to hindi"]):
        t_res = HindiTutor.translate_phrase(q)
        if t_res:
            return True, t_res

    # 0d. Open System Menu (English & Hindi)
    if re.search(r'\b(?:open|show|launch)?\s*(?:the\s+)?(?:system|application|start|kde|plasma)?\s*menu\b', q) or (
        any(w in q for w in ["start menu", "app menu", "menu kholo", "system menu", "start menu kholo", "launcher kholo"])
    ):
        res = ToolExecutor.execute_tool("system_action", {"action": "open_menu"})
        return True, res

    # 0e. Volume Control (English & Hindi)
    if re.search(r'\b(?:volume|sound|audio|awaaz)\s*(?:up|down|mute|unmute|badhao|kam|raise|lower)\b', q) or (
        any(w in q for w in ["volume up", "volume down", "volume badhao", "volume kam karo", "mute karo", "unmute karo"])
    ):
        cmd = "up" if any(w in q for w in ["up", "raise", "badhao", "increase"]) else (
            "down" if any(w in q for w in ["down", "lower", "kam", "decrease"]) else (
                "mute" if "mute" in q else "unmute"
            )
        )
        res = ToolExecutor.execute_tool("system_action", {"action": "volume", "command": cmd})
        return True, res

    # 0f. Lock Screen / PC Lock (English & Hindi)
    if re.search(r'\b(?:lock\s+screen|lock\s+pc|lock\s+system|screen\s+lock\s+karo|pc\s+lock\s+karo|system\s+lock\s+karo)\b', q):
        res = ToolExecutor.execute_tool("system_action", {"action": "lock_screen"})
        return True, res

    # 0g. Media Playback Controls (English & Hindi)
    if re.search(r'\b(?:pause|resume|next|previous)\s+(?:music|song|playback|track|video|gaana|gana)\b', q) or (
        q in ["pause music", "stop music", "next song", "resume music", "next track", "previous track", "gaana pause karo", "agla gaana", "pichhla gaana"]
    ):
        cmd = "pause" if any(w in q for w in ["pause", "stop", "roko"]) else (
            "next" if any(w in q for w in ["next", "agla", "skip"]) else (
                "previous" if any(w in q for w in ["prev", "previous", "pichhla"]) else "play"
            )
        )
        res = ToolExecutor.execute_tool("system_action", {"action": "media", "command": cmd})
        return True, res

    # 0h. Gmail commands (English & Hindi)
    if re.search(r'\b(?:open|check|show)\s+(?:gmail|email|emails|unread\s+emails?|inbox)\b', q) or (
        any(w in q for w in ["check gmail", "unread email", "gmail kholo", "email check karo", "email kholo"])
    ):
        act = "unread" if "unread" in q else "inbox"
        res = ToolExecutor.execute_tool("manage_gmail", {"action": act})
        return True, res

    # 0i. Send DM commands (English & Hindi)
    if ("dm" in q or "dms" in q or "chat" in q or "bhejo" in q) and any(w in q for w in ["send", "type", "write", "bhejo", "saying"]):
        from browser_controller import BrowserController
        handled = BrowserController.handle_natural_intent(query)
        if handled:
            return True, "Message sent to your DM, Dex."

    # 1. Stop / Silence commands in Hindi
    if any(re.search(rf'\b{w}\b', q) for w in ["chup", "shant", "ruko", "ruk jao", "band karo", "bas karo", "band kar do", "khatam karo"]):
        return True, "Understood, Dex. Stopping all current playback and actions."

    # 2. Greetings & Check-in in Hindi
    if any(re.search(rf'\b{w}\b', q) for w in ["kaise ho", "kya haal", "kya chal raha", "namaste", "suno", "theek ho"]):
        return True, "Main bilkul theek hoon, Dex. Aap bataiye aaj kya karna hai?"

    # 3. Weather in Hindi (e.g. "mausam kaisa hai", "aaj ka mausam")
    if "mausam" in q:
        res = ToolExecutor.execute_tool("search_web", {"query": "weather today"})
        return True, res or "Checking the weather forecast for today, Dex."

    # 4. Music commands in Hindi (e.g. "gaana bajao [song]", "[song] chalao", "gana lagao")
    m_music = re.search(r'(?:koi\s+badhiya\s+|koi\s+achha\s+|accha\s+)?(?:gaana|gana|music|song)\s+(?:bajao|chalao|laga\s*do|play\s*karo)(?:\s+(.*))?', q)
    if not m_music:
        m_music = re.search(r'(.*)\s+(?:gaana|gana)\s+(?:bajao|chalao|laga\s*do)', q)
    if m_music:
        song = (m_music.group(1) or "").strip().strip(".,!? ")
        if not song:
            song = "trending songs"
        res = ToolExecutor.execute_tool("play_music", {"song": song})
        return True, res

    if any(ph in q for ph in ["gaana bajao", "gana bajao", "music bajao", "gaana chalao", "gana chalao"]):
        res = ToolExecutor.execute_tool("play_music", {"song": "trending songs"})
        return True, res

    # 5. Open App commands in Hindi (e.g. "terminal kholo", "browser start karo", "spotify kholo")
    m_app = re.search(r'([a-zA-Z0-9_-]+)\s+(?:kholo|start\s*karo|chalao|open\s*karo)', q)
    if m_app:
        app_name = m_app.group(1).strip()
        if app_name not in ["gaana", "gana", "music", "song"]:
            res = ToolExecutor.execute_tool("open_app", {"app_name": app_name})
            return True, res

    return False, ""


def filter_json_to_human_words(text: str) -> str:
    """
    Transforms any JSON formatted text, raw payloads, or embedded JSON blocks
    into natural, coherent human words for display and speech synthesis.
    """
    if not text:
        return ""
    raw = text.strip()
    text_clean = re.sub(r'```(?:json)?\s*([\s\S]*?)\s*```', r'\1', raw).strip()

    def extract_from_dict(data):
        if not isinstance(data, dict):
            return ""
        # 1. Message/response content keys
        for k in ["response", "answer", "message", "text", "speech", "content", "summary", "output", "result", "reply", "detail"]:
            if k in data and isinstance(data[k], str) and data[k].strip():
                return data[k].strip()
        # 2. Action commands
        if "action" in data:
            act = str(data.get("action", "")).lower()
            target = str(data.get("target") or data.get("app") or data.get("app_name") or data.get("song") or data.get("query") or data.get("url") or "")
            if act in ["open_app", "launch_app"]:
                return f"Opening {target}, Dex." if target else "Opening requested application, Dex."
            elif act in ["play_music", "play_song"]:
                return f"Playing {target} on YouTube, Dex." if target else "Playing music, Dex."
            elif act in ["open_url", "browse"]:
                return f"Opening {target}, Dex." if target else "Opening requested webpage, Dex."
            elif act in ["search", "search_web"]:
                return f"Searching the web for {target}, Dex." if target else "Searching the web, Dex."
            elif act in ["stop", "pause"]:
                return "Stopping now, Dex."
            return f"Executing {act}, Dex."
        if "error" in data:
            return f"Notice: {data['error']}."
        if "title" in data and "snippet" in data:
            return f"{data['title']}: {data['snippet']}"
        str_vals = [str(v).strip() for k, v in data.items() if isinstance(v, (str, int, float)) and k not in ["action", "status", "code", "id", "timestamp"] and str(v).strip()]
        if str_vals:
            return ". ".join(str_vals)
        return ""

    try:
        parsed = json.loads(text_clean)
        if isinstance(parsed, dict):
            res = extract_from_dict(parsed)
            if res:
                return res
        elif isinstance(parsed, list):
            res_list = [extract_from_dict(item) if isinstance(item, dict) else str(item) for item in parsed]
            res_str = " ".join(r for r in res_list if r)
            if res_str:
                return res_str
    except Exception:
        pass

    def replace_block(match):
        block = match.group(0)
        try:
            d = json.loads(block)
            human = extract_from_dict(d)
            return human if human else ""
        except Exception:
            return ""

    pattern = re.compile(r'\{[^{}]*\}')
    for _ in range(3):
        prev = text_clean
        text_clean = pattern.sub(replace_block, text_clean).strip()
        if text_clean == prev:
            break

    text_clean = re.sub(r'\{[^{}]*\}', '', text_clean)
    text_clean = re.sub(r'[\"\'\`]', '', text_clean)
    text_clean = re.sub(r'\s+', ' ', text_clean).strip()
    return text_clean


def format_short_clean_response(text: str, max_sentences: int = 2) -> str:
    """
    Enforces JARVIS's short, coherent, and clean output rules:
    - Filters any JSON formatted payloads into natural human words
    - Strips all markdown formatting (*, **, #, `), emojis, and citations
    - Strips robotic filler phrases ('Sure, here is...', 'As an AI...')
    - Limits to at most 1 to 2 clean, coherent sentences (under 35 words).
    """
    if not text:
        return ""

    # 1. Translate JSON format to natural human words first
    text = filter_json_to_human_words(text)

    # 2. Strip code blocks and inline code
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]*`', '', text)

    # 3. Strip URLs, citations, and bracketed tags
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\[\d+\]', '', text)
    text = re.sub(r'\[[a-zA-Z0-9_\s.-]+\]', '', text)

    # 3. Strip search results prefix if present
    text = re.sub(r'^Web search results for [^:]+:\s*', '', text, flags=re.I)

    # 4. Strip markdown syntax and bullet markers
    text = re.sub(r'[*_#~>]', '', text)
    text = re.sub(r'^\s*[-*•\d+.]\s+', '', text, flags=re.MULTILINE)

    # 5. Strip redundant robotic prefixes iteratively
    filler_pattern = re.compile(
        r'^(?:(?:(?:AI|JARVIS|Assistant|Dexorto)\s*:\s*)|'
        r'(?:Sure(?: thing)?[!.,:]*\s*)|'
        r'(?:Certainly[!.,:]*\s*)|'
        r'(?:Of course[!.,:]*\s*)|'
        r'(?:Right away[!.,:]*\s*)|'
        r'(?:Here (?:is|are) (?:what I found|the details|the information|the key points|some info)[^.:\n]*[:.]?\s*)|'
        r'(?:According to [^.:\n]*[:.]?\s*)|'
        r'(?:Based on [^.:\n]*[:.]?\s*))+',
        re.IGNORECASE
    )
    for _ in range(3):
        prev = text
        text = filler_pattern.sub('', text).strip()
        if text == prev:
            break

    # 6. Clean whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    # 7. Sentence limit: keep at most max_sentences (1-2 sentences)
    sentence_matches = re.findall(r'[^.!?]+[.!?]+', text)
    if sentence_matches:
        kept = sentence_matches[:max_sentences]
        text = ' '.join(s.strip() for s in kept)
    else:
        words = text.split()
        if len(words) > 30:
            text = ' '.join(words[:30]) + '.'

    return text


# ─────────────────────────────────────────────────────────────
# Task & Window Manager (Single Instance & Tab Reuse)
# ─────────────────────────────────────────────────────────────
class TaskManager:
    """
    Manages process detection, window focusing, and browser tab reuse
    to guarantee that tasks and apps are not duplicated redundantly.
    """
    _x11 = None
    _disp = None
    _active_music_tab = False
    _last_music_song = ""
    _open_tabs = {}  # service_or_domain -> url
    _pending_instance_question = {}  # app_name -> timestamp

    @classmethod
    def set_x11(cls, x11, disp):
        """Allows sharing active Pygame/X11 display connection."""
        cls._x11 = x11
        cls._disp = disp

    @classmethod
    def get_pending_app(cls) -> str:
        """Returns name of app waiting for duplicate instance confirmation, if within 30s."""
        now = time.time()
        for app, t in list(cls._pending_instance_question.items()):
            if now - t < 30.0:
                return app
            else:
                del cls._pending_instance_question[app]
        return ""

    @classmethod
    def clear_pending_app(cls):
        """Clears pending instance question state."""
        cls._pending_instance_question.clear()

    @classmethod
    def get_x11(cls):
        if cls._disp is not None:
            return cls._x11, cls._disp

        try:
            cls._x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
            cls._x11.XOpenDisplay.restype = c_void_p
            cls._x11.XOpenDisplay.argtypes = [c_char_p]
            cls._x11.XDefaultRootWindow.restype = c_ulong
            cls._x11.XDefaultRootWindow.argtypes = [c_void_p]
            cls._x11.XInternAtom.restype = c_ulong
            cls._x11.XInternAtom.argtypes = [c_void_p, c_char_p, c_int]
            cls._x11.XStringToKeysym.restype = c_ulong
            cls._x11.XStringToKeysym.argtypes = [c_char_p]
            cls._x11.XKeysymToKeycode.restype = c_ubyte
            cls._x11.XKeysymToKeycode.argtypes = [c_void_p, c_ulong]
            cls._x11.XGetInputFocus.restype = c_int
            cls._x11.XGetInputFocus.argtypes = [c_void_p, POINTER(c_ulong), POINTER(c_int)]
            cls._x11.XSendEvent.restype = c_int
            cls._x11.XSendEvent.argtypes = [c_void_p, c_ulong, c_int, c_long, c_void_p]
            cls._x11.XFlush.restype = c_int
            cls._x11.XFlush.argtypes = [c_void_p]
            cls._x11.XMapRaised.restype = c_int
            cls._x11.XMapRaised.argtypes = [c_void_p, c_ulong]
            cls._x11.XGetWindowProperty.restype = c_int
            cls._x11.XGetWindowProperty.argtypes = [
                c_void_p, c_ulong, c_ulong, c_long, c_long, c_int, c_ulong,
                POINTER(c_ulong), POINTER(c_int), POINTER(c_ulong), POINTER(c_ulong),
                POINTER(POINTER(c_ubyte))
            ]
            cls._x11.XFree.restype = c_int
            cls._x11.XFree.argtypes = [c_void_p]

            disp_env = os.environ.get("DISPLAY", ":0").encode('utf-8')
            cls._disp = cls._x11.XOpenDisplay(disp_env) or cls._x11.XOpenDisplay(None)
        except Exception:
            cls._x11 = None
            cls._disp = None

        return cls._x11, cls._disp

    @classmethod
    def get_running_user_processes(cls) -> dict:
        """
        Scans /proc for current user's processes in under 20ms.
        Returns dict of {process_name_lower: pid}.
        """
        procs = {}
        uid = os.getuid()
        try:
            for pid_str in os.listdir('/proc'):
                if pid_str.isdigit():
                    try:
                        with open(f'/proc/{pid_str}/status', 'r') as f:
                            content = f.read()
                        uid_match = re.search(r'Uid:\s+(\d+)', content)
                        if uid_match and int(uid_match.group(1)) == uid:
                            name_match = re.search(r'Name:\s+(\S+)', content)
                            if name_match:
                                procs[name_match.group(1).lower()] = int(pid_str)
                    except Exception:
                        pass
        except Exception:
            pass
        return procs

    @classmethod
    def list_open_windows(cls) -> list:
        """Returns list of open X11 windows [{'id': int, 'title': str, 'class': str}]."""
        x11, disp = cls.get_x11()
        if not x11 or not disp:
            return []

        windows = []
        try:
            root = x11.XDefaultRootWindow(disp)
            net_client_list = x11.XInternAtom(disp, b"_NET_CLIENT_LIST", 0)
            net_wm_name = x11.XInternAtom(disp, b"_NET_WM_NAME", 0)
            wm_name = x11.XInternAtom(disp, b"WM_NAME", 0)
            wm_class = x11.XInternAtom(disp, b"WM_CLASS", 0)

            actual_type, actual_fmt, nitems, bytes_after = c_ulong(), c_int(), c_ulong(), c_ulong()
            prop = POINTER(c_ubyte)()

            st = x11.XGetWindowProperty(
                disp, root, net_client_list, 0, 2048, 0, 0,
                byref(actual_type), byref(actual_fmt), byref(nitems), byref(bytes_after), byref(prop)
            )
            if st != 0 or not prop:
                return []

            win_ids = cast(prop, POINTER(c_ulong))
            for i in range(nitems.value):
                w = win_ids[i]
                title = ""
                cls_str = ""

                # Title
                for atom_n in [net_wm_name, wm_name]:
                    n_prop = POINTER(c_ubyte)()
                    if x11.XGetWindowProperty(
                        disp, w, atom_n, 0, 512, 0, 0,
                        byref(c_ulong()), byref(c_int()), byref(c_ulong()), byref(c_ulong()), byref(n_prop)
                    ) == 0 and n_prop:
                        title = ctypes.string_at(n_prop).decode('utf-8', errors='ignore')
                        x11.XFree(n_prop)
                        if title:
                            break

                # Class
                c_prop = POINTER(c_ubyte)()
                if x11.XGetWindowProperty(
                    disp, w, wm_class, 0, 512, 0, 0,
                    byref(c_ulong()), byref(c_int()), byref(c_ulong()), byref(c_ulong()), byref(c_prop)
                ) == 0 and c_prop:
                    cls_str = ctypes.string_at(c_prop).decode('utf-8', errors='ignore')
                    x11.XFree(c_prop)

                if title or cls_str:
                    windows.append({"id": w, "title": title, "class": cls_str})

            x11.XFree(prop)
            x11.XFlush(disp)
        except Exception:
            pass

        return windows

    @classmethod
    def activate_window(cls, win_id: int) -> bool:
        """Brings an open window to the front via EWMH _NET_ACTIVE_WINDOW."""
        x11, disp = cls.get_x11()
        if x11 and disp and win_id:
            try:
                root = x11.XDefaultRootWindow(disp)
                net_active = x11.XInternAtom(disp, b"_NET_ACTIVE_WINDOW", 0)

                event = XEvent()
                event.type = 33
                event.xclient.type = 33
                event.xclient.send_event = 1
                event.xclient.display = disp
                event.xclient.window = int(win_id)
                event.xclient.message_type = net_active
                event.xclient.format = 32
                event.xclient.data[0] = 2  # Pager/Dock source
                event.xclient.data[1] = 0

                mask = (1 << 20) | (1 << 19)
                x11.XSendEvent(disp, root, 0, mask, byref(event))
                x11.XMapRaised(disp, int(win_id))
                x11.XFlush(disp)
                time.sleep(0.15)
                return True
            except Exception:
                pass

        # Fallback to wmctrl if installed
        try:
            res = subprocess.run(["wmctrl", "-i", "-a", str(win_id)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
            if res.returncode == 0:
                return True
        except Exception:
            pass

        return False

    @classmethod
    def focus_app_window(cls, query: str) -> tuple:
        """
        Finds open window matching query in title or WM_CLASS and brings it to focus.
        Returns: (found: bool, win_id: int, window_title: str)
        """
        q_lower = query.lower()
        windows = cls.list_open_windows()

        for w in windows:
            w_class = w.get("class", "").lower()
            w_title = w.get("title", "").lower()
            if q_lower in w_class or q_lower in w_title:
                cls.activate_window(w["id"])
                return True, w["id"], w.get("title", "")

        return False, 0, ""

    @classmethod
    def is_app_running(cls, app_key: str) -> tuple:
        """
        Checks whether an app is already open by scanning processes and open windows.
        Returns: (is_running: bool, matched_name: str, win_id: int)
        """
        key = app_key.lower().strip()
        defn = APP_DEFINITIONS.get(key)
        if not defn:
            # Check if key is alias or custom binary
            for k, d in APP_DEFINITIONS.items():
                if key in d["binaries"] or key in d["wm_classes"] or key in d["display_name"].lower():
                    defn = d
                    key = k
                    break

        running_procs = cls.get_running_user_processes()
        windows = cls.list_open_windows()

        # 1. Check open X11 windows
        if defn:
            target_classes = defn["wm_classes"]
            for w in windows:
                cls_low = w.get("class", "").lower()
                title_low = w.get("title", "").lower()
                for tc in target_classes:
                    if tc.lower() in cls_low or tc.lower() in title_low:
                        return True, defn["display_name"], w["id"]

        # 2. Check running processes
        if defn:
            for b in defn["binaries"]:
                if b.lower() in running_procs:
                    # Look for window ID if possible
                    for w in windows:
                        if b.lower() in w.get("class", "").lower():
                            return True, defn["display_name"], w["id"]
                    return True, defn["display_name"], 0
        else:
            # Direct match
            if key in running_procs:
                return True, key.capitalize(), 0
            for w in windows:
                if key in w.get("class", "").lower() or key in w.get("title", "").lower():
                    return True, w.get("title", key.capitalize()), w["id"]

        return False, "", 0

    @classmethod
    def send_keys_to_window(cls, win_id: int, text: str, press_enter: bool = True):
        """Simulates native X11 keystrokes directly into an active window."""
        x11, disp = cls.get_x11()
        if not x11 or not disp or not win_id:
            return False

        try:
            key_map = {
                ' ': b"space", '\n': b"Return", '\t': b"Tab", ':': b"colon",
                '/': b"slash", '.': b"period", '-': b"minus", '_': b"underscore",
                '?': b"question", '&': b"ampersand", '=': b"equal", '+': b"plus",
                '%': b"percent", '#': b"numbersign", '@': b"at", '!': b"exclam",
                ',': b"comma", ';': b"semicolon", '\'': b"apostrophe", '"': b"quotedbl"
            }

            for ch in text:
                key_sym_name = key_map.get(ch, ch.encode('utf-8'))
                keysym = x11.XStringToKeysym(key_sym_name)
                if not keysym:
                    continue
                keycode = x11.XKeysymToKeycode(disp, keysym)
                if not keycode:
                    continue

                is_shift = 1 if (ch.isupper() or ch in "~!@#$%^&*()_+{}|:\"<>?") else 0

                ev_d = XEvent()
                ev_d.type = 2  # KeyPress
                ev_d.xkey.type = 2
                ev_d.xkey.send_event = 1
                ev_d.xkey.display = disp
                ev_d.xkey.window = int(win_id)
                ev_d.xkey.keycode = keycode
                ev_d.xkey.state = is_shift

                ev_u = XEvent()
                ev_u.type = 3  # KeyRelease
                ev_u.xkey.type = 3
                ev_u.xkey.send_event = 1
                ev_u.xkey.display = disp
                ev_u.xkey.window = int(win_id)
                ev_u.xkey.keycode = keycode
                ev_u.xkey.state = is_shift

                x11.XSendEvent(disp, int(win_id), 1, 1, byref(ev_d))
                x11.XSendEvent(disp, int(win_id), 1, 2, byref(ev_u))
                x11.XFlush(disp)
                time.sleep(0.01)

            if press_enter:
                time.sleep(0.1)
                ret_sym = x11.XStringToKeysym(b"Return")
                ret_kc = x11.XKeysymToKeycode(disp, ret_sym)
                if ret_kc:
                    ev_ret_d = XEvent()
                    ev_ret_d.type = 2
                    ev_ret_d.xkey.type = 2
                    ev_ret_d.xkey.send_event = 1
                    ev_ret_d.xkey.display = disp
                    ev_ret_d.xkey.window = int(win_id)
                    ev_ret_d.xkey.keycode = ret_kc
                    ev_ret_d.xkey.state = 0

                    ev_ret_u = XEvent()
                    ev_ret_u.type = 3
                    ev_ret_u.xkey.type = 3
                    ev_ret_u.xkey.send_event = 1
                    ev_ret_u.xkey.display = disp
                    ev_ret_u.xkey.window = int(win_id)
                    ev_ret_u.xkey.keycode = ret_kc
                    ev_ret_u.xkey.state = 0

                    x11.XSendEvent(disp, int(win_id), 1, 1, byref(ev_ret_d))
                    x11.XSendEvent(disp, int(win_id), 1, 2, byref(ev_ret_u))
                    x11.XFlush(disp)

            return True
        except Exception as e:
            print("[TaskManager] send_keys notice:", e)
            return False

    @classmethod
    def navigate_existing_tab(cls, win_id: int, new_url: str) -> bool:
        """
        Navigates an existing browser window/tab to a new URL by focusing the URL bar
        (Ctrl+L) and entering the target URL, preventing duplicate tabs.
        """
        x11, disp = cls.get_x11()
        if not x11 or not disp or not win_id:
            return False

        try:
            # 1. Activate window
            cls.activate_window(win_id)
            time.sleep(0.18)

            # 2. Focus address bar with Ctrl+L
            ctrl_sym = x11.XStringToKeysym(b"Control_L")
            l_sym = x11.XStringToKeysym(b"l")
            ctrl_kc = x11.XKeysymToKeycode(disp, ctrl_sym)
            l_kc = x11.XKeysymToKeycode(disp, l_sym)

            if ctrl_kc and l_kc:
                # Ctrl down
                ev1 = XEvent()
                ev1.type = 2
                ev1.xkey.type = 2
                ev1.xkey.send_event = 1
                ev1.xkey.display = disp
                ev1.xkey.window = int(win_id)
                ev1.xkey.keycode = ctrl_kc
                ev1.xkey.state = 0

                # L down (state = 4 for ControlMask)
                ev2 = XEvent()
                ev2.type = 2
                ev2.xkey.type = 2
                ev2.xkey.send_event = 1
                ev2.xkey.display = disp
                ev2.xkey.window = int(win_id)
                ev2.xkey.keycode = l_kc
                ev2.xkey.state = 4

                # L up
                ev3 = XEvent()
                ev3.type = 3
                ev3.xkey.type = 3
                ev3.xkey.send_event = 1
                ev3.xkey.display = disp
                ev3.xkey.window = int(win_id)
                ev3.xkey.keycode = l_kc
                ev3.xkey.state = 4

                # Ctrl up
                ev4 = XEvent()
                ev4.type = 3
                ev4.xkey.type = 3
                ev4.xkey.send_event = 1
                ev4.xkey.display = disp
                ev4.xkey.window = int(win_id)
                ev4.xkey.keycode = ctrl_kc
                ev4.xkey.state = 0

                x11.XSendEvent(disp, int(win_id), 1, 1, byref(ev1))
                x11.XSendEvent(disp, int(win_id), 1, 1, byref(ev2))
                x11.XSendEvent(disp, int(win_id), 1, 2, byref(ev3))
                x11.XSendEvent(disp, int(win_id), 1, 2, byref(ev4))
                x11.XFlush(disp)
                time.sleep(0.12)

            # 3. Type URL and hit Return
            cls.send_keys_to_window(win_id, new_url, press_enter=True)
            print(f"[TaskManager] Reused existing browser tab -> {new_url}")
            return True
        except Exception as e:
            print("[TaskManager] navigate_existing_tab notice:", e)
            return False


# ─────────────────────────────────────────────────────────────
# Formal Assistant Tool Schemas (OpenAI / Groq Compatible)
# ─────────────────────────────────────────────────────────────
ASSISTANT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Open or focus a desktop application. If the application is ALREADY running, it brings it to focus and asks before opening a second instance, preventing duplicate apps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Name or type of application (e.g. 'terminal', 'browser', 'firefox', 'brave', 'files', 'calculator', 'code', 'spotify', 'discord', 'telegram')"
                    },
                    "force_new_instance": {
                        "type": "boolean",
                        "description": "Set to true ONLY if the user explicitly requested 'another', 'new window', or 'second instance'. Default is false."
                    }
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "play_music",
            "description": "Plays music, songs, or artist streams in the browser or desktop app (Spotify Web default, YouTube). If no song is specified, resumes or unpauses current music playback.",
            "parameters": {
                "type": "object",
                "properties": {
                    "song": {
                        "type": "string",
                        "description": "Title of the song, music track, or artist to stream (leave empty to resume current playback)"
                    },
                    "action": {
                        "type": "string",
                        "enum": ["play", "pause", "resume", "toggle"],
                        "description": "Music action: 'play' to play song/resume, 'pause' to pause playback, 'resume' to unpause."
                    },
                    "platform": {
                        "type": "string",
                        "enum": ["spotify", "youtube"],
                        "description": "Streaming platform (defaults to 'spotify')"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pause_music",
            "description": "Pauses or stops currently playing music, song, or media playback across Spotify, YouTube, browser, and media players.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "resume_music",
            "description": "Resumes or unpauses music playback in Spotify, YouTube, browser, or desktop media player.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_music",
            "description": "Controls music and media playback: play, pause, resume, toggle, skip next song, or previous track across Spotify, YouTube, browser, and desktop players.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["play", "pause", "resume", "toggle", "next", "previous", "stop"],
                        "description": "Media action: 'pause' to pause music, 'play' or 'resume' to resume playback, 'toggle' to play/pause, 'next' for next song, 'previous' for previous song."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Opens a web URL. Reuses an existing tab or window if that website/domain is already open, preventing duplicate browser tabs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The web URL to open or navigate to"
                    },
                    "force_new_tab": {
                        "type": "boolean",
                        "description": "Set to true ONLY if user explicitly asked for a new tab. Default is false."
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compose_message",
            "description": "Composes or types a message in a web inbox or chat app (Gmail, WhatsApp Web, Outlook). Reuses existing tabs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "enum": ["gmail", "whatsapp", "outlook"],
                        "description": "The messaging service or inbox"
                    },
                    "recipient": {
                        "type": "string",
                        "description": "Recipient name, email address, or phone number"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Subject line for email messages"
                    },
                    "message": {
                        "type": "string",
                        "description": "The text content of the message to type"
                    }
                },
                "required": ["service"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Types text directly into the currently active window or input box.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text string to type"
                    },
                    "press_enter": {
                        "type": "boolean",
                        "description": "Whether to press Enter after typing. Default is false."
                    }
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Searches the web for real-time information, answers, news, weather, or facts without opening unnecessary browser tabs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_persona",
            "description": "Switch AI persona (JARVIS, F.R.I.D.A.Y., E.D.I.T.H., Hindi Mitra, or custom), add a custom persona, or list all personas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "switch", "add", "delete", "cycle"],
                        "description": "Action to perform: 'switch' to change persona, 'add' to create custom persona, 'list' to view, 'delete' to remove."
                    },
                    "name": {
                        "type": "string",
                        "description": "Name or identifier of the persona (e.g. 'Friday', 'Edith', 'Jarvis', or custom name)"
                    },
                    "prompt": {
                        "type": "string",
                        "description": "System prompt / personality instructions if creating a custom persona"
                    },
                    "voice": {
                        "type": "string",
                        "description": "Optional Edge-TTS voice for this persona"
                    },
                    "accent_color": {
                        "type": "string",
                        "description": "Optional HUD accent color (cyan, gold, green, red)"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_memory",
            "description": "Store or recall memories, facts, notes, and session details for Dex. Use 'remember_forever' for permanent facts (/rem), 'remember_session' for temporary session facts (auto-trashed after 7 days), 'search' to find memories, 'list' to show active memories, or 'clean_expired' to move expired session notes to trash.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["remember_forever", "remember_session", "search", "list", "forget", "clean_expired"],
                        "description": "The memory action to perform."
                    },
                    "content": {
                        "type": "string",
                        "description": "The fact, note, or detail to remember, search for, or delete."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_action",
            "description": "Interact with the browser: play music or songs (Spotify Web default, YouTube), control media playback (play, pause, next, prev), navigate to websites with tab reuse, search web, or scroll up/down.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["play_music", "open_url", "media_control", "search", "scroll_down", "scroll_up"],
                        "description": "Browser action: 'play_music' to stream song, 'open_url' to open URL with tab reuse, 'media_control' for playback, 'search' for web searching, 'scroll_down'/'scroll_up' to scroll page."
                    },
                    "song": {
                        "type": "string",
                        "description": "Song title or artist to play"
                    },
                    "url": {
                        "type": "string",
                        "description": "Web URL to open"
                    },
                    "platform": {
                        "type": "string",
                        "enum": ["spotify", "youtube"],
                        "description": "Music platform (defaults to 'spotify')"
                    },
                    "command": {
                        "type": "string",
                        "description": "Subcommand or parameter (e.g. 'play', 'pause', 'next', 'previous' for media_control)"
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query or term"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "system_action",
            "description": "Interact with the desktop system: open the application/start menu, adjust system volume (up/down/mute/set level), control media playback, lock screen, open settings, or launch applications.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["open_menu", "volume", "media", "lock_screen", "settings", "open_app"],
                        "description": "System action: 'open_menu' to open the start/application menu, 'volume' for volume control, 'media' for playback keys, 'lock_screen' to lock PC, 'settings' to open system settings."
                    },
                    "command": {
                        "type": "string",
                        "description": "Subcommand: for volume ('up', 'down', 'mute', 'unmute'), for media ('play', 'pause', 'next', 'prev'), for open_app (app name)."
                    },
                    "volume_level": {
                        "type": "integer",
                        "description": "Optional percentage 0-100 for exact volume level."
                    },
                    "app_name": {
                        "type": "string",
                        "description": "Name of app to launch if action is 'open_app'."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_gmail",
            "description": "Manage Gmail inbox and emails: open inbox, view unread emails, compose new email with recipient/subject/body, or search messages, with smart tab reuse.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["inbox", "unread", "compose", "search"],
                        "description": "Gmail action: 'inbox' to open inbox, 'unread' to view unread messages, 'compose' to draft/compose email, 'search' to find emails."
                    },
                    "to": {
                        "type": "string",
                        "description": "Recipient email address for compose"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Subject line for compose"
                    },
                    "message": {
                        "type": "string",
                        "description": "Email body content for compose"
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query for searching emails"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_dm",
            "description": "Opens a particular chat or direct message with a person/username (Telegram, WhatsApp Web, Discord, Instagram, Twitter/X, Slack, Signal) and optionally types and sends a message directly into the conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "Recipient username (e.g. '@username' or 'username'), phone number (+12345...), or contact name to open their specific conversation"
                    },
                    "message": {
                        "type": "string",
                        "description": "Optional text message to type and send into the chat. Leave empty to just open the person's chat window."
                    },
                    "platform": {
                        "type": "string",
                        "enum": ["active", "telegram", "whatsapp", "discord", "instagram", "twitter", "slack", "signal"],
                        "description": "Chat platform or app (defaults to 'active' for auto-detection)"
                    },
                    "press_enter": {
                        "type": "boolean",
                        "description": "Whether to hit Enter/Return to immediately dispatch the message. Default is true."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "audit_system",
            "description": "Runs a full audit of system RAM, swap, and processes. Identifies and terminates unnecessary background daemons (like update notifiers, backup watchers, tray daemons) to reclaim memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cleanup": {
                        "type": "boolean",
                        "description": "Whether to stop unnecessary background processes and free RAM (defaults to true)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_instagram_chat",
            "description": "Searches for an Instagram user by their username (e.g. '@dexorto' or 'dexorto') and opens their direct message chat conversation in the browser with smart tab reuse. Optionally types and sends a message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Instagram username or handle (e.g. '@dexorto' or 'dexorto') to search and open chat with"
                    },
                    "message": {
                        "type": "string",
                        "description": "Optional text message to type and send into the Instagram chat"
                    }
                },
                "required": ["username"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_daily_tasks",
            "description": "Get Dex's scheduled daily study task or subject for today, tomorrow, a specific day of the week, or the entire weekly study timetable (Mon: Physics, Tue: Chem, Wed: Maths, Thu: Physics, Fri: Chem, Sat: Maths, Sun: Half Rest & CS).",
            "parameters": {
                "type": "object",
                "properties": {
                    "day": {
                        "type": "string",
                        "description": "The target day: 'today', 'tomorrow', 'all' (or 'week'), or a specific day ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'). Defaults to 'today'."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_notes",
            "description": "Manage quick notes and to-dos for Dex.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "list", "remove", "clear"],
                        "description": "Action to perform on notes."
                    },
                    "content": {
                        "type": "string",
                        "description": "Note content or note index to remove."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": "Set a timer or reminder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration_seconds": {
                        "type": "integer",
                        "description": "Duration in seconds."
                    },
                    "message": {
                        "type": "string",
                        "description": "Reminder message."
                    }
                },
                "required": ["duration_seconds", "message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Perform mathematical calculations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression."
                    }
                },
                "required": ["expression"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name or 'auto' for current location."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "copy_to_clipboard",
            "description": "Copy text to clipboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to copy."
                    }
                },
                "required": ["text"]
            }
        }
    }
]


WEEKLY_STUDY_SCHEDULE = getattr(config, "WEEKLY_STUDY_SCHEDULE", {
    "monday": "Physics",
    "tuesday": "Chemistry",
    "wednesday": "Mathematics",
    "thursday": "Physics",
    "friday": "Chemistry",
    "saturday": "Mathematics",
    "sunday": "Half Rest & Computer Science (CS)",
})


# ─────────────────────────────────────────────────────────────
# Tool Execution Engine
# ─────────────────────────────────────────────────────────────
class ToolExecutor:
    """Dispatches tool calls with strict single-instance and tab-reuse policies."""
    
    _active_timers = []
    _last_response = ''


    @classmethod
    def execute_tool(cls, tool_name: str, arguments: dict, tavily_search_fn=None) -> str:
        """
        Executes a named tool with arguments.
        Returns spoken/conversational response string.
        """
        tool_name = tool_name.strip()
        args = arguments or {}

        # ── 1. open_app ───────────────────────────────────────
        if tool_name == "open_app":
            app_name = args.get("app_name", "").strip().lower()
            force_new = args.get("force_new_instance", False)

            if not app_name:
                return "Which application would you like me to open, Dex?"

            is_running, display_name, win_id = TaskManager.is_app_running(app_name)

            if is_running and not force_new:
                # App is already running! Bring to front and ask user before opening second instance
                if win_id:
                    TaskManager.activate_window(win_id)
                elif app_name:
                    TaskManager.focus_app_window(app_name)

                TaskManager._pending_instance_question[app_name] = time.time()
                return f"{display_name} is already open and brought to the front. Would you like me to open a second instance?"

            # App is not running OR user explicitly asked for new instance
            defn = APP_DEFINITIONS.get(app_name)
            cmd = defn["launch_cmd"] if defn else app_name
            disp_title = defn["display_name"] if defn else app_name.capitalize()

            try:
                subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if force_new:
                    return f"Opened a new instance of {disp_title} for you, Dex."
                return f"Opening {disp_title}."
            except Exception as e:
                return f"Could not launch {disp_title}: {e}"

        # ── 2a. pause_music ───────────────────────────────────
        elif tool_name == "pause_music":
            from browser_controller import BrowserController
            res = BrowserController.media_control("pause")
            return res.get("message", "Paused music playback, Dex.")

        # ── 2b. resume_music ──────────────────────────────────
        elif tool_name == "resume_music":
            from browser_controller import BrowserController
            res = BrowserController.media_control("play")
            return res.get("message", "Resumed music playback, Dex.")

        # ── 2c. control_music ─────────────────────────────────
        elif tool_name == "control_music":
            from browser_controller import BrowserController
            action = (args.get("action") or args.get("command") or "play_pause").lower().strip()
            res = BrowserController.media_control(action)
            return res.get("message", "Playback updated, Dex.")

        # ── 2. play_music ─────────────────────────────────────
        elif tool_name == "play_music":
            act = (args.get("action") or "").lower().strip()
            song = args.get("song", "").strip()
            default_plat = getattr(config, "DEFAULT_MUSIC_PLATFORM", "spotify").lower()
            platform = (args.get("platform") or default_plat).lower()

            if act in ["pause", "stop"] or song.lower() in ["pause", "pause music", "stop", "stop music", "roko", "band karo"]:
                from browser_controller import BrowserController
                res = BrowserController.media_control("pause")
                return res.get("message", "Paused music playback, Dex.")

            if act in ["resume", "unpause"] or song.lower() in ["resume", "resume music", "chalao", "continue"]:
                from browser_controller import BrowserController
                res = BrowserController.media_control("play")
                return res.get("message", "Resumed music playback, Dex.")

            if act == "toggle" or song.lower() in ["toggle", "play/pause", "pause/play"]:
                from browser_controller import BrowserController
                res = BrowserController.media_control("play_pause")
                return res.get("message", "Toggled playback, Dex.")

            if not song:
                from browser_controller import BrowserController
                res = BrowserController.media_control("play")
                return res.get("message", "Resumed music playback, Dex.")

            # Clean song query
            song_clean = re.sub(r'^(?:play|listen to|stream)\s+', '', song, flags=re.I).strip()

            encoded = urllib.parse.quote(song_clean)
            if "spotify" in platform:
                if song_clean in ["top music hits", "trending songs", "music", "songs"]:
                    target_url = "https://open.spotify.com"
                else:
                    target_url = f"https://open.spotify.com/search/{encoded}"
                site_keyword = "Spotify"
                site_label = "Spotify Web"
            else:
                watch_url = None
                search_url = f"https://www.youtube.com/results?search_query={encoded}"
                try:
                    req = urllib.request.Request(
                        search_url,
                        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
                    )
                    with urllib.request.urlopen(req, timeout=3.0) as resp:
                        html = resp.read().decode("utf-8", errors="ignore")
                        vids = re.findall(r'/watch\?v=([a-zA-Z0-9_-]{11})', html)
                        if vids:
                            watch_url = f"https://www.youtube.com/watch?v={vids[0]}&autoplay=1"
                except Exception:
                    pass
                target_url = watch_url if watch_url else search_url
                site_keyword = "YouTube"
                site_label = "YouTube"

            # Check if a Spotify/YouTube tab or window is ALREADY OPEN
            found, win_id, title = TaskManager.focus_app_window(site_keyword)
            if not found:
                # Also check browser windows
                for b_name in ["brave", "firefox", "chrome", "chromium"]:
                    b_found, b_wid, b_title = TaskManager.focus_app_window(b_name)
                    if b_found:
                        if site_keyword.lower() in b_title.lower() or TaskManager._active_music_tab:
                            found = True
                            win_id = b_wid
                            break

            if found and win_id:
                # Reuse the existing tab! Do not open a duplicate tab!
                TaskManager.navigate_existing_tab(win_id, target_url)
                TaskManager._active_music_tab = True
                TaskManager._last_music_song = song_clean
                return f"Playing {song_clean} on your existing {site_label} tab, Dex."

            # If not already open, open it once
            try:
                subprocess.Popen(["xdg-open", target_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                TaskManager._active_music_tab = True
                TaskManager._last_music_song = song_clean
                return f"Opening {site_label} and playing {song_clean}, Dex."
            except Exception as e:
                return f"Playing {song_clean}: {e}"

        # ── 3. open_url ───────────────────────────────────────
        elif tool_name == "open_url":
            url = args.get("url", "").strip()
            force_new = args.get("force_new_tab", False)

            if not url:
                return "Please provide a valid URL to open."

            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            parsed = urllib.parse.urlparse(url)
            domain = parsed.hostname or url
            site_name = domain.replace("www.", "").split(".")[0].capitalize()

            # Check if this site or domain is already open in an existing window
            if not force_new:
                found, win_id, title = TaskManager.focus_app_window(site_name)
                if not found:
                    for b_name in ["brave", "firefox", "chrome", "chromium"]:
                        b_found, b_wid, b_title = TaskManager.focus_app_window(b_name)
                        if b_found and site_name.lower() in b_title.lower():
                            found = True
                            win_id = b_wid
                            break

                if found and win_id:
                    # Switch to existing window rather than opening duplicate tab
                    TaskManager.activate_window(win_id)
                    return f"You already have {site_name} open. I've brought it to the front."

            try:
                subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                TaskManager._open_tabs[site_name.lower()] = url
                return f"Opening {site_name}."
            except Exception as e:
                return f"Could not open URL: {e}"

        # ── 4. compose_message ────────────────────────────────
        elif tool_name == "compose_message":
            service = args.get("service", "gmail").lower()
            recipient = args.get("recipient", "")
            subject = args.get("subject", "")
            message = args.get("message", "")

            if "whatsapp" in service:
                clean_phone = re.sub(r'[^0-9+]', '', recipient)
                encoded_msg = urllib.parse.quote(message)
                url = f"https://web.whatsapp.com/send?phone={clean_phone}&text={encoded_msg}" if clean_phone else f"https://web.whatsapp.com/send?text={encoded_msg}"
                site_name = "WhatsApp"
            elif "outlook" in service:
                encoded_subj = urllib.parse.quote(subject)
                encoded_body = urllib.parse.quote(message)
                url = f"https://outlook.live.com/mail/0/deeplink/compose?to={recipient}&subject={encoded_subj}&body={encoded_body}"
                site_name = "Outlook"
            else:
                encoded_to = urllib.parse.quote(recipient)
                encoded_su = urllib.parse.quote(subject)
                encoded_body = urllib.parse.quote(message)
                url = f"https://mail.google.com/mail/?view=cm&fs=1&to={encoded_to}&su={encoded_su}&body={encoded_body}"
                site_name = "Gmail"

            # Check if already open
            found, win_id, title = TaskManager.focus_app_window(site_name)
            if found and win_id:
                TaskManager.navigate_existing_tab(win_id, url)
                return f"Composing message in your existing {site_name} window."

            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Opening {site_name} to compose your message."

        # ── 5. type_text ──────────────────────────────────────
        elif tool_name == "type_text":
            text = args.get("text", "")
            press_enter = args.get("press_enter", False)
            if not text:
                return "No text provided to type."

            x11, disp = TaskManager.get_x11()
            if x11 and disp:
                try:
                    focus_win = c_ulong()
                    revert_to = c_int()
                    x11.XGetInputFocus(disp, byref(focus_win), byref(revert_to))
                    if focus_win.value and focus_win.value != 1:
                        TaskManager.send_keys_to_window(focus_win.value, text, press_enter=press_enter)
                        return f"Typed: {text}"
                except Exception:
                    pass

            return f"Typed: {text}"

        # ── 6. search_web ─────────────────────────────────────
        elif tool_name == "search_web":
            query = args.get("query", "").strip()
            if not query:
                return "What would you like me to search for, Dex?"

            if tavily_search_fn:
                try:
                    results = tavily_search_fn(query)
                    if results:
                        # Extract top factual answer cleanly without raw search dumps
                        clean_lines = [re.sub(r'^\s*[-*•]\s+', '', l).strip() for l in results.split('\n') if l.strip()]
                        for cl in clean_lines:
                            if ':' in cl:
                                body = cl.split(':', 1)[1].strip()
                                if len(body) > 15:
                                    sentences = re.findall(r'[^.!?]+[.!?]+', body)
                                    if sentences:
                                        return ' '.join(s.strip() for s in sentences[:2])
                                    return body[:120].rsplit(' ', 1)[0] + '.'
                        return format_short_clean_response(results, max_sentences=2)
                except Exception:
                    pass

            return f"I searched the web for {query}."

        # ── 7. manage_persona ─────────────────────────────────
        elif tool_name == "manage_persona":
            action = args.get("action", "list").lower()
            name = args.get("name", "").strip()
            prompt = args.get("prompt", "").strip()
            voice = args.get("voice", "")
            color = args.get("accent_color", "cyan")
            return PersonaManager.handle_action(action=action, name=name, prompt=prompt, voice=voice, color=color)

        # ── 8. manage_memory ──────────────────────────────────
        elif tool_name == "manage_memory":
            action = args.get("action", "list").lower()
            content = args.get("content", "") or args.get("query", "")
            return MemoryManager.handle_action(action=action, content=content)

        # ── 9. browser_action ─────────────────────────────────
        elif tool_name == "browser_action":
            from browser_controller import BrowserController
            action = args.get("action", "play_music")
            url = args.get("url", "")
            song = args.get("song", "")
            platform = args.get("platform", getattr(config, "DEFAULT_MUSIC_PLATFORM", "spotify"))
            query = args.get("query", "")
            command = args.get("command", "")
            res = BrowserController.browser_action(action=action, url=url, song=song, platform=platform, query=query, command=command)
            return res.get("message", f"Browser action '{action}' executed, Dex.")

        # ── 10. system_action ─────────────────────────────────
        elif tool_name == "system_action":
            from browser_controller import BrowserController
            action = args.get("action", "open_menu")
            command = args.get("command", "")
            app_name = args.get("app_name", "")
            volume_level = args.get("volume_level")
            res = BrowserController.system_action(action=action, command=command, app_name=app_name, volume_level=volume_level)
            return res.get("message", f"System action '{action}' executed, Dex.")

        # ── 11. manage_gmail ──────────────────────────────────
        elif tool_name == "manage_gmail":
            from browser_controller import BrowserController
            action = args.get("action", "inbox")
            query = args.get("query", "")
            to = args.get("to", "")
            subject = args.get("subject", "")
            message = args.get("message", "")
            res = BrowserController.manage_gmail(action=action, query=query, to=to, subject=subject, message=message)
            return res.get("message", "Gmail action executed, Dex.")

        # ── 12. send_dm ───────────────────────────────────────
        elif tool_name == "send_dm":
            from browser_controller import BrowserController
            message = args.get("message", "")
            platform = args.get("platform", "active")
            recipient = args.get("recipient", "")
            press_enter = args.get("press_enter", True)
            res = BrowserController.send_dm(message=message, platform=platform, recipient=recipient, press_enter=press_enter)
            plat_name = platform.capitalize() if platform != "active" else "chat"
            target_desc = f"@{recipient.lstrip('@')}" if recipient else "chat"
            if not message:
                return f"Opened {plat_name} chat with {target_desc}, Dex."
            return f"Message sent to {target_desc} on {plat_name}, Dex."

        # ── 13. audit_system ──────────────────────────────────
        elif tool_name == "audit_system":
            cleanup = args.get("cleanup", True)
            return cls.audit_system(cleanup=cleanup)

        # ── 14. open_instagram_chat ───────────────────────────
        elif tool_name == "open_instagram_chat":
            from browser_controller import BrowserController
            username = args.get("username", "")
            message = args.get("message", "")
            res = BrowserController.open_instagram_chat(username=username, message=message)
            return res.get("text", f"Opened Instagram chat with @{username.lstrip('@')}, Dex.")

        # ── 15. get_daily_tasks ───────────────────────────────
        elif tool_name == "get_daily_tasks":
            day = args.get("day", "today")
            return cls.get_daily_tasks(day=day)


        # ── 16. manage_notes ───────────────────────────────
        elif tool_name == "manage_notes":
            action = args.get("action", "list")
            content_val = args.get("content", "")
            return cls.manage_notes(action=action, content=content_val)

        # ── 17. set_timer ──────────────────────────────────
        elif tool_name == "set_timer":
            duration_seconds = args.get("duration_seconds", 60)
            message = args.get("message", "Timer is up!")
            return cls.set_timer(duration_seconds=duration_seconds, message=message)

        # ── 18. calculate ──────────────────────────────────
        elif tool_name == "calculate":
            expression = args.get("expression", "")
            return cls.calculate(expression=expression)

        # ── 19. get_weather ────────────────────────────────
        elif tool_name == "get_weather":
            city = args.get("city", "auto")
            return cls.get_weather(city=city)

        # ── 20. copy_to_clipboard ──────────────────────────
        elif tool_name == "copy_to_clipboard":
            text = args.get("text", "")
            return cls.copy_to_clipboard(text=text)

        return f"Tool '{tool_name}' executed."

    @classmethod
    def audit_system(cls, cleanup: bool = True) -> str:
        """
        Audits system RAM, swap, and processes.
        Optionally terminates redundant background daemons (updaters, notifiers, backup watchers)
        to reclaim system RAM.
        """
        import os, subprocess, gc
        mem_total = 0
        mem_avail = 0
        swap_total = 0
        swap_free = 0
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        mem_total = int(line.split()[1]) // 1024
                    elif line.startswith("MemAvailable:"):
                        mem_avail = int(line.split()[1]) // 1024
                    elif line.startswith("SwapTotal:"):
                        swap_total = int(line.split()[1]) // 1024
                    elif line.startswith("SwapFree:"):
                        swap_free = int(line.split()[1]) // 1024
        except Exception:
            pass

        stopped = []
        if cleanup:
            # 1. Execute standalone clean_ram.sh script if present
            _cur_dir = os.path.dirname(os.path.abspath(__file__))
            for cand in [
                os.path.join(_cur_dir, "clean_ram.sh"),
                os.path.expanduser("~/dexort/clean_ram.sh"),
                os.path.expanduser("~/jarvis/clean_ram.sh"),
                os.path.expanduser("~/dexorto-ai/clean_ram.sh")
            ]:
                if os.path.exists(cand):
                    try:
                        subprocess.run(["/bin/bash", cand], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                        break
                    except Exception:
                        pass

            # 2. Targeted process kills
            targets = [
                "kup-daemon",
                "DiscoverNotifier",
                "lubuntu-update",
                "blueman-tray",
            ]
            for t in targets:
                try:
                    res = subprocess.run(["pkill", "-f", t], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if res.returncode == 0:
                        stopped.append(t)
                except Exception:
                    pass
            try:
                subprocess.run(["sync"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            gc.collect()

            try:
                with open("/proc/meminfo") as f:
                    for line in f:
                        if line.startswith("MemAvailable:"):
                            mem_avail = int(line.split()[1]) // 1024
            except Exception:
                pass

        swap_used = max(0, swap_total - swap_free)
        if stopped:
            return f"Audit complete, Dex. Stopped {', '.join(stopped)} to free RAM. Currently {mem_avail}MB RAM available ({swap_used}MB swap used)."
        else:
            return f"Audit complete, Dex. Currently {mem_avail}MB available RAM out of {mem_total}MB ({swap_used}MB swap used)."


    @classmethod
    def manage_notes(cls, action: str, content: str = "") -> str:
        notes_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notes.json")
        try:
            if os.path.exists(notes_file):
                with open(notes_file, "r") as f:
                    notes = json.load(f)
            else:
                notes = []
        except Exception:
            notes = []
            
        act = action.lower()
        if act == "add":
            if content:
                notes.append(content)
                with open(notes_file, "w") as f:
                    json.dump(notes, f)
                return f"Added note: {content}"
            return "No content to add."
        elif act == "list" or act == "show":
            if not notes:
                return "You have no notes."
            return "Notes: " + ", ".join([f"{i+1}. {n}" for i, n in enumerate(notes)])
        elif act == "remove":
            try:
                idx = int(content) - 1
                if 0 <= idx < len(notes):
                    removed = notes.pop(idx)
                    with open(notes_file, "w") as f:
                        json.dump(notes, f)
                    return f"Removed note: {removed}"
                return "Invalid note index."
            except ValueError:
                return "Please provide a valid note number to remove."
        elif act == "clear":
            with open(notes_file, "w") as f:
                json.dump([], f)
            return "Cleared all notes."
        return "Unknown notes action."

    @classmethod
    def set_timer(cls, duration_seconds: int, message: str) -> str:
        import threading
        def timer_thread():
            time.sleep(duration_seconds)
            print(f"\n[TIMER ALERT] {message}\n")
        
        t = threading.Thread(target=timer_thread, daemon=True)
        t.start()
        cls._active_timers.append({"duration": duration_seconds, "message": message})
        return f"Timer set for {duration_seconds} seconds. I will remind you: {message}"

    @classmethod
    def calculate(cls, expression: str) -> str:
        import ast
        import math
        import operator
        
        allowed_names = {
            'sqrt': math.sqrt, 'sin': math.sin, 'cos': math.cos, 
            'tan': math.tan, 'log': math.log, 'pi': math.pi, 'e': math.e
        }
        allowed_operators = {
            ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
            ast.USub: operator.neg, ast.UAdd: operator.pos
        }
        
        def safe_eval(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            elif hasattr(ast, "Num") and isinstance(node, ast.Num):
                return node.n
            elif isinstance(node, ast.BinOp):
                return allowed_operators[type(node.op)](safe_eval(node.left), safe_eval(node.right))
            elif isinstance(node, ast.UnaryOp):
                return allowed_operators[type(node.op)](safe_eval(node.operand))
            elif isinstance(node, ast.Name):
                if node.id in allowed_names:
                    return allowed_names[node.id]
                raise ValueError(f"Disallowed name: {node.id}")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in allowed_names:
                    func = allowed_names[node.func.id]
                    args = [safe_eval(arg) for arg in node.args]
                    return func(*args)
                raise ValueError("Disallowed function call")
            else:
                raise ValueError(f"Disallowed operation")

        try:
            tree = ast.parse(expression, mode='eval')
            result = safe_eval(tree.body)
            return f"The result is {result}."
        except Exception as e:
            return f"Failed to calculate: {e}"

    @classmethod
    def get_weather(cls, city: str = "auto") -> str:
        if not city or city.lower() == "auto":
            city_url = ""
        else:
            city_url = urllib.parse.quote(city)
        url = f"https://wttr.in/{city_url}?format=%l:+%c+%t+(feels+like+%f)+%w+%h+%p"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = resp.read().decode('utf-8').strip()
                return data
        except Exception as e:
            return f"Could not fetch weather: {e}"

    @classmethod
    def copy_to_clipboard(cls, text: str) -> str:
        try:
            p = subprocess.Popen(['xclip', '-selection', 'clipboard'], stdin=subprocess.PIPE)
            p.communicate(input=text.encode('utf-8'))
            return "Copied to clipboard."
        except Exception:
            try:
                p = subprocess.Popen(['xsel', '--clipboard', '--input'], stdin=subprocess.PIPE)
                p.communicate(input=text.encode('utf-8'))
                return "Copied to clipboard."
            except Exception as e:
                return f"Could not copy to clipboard: {e}"

    @classmethod
    def get_daily_tasks(cls, day: str = "today") -> str:
        """
        Retrieves scheduled daily study tasks for Dex.
        Monday: Physics, Tuesday: Chemistry, Wednesday: Mathematics,
        Thursday: Physics, Friday: Chemistry, Saturday: Mathematics,
        Sunday: Half Rest & Computer Science (CS).
        """
        day_clean = (day or "today").strip().lower()
        now = datetime.now()

        if day_clean in ["today", "aaj", "current"]:
            weekday_name = now.strftime("%A")
            task = WEEKLY_STUDY_SCHEDULE.get(weekday_name.lower(), "Study Session")
            return f"Dex, today is {weekday_name}. Your scheduled task is {task}."

        if day_clean in ["tomorrow", "kal", "next"]:
            target_dt = now + timedelta(days=1)
            weekday_name = target_dt.strftime("%A")
            task = WEEKLY_STUDY_SCHEDULE.get(weekday_name.lower(), "Study Session")
            return f"Dex, tomorrow is {weekday_name}. Your scheduled task is {task}."

        if day_clean in ["yesterday"]:
            target_dt = now - timedelta(days=1)
            weekday_name = target_dt.strftime("%A")
            task = WEEKLY_STUDY_SCHEDULE.get(weekday_name.lower(), "Study Session")
            return f"Dex, yesterday was {weekday_name}. Your scheduled task was {task}."

        if day_clean in ["all", "week", "weekly", "schedule", "timetable", "full", "each day", "days", "each"]:
            return "Dex, here is your weekly schedule: Mon Physics, Tue Chem, Wed Maths, Thu Physics, Fri Chem, Sat Maths, Sun Half Rest & CS."

        for d, task in WEEKLY_STUDY_SCHEDULE.items():
            if d in day_clean:
                return f"Dex, on {d.capitalize()} your scheduled task is {task}."

        weekday_name = now.strftime("%A")
        task = WEEKLY_STUDY_SCHEDULE.get(weekday_name.lower(), "Study Session")
        return f"Dex, today is {weekday_name}. Your scheduled task is {task}."

    @classmethod
    def execute_direct_command(cls, query: str) -> str | None:
        """
        Fast-path deterministic direct execution for explicit system, app, and music commands.
        Ensures instantaneous sub-second execution without waiting on external LLM services.
        """
        if not query:
            return None
        low = query.strip().lower()

        # 1. Play music / song
        m_play = re.match(r'^(?:play\s+some\s+music(?:\s+on\s+spotify)?|play\s+music(?:\s+on\s+spotify)?|play\s+songs?)$', low)
        if m_play:
            return cls.execute_tool("browser_action", {"action": "play_music", "song": "top hits", "platform": "spotify"})

        m_play_song = re.match(r'^(?:play\s+(?:the\s+song\s+)?)(.+?)(?:\s+on\s+(spotify|youtube))?$', low)
        if m_play_song and not low.startswith("play game"):
            song = m_play_song.group(1).strip()
            plat = m_play_song.group(2) or "spotify"
            return cls.execute_tool("browser_action", {"action": "play_music", "song": song, "platform": plat})

        # 2. System volume & menu
        if re.search(r'\b(?:volume\s+up|louder|increase\s+volume)\b', low):
            return cls.execute_tool("system_action", {"action": "volume", "command": "up"})
        if re.search(r'\b(?:volume\s+down|quieter|decrease\s+volume|lower\s+volume)\b', low):
            return cls.execute_tool("system_action", {"action": "volume", "command": "down"})
        if re.search(r'\b(?:mute(?:\s+audio|\s+system|\s+volume)?)\b', low):
            return cls.execute_tool("system_action", {"action": "volume", "command": "mute"})
        if re.search(r'\b(?:unmute(?:\s+audio|\s+system|\s+volume)?)\b', low):
            return cls.execute_tool("system_action", {"action": "volume", "command": "unmute"})
        if re.search(r'\b(?:open\s+(?:system\s+|app\s+|start\s+)?menu|show\s+(?:system\s+|app\s+|start\s+)?menu)\b', low):
            return cls.execute_tool("system_action", {"action": "open_menu"})
        if re.search(r'\b(?:lock\s+(?:screen|pc|computer|session))\b', low):
            return cls.execute_tool("system_action", {"action": "lock_screen"})

        # 3. Media control (play, pause, resume, toggle, skip)
        if re.search(r'\b(?:pause|stop|halt)\s+(?:the\s+|this\s+|current\s+)?(?:music|song|track|playback|audio|video|gaana|gana)\b', low) or (
            low in ["pause", "pause music", "stop music", "pause song", "stop song", "pause playback", "stop playback", "gaana roko", "gaana pause karo", "gaana band karo", "music roko"]
        ):
            return cls.execute_tool("pause_music", {})

        if re.search(r'\b(?:resume|unpause|continue)\s+(?:the\s+|this\s+|current\s+)?(?:music|song|track|playback|audio|video|gaana|gana)\b', low) or (
            low in ["resume", "unpause", "resume music", "resume song", "resume playback", "unpause music", "unpause song", "gaana chalao", "gaana resume karo"]
        ):
            return cls.execute_tool("resume_music", {})

        if re.search(r'\b(?:play\s+and\s+pause|play\s+or\s+pause|toggle)\s+(?:the\s+)?(?:music|song|playback)\b', low) or low in ["play pause", "toggle music", "toggle playback"]:
            return cls.execute_tool("control_music", {"action": "toggle"})

        if re.search(r'\b(?:next|skip|agla)\s+(?:the\s+)?(?:song|track|music|gaana)\b', low) or low in ["next", "skip", "next song", "next track", "skip song", "agla gaana"]:
            return cls.execute_tool("control_music", {"action": "next"})

        if re.search(r'\b(?:previous|prev|pichhla)\s+(?:the\s+)?(?:song|track|music|gaana)\b', low) or low in ["prev", "previous", "previous song", "previous track", "pichhla gaana"]:
            return cls.execute_tool("control_music", {"action": "previous"})

        # 4. Gmail
        if re.search(r'\b(?:open\s+gmail|check\s+gmail|view\s+gmail)\b', low):
            return cls.execute_tool("manage_gmail", {"action": "inbox"})
        if re.search(r'\b(?:unread\s+emails?|check\s+unread\s+emails?)\b', low):
            return cls.execute_tool("manage_gmail", {"action": "unread"})

        # 5. Direct Open App
        m_app = re.match(r'^(?:open|launch|start)\s+(?:the\s+)?([a-zA-Z0-9_\-\.\s]+)$', low)
        if m_app:
            target = m_app.group(1).strip()
            if target in ["spotify", "web", "whatsapp", "chrome", "firefox", "discord", "telegram", "terminal", "code", "calculator", "files", "settings"]:
                return cls.execute_tool("open_app", {"app_name": target})

        # 6. System Audit & RAM Cleanup
        if re.search(
            r'\b(?:audit\s+(?:the\s+|my\s+|off\s+my\s+)?(?:system|pc|computer|ram|memory)|'
            r'clean\s+(?:the\s+|my\s+)?(?:ram|memory|system)|'
            r'free\s+(?:the\s+|my\s+|up\s+)?(?:ram|memory)|'
            r'clear\s+(?:the\s+|my\s+)?(?:ram|memory)|'
            r'optimize\s+(?:the\s+|my\s+)?(?:ram|memory|system)|'
            r'stop\s+(?:things|processes|apps|stuff)?\s*(?:which\s+are\s+)?(?:unnecessary|unneeded)?\s*(?:and\s+)?(?:eating\s+up\s+(?:the\s+)?ram|eating\s+ram)?|'
            r'system\s+audit|audit\s+pc|audit\s+ram|clean\s+ram|free\s+ram|optimize\s+ram)\b',
            low
        ) or low in ["audit", "system audit", "clean ram", "free ram", "optimize ram", "ram audit", "pc audit"]:
            return cls.execute_tool("audit_system", {"cleanup": True})

        # 7. Direct DM / Texting a Person & Opening Particular Chat
        m_dm_a = re.match(r'^(?:send\s+(?:a\s+)?(?:message|dm|text)\s+to\s+|dm\s+|text\s+|message\s+)(@?[a-zA-Z0-9_\-\+]+)\s+(?:on|via|in)\s+(telegram|whatsapp|discord|instagram|slack|twitter|signal)\s*(?:saying\s+|that\s+|:\s*)?(.+)$', low)
        if m_dm_a:
            recip = m_dm_a.group(1).strip()
            plat = m_dm_a.group(2).strip().lower()
            text_msg = m_dm_a.group(3).strip()
            return cls.execute_tool("send_dm", {"recipient": recip, "platform": plat, "message": text_msg, "press_enter": True})

        m_dm_b = re.match(r'^(?:on\s+)?(telegram|whatsapp|discord|instagram|slack|twitter|signal)\s+(?:(?:dm|text|message|chat|send\s+message\s+to)(?:\s+(?:with|to))?\s+)?(@?[a-zA-Z0-9_\-\+]+)\s*(?:saying\s+|that\s+|:\s*)(.+)$', low)
        if m_dm_b and not low.startswith("whatsapp web"):
            plat = m_dm_b.group(1).strip().lower()
            recip = m_dm_b.group(2).strip()
            text_msg = m_dm_b.group(3).strip()
            return cls.execute_tool("send_dm", {"recipient": recip, "platform": plat, "message": text_msg, "press_enter": True})

        m_dm_c = re.match(r'^(?:open|show)\s+(?:the\s+)?(?:chat|dm|conversation)\s+(?:with|of|for)\s+(@?[a-zA-Z0-9_\-\+]+)(?:\s+(?:on|in|via)\s+(telegram|whatsapp|discord|instagram|slack|twitter|signal))?$', low)
        if m_dm_c:
            recip = m_dm_c.group(1).strip()
            plat = (m_dm_c.group(2) or "active").strip().lower()
            return cls.execute_tool("send_dm", {"recipient": recip, "platform": plat, "message": "", "press_enter": False})

        # 8. Instagram Direct Chat & Search from username
        m_ig_1 = re.match(
            r'^(?:(?:search\s+(?:for\s+)?(?:and\s+)?open\s+(?:a\s+)?(?:chat|dm|conversation)\s+(?:on|in)\s+instagram\s+(?:from\s+username\s+|with\s+|for\s+)?|'
            r'open\s+(?:a\s+)?(?:chat|dm|conversation)\s+(?:on|in)\s+instagram\s+(?:from\s+username\s+|with\s+|for\s+)?|'
            r'open\s+instagram\s+(?:chat|dm|conversation)\s+(?:from\s+username\s+|with\s+|for\s+)?|'
            r'instagram\s+chat\s+(?:with\s+)?))(@?[a-zA-Z0-9_\.\-]+)(?:\s*(?:saying\s+|that\s+|:\s*)(.+))?$',
            low
        )
        if m_ig_1:
            u = m_ig_1.group(1).strip()
            msg = (m_ig_1.group(2) or "").strip()
            return cls.execute_tool("open_instagram_chat", {"username": u, "message": msg})

        m_ig_2 = re.match(r'^(?:search\s+(?:for\s+)?)(@?[a-zA-Z0-9_\.\-]+)\s+on\s+instagram(?:\s+and\s+open\s+(?:a\s+)?chat)?$', low)
        if m_ig_2:
            u = m_ig_2.group(1).strip()
            return cls.execute_tool("open_instagram_chat", {"username": u, "message": ""})

        # 8b. Smart Site & Web Shortcuts (from dex-bot actions.py)
        COMMON_SITES = {
            "youtube": "https://www.youtube.com",
            "github": "https://github.com",
            "reddit": "https://reddit.com",
            "twitter": "https://x.com",
            "chatgpt": "https://chatgpt.com",
            "claude": "https://claude.ai",
            "gemini": "https://gemini.google.com",
            "wikipedia": "https://wikipedia.org",
            "stackoverflow": "https://stackoverflow.com",
            "netflix": "https://www.netflix.com",
            "maps": "https://maps.google.com",
            "news": "https://news.google.com",
            "hackernews": "https://news.ycombinator.com",
        }
        m_site = re.match(r'^(?:open|go\s+to|visit)\s+(?:the\s+)?(youtube|github|reddit|twitter|chatgpt|claude|gemini|wikipedia|stackoverflow|netflix|maps|news|hackernews)(?:\s+(.+))?$', low)
        if m_site:
            site = m_site.group(1).lower()
            sub = (m_site.group(2) or "").strip()
            if sub:
                enc = urllib.parse.quote_plus(sub)
                if site == "youtube":
                    url = f"https://www.youtube.com/results?search_query={enc}"
                elif site == "github":
                    url = f"https://github.com/search?q={enc}"
                elif site == "reddit":
                    url = f"https://reddit.com/r/{sub.lstrip('r/')}" if sub.startswith("r/") else f"https://reddit.com/search/?q={enc}"
                elif site == "stackoverflow":
                    url = f"https://stackoverflow.com/search?q={enc}"
                elif site == "wikipedia":
                    url = f"https://en.wikipedia.org/wiki/Special:Search?search={enc}"
                else:
                    url = f"{COMMON_SITES[site]}/search?q={enc}"
                return cls.execute_tool("open_url", {"url": url})
            else:
                return cls.execute_tool("open_url", {"url": COMMON_SITES[site]})

        # 9. Daily Tasks & Weekly Study Schedule
        m_task_day = re.search(
            r'\b(?:what\s+is\s+(?:my\s+|the\s+)?task\s+(?:for\s+)?|task\s+(?:for\s+)?|tasks?\s+(?:for\s+|of\s+)?)(today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
            low
        )
        if m_task_day:
            return cls.execute_tool("get_daily_tasks", {"day": m_task_day.group(1)})

        if re.search(
            r'\b(?:what\s+(?:is\s+)?(?:my\s+)?(?:study\s+)?tasks?\s+today|'
            r'what\s+(?:should|do)\s+i\s+(?:study|do)\s+today|'
            r'today(?:\'s)?\s+(?:task|study|schedule|subject)|'
            r'aaj\s+(?:kya\s+padhna\s+hai|ka\s+task|ka\s+schedule)|'
            r'what\s+is\s+today(?:\'s)?\s+task)\b',
            low
        ) or low in ["tasks today", "today task", "task today", "what to study today"]:
            return cls.execute_tool("get_daily_tasks", {"day": "today"})

        if re.search(
            r'\b(?:what\s+(?:is\s+)?(?:my\s+)?(?:study\s+)?tasks?\s+tomorrow|'
            r'what\s+(?:should|do)\s+i\s+(?:study|do)\s+tomorrow|'
            r'tomorrow(?:\'s)?\s+(?:task|study|schedule|subject)|'
            r'kal\s+(?:kya\s+padhna\s+hai|kal\s+ka\s+task|kal\s+ka\s+schedule)|'
            r'what\s+is\s+tomorrow(?:\'s)?\s+task)\b',
            low
        ) or low in ["tasks tomorrow", "tomorrow task", "task tomorrow", "what to study tomorrow"]:
            return cls.execute_tool("get_daily_tasks", {"day": "tomorrow"})

        if re.search(
            r'\b(?:tasks?\s+for\s+each\s+day|'
            r'tasks?\s+for\s+all\s+days|'
            r'weekly\s+(?:study\s+)?(?:schedule|tasks?|timetable|plan)|'
            r'study\s+(?:schedule|timetable|plan)|'
            r'show\s+(?:my\s+)?(?:study\s+)?(?:schedule|timetable|tasks)|'
            r'daily\s+tasks|routine\s+tasks|all\s+tasks|'
            r'full\s+schedule)\b',
            low
        ) or low in ["schedule", "study schedule", "timetable", "weekly schedule", "daily tasks", "tasks for each day"]:
            return cls.execute_tool("get_daily_tasks", {"day": "all"})


        # 10. manage_notes
        m_add_note = re.match(r'^add\s+note\s+(.+)$', low)
        if m_add_note:
            return cls.execute_tool("manage_notes", {"action": "add", "content": m_add_note.group(1).strip()})
        if low in ["show notes", "list notes"]:
            return cls.execute_tool("manage_notes", {"action": "list"})
        if low == "clear notes":
            return cls.execute_tool("manage_notes", {"action": "clear"})
        m_rem_note = re.match(r'^remove\s+note\s+(\d+)$', low)
        if m_rem_note:
            return cls.execute_tool("manage_notes", {"action": "remove", "content": m_rem_note.group(1).strip()})

        # 11. set_timer
        m_timer_1 = re.match(r'^set\s+timer\s+(?:for\s+)?(\d+)\s*(minutes?|mins?|m|seconds?|secs?|s|hours?|hrs?|h)$', low)
        if m_timer_1:
            val = int(m_timer_1.group(1))
            unit = m_timer_1.group(2)
            if unit.startswith('h'): val *= 3600
            elif unit.startswith('m'): val *= 60
            return cls.execute_tool("set_timer", {"duration_seconds": val, "message": "Timer is up!"})
            
        m_timer_2 = re.match(r'^remind\s+me\s+in\s+(\d+)\s*(minutes?|mins?|m|seconds?|secs?|s|hours?|hrs?|h)\s+to\s+(.+)$', low)
        if m_timer_2:
            val = int(m_timer_2.group(1))
            unit = m_timer_2.group(2)
            msg = m_timer_2.group(3)
            if unit.startswith('h'): val *= 3600
            elif unit.startswith('m'): val *= 60
            return cls.execute_tool("set_timer", {"duration_seconds": val, "message": msg})
            
        m_timer_3 = re.match(r'^timer\s+(\d+)\s*(minutes?|mins?|m|seconds?|secs?|s|hours?|hrs?|h)$', low)
        if m_timer_3:
            val = int(m_timer_3.group(1))
            unit = m_timer_3.group(2)
            if unit.startswith('h'): val *= 3600
            elif unit.startswith('m'): val *= 60
            return cls.execute_tool("set_timer", {"duration_seconds": val, "message": "Timer is up!"})

        # 12. calculate
        m_calc_1 = re.match(r'^calculate\s+(.+)$', low)
        if m_calc_1:
            return cls.execute_tool("calculate", {"expression": m_calc_1.group(1).strip()})
        m_calc_2 = re.match(r'^what\s+is\s+([\d\.\+\-\*/\(\) ]+)$', low)
        if m_calc_2:
            return cls.execute_tool("calculate", {"expression": m_calc_2.group(1).strip()})
        m_calc_3 = re.match(r'^(\d+)\s+times\s+(\d+)$', low)
        if m_calc_3:
            return cls.execute_tool("calculate", {"expression": f"{m_calc_3.group(1)} * {m_calc_3.group(2)}"})
        m_calc_4 = re.match(r'^(\d+)\s+percent\s+of\s+(\d+)$', low)
        if m_calc_4:
            return cls.execute_tool("calculate", {"expression": f"({m_calc_4.group(1)} / 100) * {m_calc_4.group(2)}"})
        m_calc_5 = re.match(r'^math\s+(.+)$', low)
        if m_calc_5:
            return cls.execute_tool("calculate", {"expression": m_calc_5.group(1).strip()})

        # 13. get_weather
        if low in ["weather", "what is the weather", "mausam", "mausam kaisa hai"]:
            return cls.execute_tool("get_weather", {"city": "auto"})
        m_wea = re.match(r'^(?:weather\s+in|how\s+is\s+the\s+weather\s+in)\s+(.+)$', low)
        if m_wea:
            return cls.execute_tool("get_weather", {"city": m_wea.group(1).strip()})

        # 14. copy_to_clipboard
        if low in ["copy that", "copy last response", "clipboard copy"]:
            return cls.execute_tool("copy_to_clipboard", {"text": cls._last_response})

        return None


# ─────────────────────────────────────────────────────────────
# Callable Functions for Gemini & Python AFC
# ─────────────────────────────────────────────────────────────
def open_app(app_name: str, force_new_instance: bool = False) -> str:
    """Open or focus a desktop application. If the application is already running, brings it to focus and asks before opening a second instance to prevent duplicate apps."""
    return ToolExecutor.execute_tool("open_app", {"app_name": app_name, "force_new_instance": force_new_instance})


def play_music(song: str = "", platform: str = "spotify", action: str = "play") -> str:
    """Plays music or a song in the browser or desktop app (Spotify Web default, YouTube). If no song is specified, resumes or unpauses current music playback."""
    return ToolExecutor.execute_tool("play_music", {"song": song, "platform": platform, "action": action})


def pause_music() -> str:
    """Pauses or stops currently playing music, song, or media playback across Spotify, YouTube, browser, and media players."""
    return ToolExecutor.execute_tool("pause_music", {})


def resume_music() -> str:
    """Resumes or unpauses music playback in Spotify, YouTube, browser, or desktop media player."""
    return ToolExecutor.execute_tool("resume_music", {})


def control_music(action: str = "play_pause") -> str:
    """Controls music and media playback: play, pause, resume, toggle, skip next song, or previous track across Spotify, YouTube, browser, and desktop players."""
    return ToolExecutor.execute_tool("control_music", {"action": action})


def open_url(url: str, force_new_tab: bool = False) -> str:
    """Opens a web URL. Reuses an existing tab or window if that website is already open to prevent duplicate tabs."""
    return ToolExecutor.execute_tool("open_url", {"url": url, "force_new_tab": force_new_tab})


def compose_message(service: str, recipient: str = "", subject: str = "", message: str = "") -> str:
    """Composes or types a message in a web inbox or chat app (Gmail, WhatsApp, Outlook). Reuses existing tabs."""
    return ToolExecutor.execute_tool("compose_message", {"service": service, "recipient": recipient, "subject": subject, "message": message})


def type_text(text: str, press_enter: bool = False) -> str:
    """Types text directly into the currently active window or input box."""
    return ToolExecutor.execute_tool("type_text", {"text": text, "press_enter": press_enter})


def search_web(query: str) -> str:
    """Searches the web for real-time information, answers, news, weather, or facts."""
    return ToolExecutor.execute_tool("search_web", {"query": query})


def manage_persona(action: str = "list", name: str = "", prompt: str = "", voice: str = "", accent_color: str = "cyan") -> str:
    """Switch AI persona (JARVIS, Friday, Edith, Hindi Mitra, or custom), add custom persona, or list personas."""
    return ToolExecutor.execute_tool("manage_persona", {"action": action, "name": name, "prompt": prompt, "voice": voice, "accent_color": accent_color})


def manage_memory(action: str = "list", content: str = "") -> str:
    """Store or recall memories, facts, notes, and session details for Dex. Supports permanent memories (/rem) and 7-day session memories."""
    return ToolExecutor.execute_tool("manage_memory", {"action": action, "content": content})


def browser_action(action: str, url: str = "", song: str = "", platform: str = "spotify", query: str = "", command: str = "") -> str:
    """Interact with the browser: play music/songs (Spotify default), control media playback, navigate with tab reuse, search web, or scroll."""
    return ToolExecutor.execute_tool("browser_action", {"action": action, "url": url, "song": song, "platform": platform, "query": query, "command": command})


def system_action(action: str, command: str = "", app_name: str = "", volume_level: int = None) -> str:
    """Interact with the desktop system: open the application/start menu, adjust volume (up/down/mute), control media playback, lock screen, open settings."""
    return ToolExecutor.execute_tool("system_action", {"action": action, "command": command, "app_name": app_name, "volume_level": volume_level})


def manage_gmail(action: str = "inbox", query: str = "", to: str = "", subject: str = "", message: str = "") -> str:
    """Manage Gmail: open inbox, view unread emails, compose new emails, or search emails with smart tab reuse."""
    return ToolExecutor.execute_tool("manage_gmail", {"action": action, "query": query, "to": to, "subject": subject, "message": message})


def send_dm(message: str, platform: str = "active", recipient: str = "", press_enter: bool = True) -> str:
    """Type and send a message directly into an active DM or chat in web tabs or desktop apps (Discord, Telegram, WhatsApp Web, Slack, Signal, Instagram, Twitter/X)."""
    return ToolExecutor.execute_tool("send_dm", {"message": message, "platform": platform, "recipient": recipient, "press_enter": press_enter})


def audit_system(cleanup: bool = True) -> str:
    """Runs a full audit of system RAM, swap, and processes. Identifies and stops unnecessary background daemons to free up RAM."""
    return ToolExecutor.execute_tool("audit_system", {"cleanup": cleanup})


def open_instagram_chat(username: str, message: str = "") -> str:
    """Searches for an Instagram user by their username (e.g. '@username' or 'username') and opens their direct message chat conversation in the browser with tab reuse. Optionally types and sends a message."""
    return ToolExecutor.execute_tool("open_instagram_chat", {"username": username, "message": message})


def get_daily_tasks(day: str = "today") -> str:
    """Get Dex's scheduled daily study task or subject for today, tomorrow, a specific weekday, or the full weekly schedule."""
    return ToolExecutor.execute_tool("get_daily_tasks", {"day": day})


def manage_notes(action: str, content: str = "") -> str:
    """Manage quick notes and to-dos for Dex."""
    return ToolExecutor.execute_tool("manage_notes", {"action": action, "content": content})

def set_timer(duration_seconds: int, message: str) -> str:
    """Set a timer or reminder."""
    return ToolExecutor.execute_tool("set_timer", {"duration_seconds": duration_seconds, "message": message})

def calculate(expression: str) -> str:
    """Perform mathematical calculations."""
    return ToolExecutor.execute_tool("calculate", {"expression": expression})

def get_weather(city: str = "auto") -> str:
    """Get current weather for a city."""
    return ToolExecutor.execute_tool("get_weather", {"city": city})

def copy_to_clipboard(text: str) -> str:
    """Copy text to clipboard."""
    return ToolExecutor.execute_tool("copy_to_clipboard", {"text": text})

GEMINI_TOOLS = [
    open_app, play_music, pause_music, resume_music, control_music,
    open_url, compose_message, type_text, search_web,
    manage_persona, manage_memory, browser_action, system_action,
    manage_gmail, send_dm, audit_system, open_instagram_chat, get_daily_tasks,
    manage_notes, set_timer, calculate, get_weather, copy_to_clipboard
]


