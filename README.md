# ⚡ D . E . X . O . R . T . O   A I

<div align="center">

![Dexorto AI Logo](assets/icon.png)

**A Minimalist Cyberpunk Desktop AI Voice Companion & Autonomous System Assistant**

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-00D2FF?style=for-the-badge)](LICENSE)
[![Pygame](https://img.shields.io/badge/UI-Pygame%202.5%2B-FFD43B?style=for-the-badge&logo=pygame&logoColor=black)](https://www.pygame.org/)
[![Google Gemini](https://img.shields.io/badge/LLM-Google%20Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://aistudio.google.com/)
[![Groq](https://img.shields.io/badge/Inference-Groq%20Cloud-F55036?style=for-the-badge)](https://groq.com/)
[![Edge TTS](https://img.shields.io/badge/Voice-Microsoft%20Edge%20TTS-0078D4?style=for-the-badge&logo=microsoft&logoColor=white)](https://github.com/rany2/edge-tts)

</div>

---

## 🌌 Overview

**Dexorto AI** is an advanced, ultra-responsive desktop AI companion engineered for Linux power users. Featuring a dark slate-gray and Stark-cyan cyberpunk HUD inspired by Iron Man's JARVIS, Dexorto pairs high-performance continuous wake-word acoustic listening with a multi-provider fallback brain (Google Gemini, Groq, OpenRouter), local hardware telemetry, system optimization tools, and natural bilingual fluency (English & Hindi).

---

## ✨ Key Features

- **🎙 Continuous Wake Word Engine**: Instant activation via *"Dexorto"* phonetics without false triggers or audio crackles.
- **⚡ Cyberpunk Minimal Gray HUD**:
  - **Concentric Arc Core Reactor**: Rotational tick marks, aperture iris, and real-time horizontal soundwave equalizer visualizer.
  - **Live Hardware Telemetry**: CPU percentage, memory allocation, storage capacity, and system uptime counters.
  - **Asynchronous Weather Station**: Live temperature, weather conditions, humidity, and wind telemetry fetched non-blockingly.
  - **Quick Protocols & App Deck**: 1-click launchers for Notes, Calculator, Weather, System RAM optimizer, Spotify, Instagram, and Hindi Tutor.
  - **Interactive Conversation Feed**: Styled message bubbles, custom scrollbar, and text input box with clipboard shortcuts (`Ctrl+Backspace` word delete, `Ctrl+V` paste).
- **🧠 Multi-Provider AI Brain**:
  - Primary: Google Gemini 3.1 Flash-Lite (low latency streaming).
  - Fallbacks: Groq Cloud (ultra-fast open models) & OpenRouter (`:free` tier).
- **🛠 Native Tool Integration**:
  - Application launcher & process focus management.
  - Web search & YouTube / Spotify playback controls.
  - Instagram chat opener (`instagram.com/<username>/?hl=en`).
  - Persistent Note / Todo manager (`notes.json`).
  - Safe mathematical expression evaluator.
  - Memory & retention system (`memory.json`).
  - System RAM cleaner and background daemon auditor.
  - Model Context Protocol (MCP) JSON-RPC 2.0 server.
- **🗣 Multi-Persona Neural Speech**:
  - High-fidelity natural neural TTS voices (Aria US, Prabhat/Neerja Indian English, Madhur/Swara Hindi, Ryan British).
  - Barge-in support (interrupt AI speech naturally with wake word).
- **🌐 Bilingual & Hindi Tutor**:
  - Native comprehension of English, Hindi, and Hinglish.
  - Interactive Hindi language tutoring module.

---

## 📁 Repository Structure

```text
dexorto-ai/
├── assets/                  # Icons and avatar visual assets
│   ├── icon.png             # Application logo
│   └── stickers/            # Robot and waifu status avatars
├── assistant_tools.py       # Comprehensive tool execution engine & MCP handlers
├── browser_controller.py    # Chromium / Firefox browser controller & tab recycling
├── calibrate.py             # Audio, microphone & latency calibration suite
├── calibrate.sh             # Calibration launcher script
├── clean_ram.sh             # RAM optimizer & page-cache sync script
├── config.py                # Centralized configuration & environment loader
├── dexorto_mcp_server.py    # Model Context Protocol (MCP) JSON-RPC 2.0 server
├── jarvis.py                # Background voice daemon & CLI assistant
├── jarvis_inir_widget.py    # Primary Cyberpunk Desktop Companion HUD (Pygame)
├── jarvis_ipc.py            # Local IPC communication protocol
├── jarvis_widget.py         # Companion widget mirror
├── launch_dexorto.sh        # Master desktop launcher
├── memory.json              # Long-term memory storage template
├── notes.json               # Notes & Todo list storage template
├── personas.json            # AI persona configuration profiles
├── requirements.txt         # Python package dependencies
├── run_widget.sh            # Lightweight widget runner
├── test_voice.sh            # Neural speech diagnostic script
├── .env.example             # Environment credentials template
├── .gitignore               # Git exclusions
├── LICENSE                  # MIT License
└── README.md                # Project documentation
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites

On Ubuntu / Debian / Mint / Lubuntu:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv portaudio19-dev libasound2-dev xclip
```

### 2. Clone Repository

```bash
git clone https://github.com/Dexorto1/dexorto-ai.git
cd dexorto-ai
```

### 3. Setup Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure API Keys

Copy the sample environment file and provide your free keys:

```bash
cp .env.example .env
```

Edit `.env`:
```ini
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here
TAVILY_API_KEY=your_tavily_api_key_here
OPENROUTER_API_KEY=your_openrouter_api_key_here
```

> **Note**: Free keys can be acquired at:
> - Google Gemini: [Google AI Studio](https://aistudio.google.com/apikey)
> - Groq Cloud: [Groq Console](https://console.groq.com/keys)
> - OpenRouter: [OpenRouter Keys](https://openrouter.ai/keys)
> - Tavily Search: [Tavily Dashboard](https://app.tavily.com/home)

---

## 🎮 Launching Dexorto AI

### Complete Desktop HUD Mode
Starts the Pygame companion with continuous voice recognition:
```bash
./launch_dexorto.sh
# Or directly:
python3 jarvis_inir_widget.py
```

### Terminal Voice CLI Mode
```bash
python3 jarvis.py
```

### Pure Text Terminal Mode
```bash
python3 jarvis.py --text
```

### Hardware & Mic Calibration
```bash
./calibrate.sh
```

---

## ⌨️ Desktop HUD Shortcuts & Controls

| Shortcut / Action | Function |
|-------------------|----------|
| **Say "Dexorto"** | Trigger wake word and initiate voice command mode |
| **Enter** | Send message typed into conversation box |
| **Ctrl + Backspace** | Delete preceding word in message input |
| **Ctrl + V** | Paste clipboard text into conversation box |
| **F11** | Toggle Fullscreen / Windowed companion view |
| **Esc** | Clear message input / cancel speech |
| **[ ⚡ ] Button** | Trigger System RAM audit & cache optimization |
| **[ 🎙 ] Button** | Toggle Microphone Listening state |
| **[ ⏹ ] Button** | Stop ongoing AI speech output |
| **[ 🗑 Clear ]** | Clear conversation feed |
| **[ 📋 Extract ]** | Copy conversation transcript to system clipboard |

---

## 🗣 Example Voice & Text Commands

- *"Dexorto, open Firefox"*
- *"Dexorto, play Interstellar soundtrack on Spotify"*
- *"Dexorto, what is 385 multiplied by 42?"*
- *"Dexorto, what's the weather in Vadodara?"*
- *"Dexorto, add note buy new mechanical keyboard"*
- *"Dexorto, show my notes"*
- *"Dexorto, what is my schedule today?"*
- *"Dexorto, optimize system RAM"*
- *"Dexorto, gaana bajao"* (Bilingual Hindi command)
- *"Dexorto, teach me Hindi greetings"*

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
