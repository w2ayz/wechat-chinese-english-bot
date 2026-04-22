# WeChat Chinese–English Bot v1.1

A real-time Chinese↔English translation bot for WeChat, built on the [Openclaw](https://openclaw.ai) AI agent platform. All translation happens at the plugin layer — messages are intercepted before reaching the agent, translated, and delivered back as both a text bubble and a downloadable MP3 audio file.

---

## Features

- `/ce on` / `/ce off` — toggle translation mode from within WeChat
- Automatic language detection — Chinese → English, English → Chinese
- Text messages: translated and replied inline
- Voice messages: transcribed by Whisper, translated by Ollama, synthesised by Edge TTS, delivered as MP3 file
- Runs entirely on-device (no cloud API keys required beyond Edge TTS)

---

## Architecture

```
WeChat user
    │
    ▼
Openclaw gateway  (openclaw-weixin plugin v2.1.9)
    │
    ├── /CE commands ──► update ~/.openclaw/memory/wechat_ce_mode.json
    │                    reply "CE mode ON/OFF" immediately
    │
    └── CE mode active?
            │
            ├── Text message
            │       └── ce-handler.py --text "..."
            │               ├── detect_language()  (CJK codepoint scan)
            │               ├── translate()        (Ollama HTTP API)
            │               └── tts_edge()         (Edge TTS → MP3)
            │
            └── Voice message
                    └── ce-handler.py --file /path/to/audio
                            ├── transcribe_audio() (Whisper turbo)
                            ├── detect_language()
                            ├── translate()        (Ollama HTTP API)
                            └── tts_edge()         (Edge TTS → MP3)
```

**Translation pipeline by input type:**

| Step | Text message | Voice (WeChat STT) | Voice (no STT) |
|------|-------------|--------------------|----------------|
| 1. Transcribe | — | Use WeChat transcript | Whisper turbo |
| 2. Detect language | CJK scan | CJK scan | CJK scan |
| 3. Translate | Ollama (qwen2.5:7b) | Ollama (qwen2.5:7b) | Ollama (qwen2.5:7b) |
| 4. Synthesise | Edge TTS → MP3 | Edge TTS → MP3 | Edge TTS → MP3 |
| 5. Deliver text | WeChat text bubble | WeChat text bubble | WeChat text bubble |
| 6. Deliver audio | MP3 file attachment | MP3 file attachment | MP3 file attachment |

**Voice selection:**

| Source | Target | Edge TTS voice |
|--------|--------|----------------|
| Chinese | English | `en-US-AriaNeural` |
| English | Chinese | `zh-CN-XiaoxiaoNeural` |

---

## Prerequisites

| Dependency | Install |
|------------|---------|
| [Openclaw](https://openclaw.ai) | Platform requirement |
| Openclaw-weixin plugin v2.1.9+ | Bundled with Openclaw WeChat channel |
| [Ollama](https://ollama.ai) | `brew install ollama` |
| qwen2.5:7b-instruct model | `ollama pull qwen2.5:7b-instruct` |
| [Whisper](https://github.com/openai/whisper) | `pip install openai-whisper` |
| Node.js 18+ | `brew install node` |
| node-edge-tts | `npm install node-edge-tts commander` |
| Python 3.11+ | `brew install python` |

---

## File Structure

```
openclaw-wechat-ce/
├── README.md
├── SKILL.md                        # Openclaw skill descriptor
└── scripts/
    ├── ce-handler.py               # Main pipeline: Whisper → Ollama → Edge TTS
    └── mode.py                     # Read/set CE mode from the command line

# Separate skill (sibling directory):
edge-tts/
└── scripts/
    └── tts-converter.js            # Edge TTS Node.js wrapper
```

The plugin patch lives in the Openclaw-weixin extension:
```
extensions/openclaw-weixin/src/messaging/
├── process-message.ts              # CE intercept + command handling (patched)
├── send-media.ts                   # Audio routed as MP3 file attachment
└── send.ts                         # sendVoiceMessageWeixin (reserved for future use)
```

---

## Installation

### 1. Install dependencies

```bash
# Ollama + model
brew install ollama
ollama serve &
ollama pull qwen2.5:7b-instruct

# Whisper
pip install openai-whisper

# Edge TTS Node wrapper (inside the edge-tts skill directory)
cd ~/.openclaw/workspace/skills/edge-tts/scripts
npm install node-edge-tts commander
```

### 2. Place skill files

Copy this repository into your Openclaw skills directory:

```bash
cp -r openclaw-wechat-ce ~/.openclaw/workspace/skills/
```

### 3. Patch the openclaw-weixin plugin

The CE intercept requires changes to `process-message.ts` inside the openclaw-weixin extension. A pre-patched reference file and a one-command patch script are included:

```bash
bash ~/.openclaw/workspace/skills/openclaw-wechat-ce/patch.sh
```

This copies `process-message.patched.ts` over the stock plugin file and backs up the original.

#### ⚠️ Auto-update problem

Openclaw automatically updates the `openclaw-weixin` plugin from npm. Each update downloads a fresh copy of the extension and **overwrites `process-message.ts`**, removing all CE patches.

**How to detect this has happened:**
```bash
bash ~/.openclaw/workspace/skills/openclaw-wechat-ce/patch.sh --check
# ❌ CE patches are NOT present — run: bash patch.sh
```

**How to re-apply the patches manually:**
```bash
bash ~/.openclaw/workspace/skills/openclaw-wechat-ce/patch.sh
openclaw gateway --force
```

Run these two commands any time CE translation stops working after an Openclaw update. The `patch.sh --check` command is safe to run at any time and makes no changes.

### 4. Restart the Openclaw gateway

```bash
openclaw gateway --force
```

---

## Usage

In WeChat, chat with your Openclaw bot:

| Command | Effect |
|---------|--------|
| `/ce on` or `ce on` | Enable translation mode |
| `/ce off` or `ce off` | Disable translation mode |
| `/ce` | Toggle (flip current state) |

When CE mode is **on**, every incoming text or voice message is automatically translated and replied to with a text bubble + MP3 audio file.

---

## Configuration

**Change the Ollama model:**
```bash
export OLLAMA_MODEL=llama3.1:8b
```

**Change the Edge TTS script path:**
```bash
export EDGE_TTS_SCRIPT=/path/to/tts-converter.js
```

**Change the temp directory for audio files:**
```bash
export TMP_DIR=/tmp/my-ce-wechat
```

**Check current CE mode from the terminal:**
```bash
python3 ~/.openclaw/workspace/skills/openclaw-wechat-ce/scripts/mode.py
# → on  or  off

python3 ~/.openclaw/workspace/skills/openclaw-wechat-ce/scripts/mode.py off
```

---

## How It Works

CE mode state is stored in `~/.openclaw/memory/wechat_ce_mode.json`:
```json
{"enabled": true}
```

The plugin reads this file **before** downloading voice media, so a `/ce off` command written to disk is guaranteed to be seen by any message that arrives after it — the race window is effectively zero.

---

## Limitations

- Edge TTS requires an internet connection (Microsoft's TTS service)
- Ollama model must be running locally (`ollama serve`)
- Whisper `turbo` model downloads ~800 MB on first run
- Audio is delivered as a file attachment, not a native WeChat voice bubble (WeChat's iLink bot API does not support third-party voice bubble playback in all configurations)
- The `process-message.ts` patch is erased by every Openclaw plugin auto-update — must be manually re-applied with `patch.sh` (see Installation step 3)

---

## License

MIT
