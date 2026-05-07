---
name: openclaw-wechat-ce
description: >
  CE (Chinese↔English) real-time translation for WeChat via Openclaw plugin-level
  intercept. Translation is handled automatically before reaching the agent.
  This skill only manages the CE mode toggle UI responses.
  Do NOT translate messages yourself — the platform handles it.
---

# WeChat CE Skill — Openclaw Implementation Guide

CE (Chinese↔English) translation is handled **automatically at the plugin level** by patching the `openclaw-weixin` npm dist. Messages are intercepted in `process-message.js` (the compiled file the gateway actually loads), routed through the `ce-handler.py` pipeline (Whisper → Ollama → Edge TTS), and delivered back to the user — all before the agent sees the message.

> **v1.3 Architecture Note:** OpenClaw loads the compiled npm dist (`~/.openclaw/npm/node_modules/@tencent-weixin/openclaw-weixin/dist/src/messaging/process-message.js`), NOT the TypeScript extension source at `~/.openclaw/extensions/`. All patches target the JS dist file. The reference file is `process-message.patched.js` (not `.ts`).

---

## CE Mode Commands

The following commands are handled at the plugin level. If for any reason one reaches the agent, respond with the appropriate status:

| Command | Action | Response |
|---------|--------|----------|
| `/ce`, `/CE` | Toggle mode | "✅ CE mode ON — I'll translate every message and voice note." or "⏹ CE mode OFF — normal conversation resumed." |
| `/ce on`, `ce on` | Enable | "✅ CE mode ON — I'll translate every message and voice note." |
| `/ce off`, `ce off` | Disable | "⏹ CE mode OFF — normal conversation resumed." |

**IMPORTANT:** Do NOT translate any incoming messages — the plugin handles all translation. Do NOT output `MEDIA:` directives for audio files.

---

## Implementation Overview

### Plugin patch: `process-message.js` (npm dist)

The CE logic is injected into the compiled npm dist at:
`~/.openclaw/npm/node_modules/@tencent-weixin/openclaw-weixin/dist/src/messaging/process-message.js`

The patch is maintained as `process-message.patched.js` in this skill directory. `patch.sh` applies it by copying this reference file over the npm dist. The code below shows the key additions (the dist is plain ESM JS, not TypeScript):

#### A. Imports (top of file)
```javascript
import os from "node:os";
```

#### B. Helper functions (after `MEDIA_OUTBOUND_TEMP_DIR` constant, before `processOneMessage`)

```javascript
async function _isCEModeOn() {
  const modePath = os.homedir() + "/.openclaw/memory/wechat_ce_mode.json";
  try {
    const { readFile } = await import("node:fs/promises");
    const raw = await readFile(modePath, "utf-8");
    return JSON.parse(raw)?.enabled === true;
  } catch { return false; }
}

function _hasVoiceItem(full) {
  if (!full?.item_list) return false;
  for (const item of full.item_list) { if (item?.voice_item) return true; }
  return false;
}

async function _handleCECommand(text) {
  const t = text.trim().toLowerCase();
  const modePath = os.homedir() + "/.openclaw/memory/wechat_ce_mode.json";
  const { readFile, writeFile, mkdir } = await import("node:fs/promises");
  const readMode = async () => {
    try { return JSON.parse(await readFile(modePath, "utf-8"))?.enabled === true; }
    catch { return false; }
  };
  const writeMode = async (enabled) => {
    await mkdir(os.homedir() + "/.openclaw/memory", { recursive: true });
    await writeFile(modePath, JSON.stringify({ enabled }), "utf-8");
  };
  if (t === "/ce" || t === "ce") {
    const cur = await readMode(); await writeMode(!cur);
    return !cur ? "✅ CE mode ON — I'll translate every message and voice note."
                : "⏹ CE mode OFF — normal conversation resumed.";
  }
  if (t === "/ce on" || t === "ce on" || t === "turn on ce") {
    await writeMode(true);
    return "✅ CE mode ON — I'll translate every message and voice note.";
  }
  if (t === "/ce off" || t === "ce off" || t === "stop ce" || t === "turn off ce") {
    await writeMode(false);
    return "⏹ CE mode OFF — normal conversation resumed.";
  }
  return null;
}
```

#### C. CE command handler (inside `processOneMessage`, before slash command block)

```javascript
const ceReply = await _handleCECommand(textBody);
if (ceReply !== null) {
  const ceTo = full.from_user_id ?? "";
  const ceCtx = full.context_token ?? undefined;
  try {
    await sendMessageWeixin({ to: ceTo, text: ceReply,
      opts: { baseUrl: deps.baseUrl, token: deps.token, contextToken: ceCtx } });
  } catch (e) { deps.errLog(`[ce] command reply error: ${String(e)}`); }
  return;
}
```

#### D. CE mode flag (before media download)

```javascript
const _ceActive = !textBody.startsWith("/") && (await _isCEModeOn());
const _hasVoice = _hasVoiceItem(full);
const _hasText  = !!textBody && !textBody.startsWith("/");
```

#### E. CE intercept block (after media download, before agent dispatch)

```javascript
if (_ceActive && (_hasVoice || _hasText)) {
  const ceScriptPath = os.homedir() + "/.openclaw/workspace/skills/wechat-ce/scripts/ce-handler.py";
  const ceTo = full.from_user_id ?? "";
  const ceCtx = full.context_token ?? undefined;
  const { execFile } = await import("node:child_process");
  let pythonArgs = _hasText ? ["--text", textBody] : [];
  if (_hasVoice && !_hasText) {
    let voiceText = null;
    if (full.item_list) {
      for (const item of full.item_list) {
        if (item?.voice_item?.text) { voiceText = item.voice_item.text; break; }
      }
    }
    pythonArgs = voiceText ? ["--text", voiceText]
               : mediaOpts.decryptedVoicePath ? ["--file", mediaOpts.decryptedVoicePath]
               : [];
  }
  if (pythonArgs.length > 0) {
    const raw = await new Promise((resolve, reject) =>
      execFile("/usr/bin/python3", [ceScriptPath, ...pythonArgs],
        { timeout: 120000, maxBuffer: 10 * 1024 * 1024 },
        (err, stdout, stderr) => err ? reject(new Error(stderr.slice(0, 300))) : resolve(stdout))
    );
    let ceResult;
    try { ceResult = JSON.parse(raw); } catch { ceResult = { text: raw }; }
    const ceTranslation = ceResult.text ?? "";
    const ceAudioPath   = ceResult.audio ?? "";
    if (ceAudioPath) {
      await sendWeixinMediaFile({ filePath: ceAudioPath, to: ceTo, text: ceTranslation,
        opts: { baseUrl: deps.baseUrl, token: deps.token, contextToken: ceCtx },
        cdnBaseUrl: deps.cdnBaseUrl });
    } else if (ceTranslation) {
      await sendMessageWeixin({ to: ceTo, text: ceTranslation,
        opts: { baseUrl: deps.baseUrl, token: deps.token, contextToken: ceCtx } });
    }
    return;
  }
}
```

> **ce-handler.py output format:** Always a single JSON line — `{"label": "English text", "text": "...", "audio": "/tmp/ce-wechat/ce_TIMESTAMP_en.mp3"}`. The intercept sends the MP3 via `sendWeixinMediaFile` with translation as caption. If no audio path, falls back to text-only reply.

---

### `ce-handler.py` — pipeline script

Full path: `~/.openclaw/workspace/skills/wechat-ce/scripts/ce-handler.py`

Key constants:
```python
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")
EDGE_TTS_SCRIPT = Path(__file__).resolve().parents[2] / "edge-tts" / "scripts" / "tts-converter.js"
TMP_DIR = Path(os.environ.get("TMP_DIR", "/tmp/ce-wechat"))
```

Ollama is called via HTTP (not CLI) to avoid stdin-blocking:
```python
req = urllib.request.Request(
    "http://localhost:11434/api/generate",
    data=json.dumps({"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    result = json.loads(resp.read().decode())
```

Whisper is called with `stdin=subprocess.DEVNULL` to avoid blocking:
```python
p = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
```

---

### `mode.py` — CLI helper

```bash
python3 ~/.openclaw/workspace/skills/wechat-ce/scripts/mode.py        # print on/off
python3 ~/.openclaw/workspace/skills/wechat-ce/scripts/mode.py on     # enable
python3 ~/.openclaw/workspace/skills/wechat-ce/scripts/mode.py off    # disable
python3 ~/.openclaw/workspace/skills/wechat-ce/scripts/mode.py toggle # flip
```

State file: `~/.openclaw/memory/wechat_ce_mode.json` → `{"enabled": true}`

---

## Auto-Update & Reboot Survival (v1.2 / updated v1.3)

`openclaw update` reinstalls the `openclaw-weixin` npm package, overwriting the compiled dist JS and removing all CE patches. The gateway restarts with the stock plugin — CE translation silently stops working.

### Solution: macOS LaunchAgent with WatchPaths

Two files work together:

| File | Purpose |
|------|---------|
| `boot-patch.sh` | Checks patch presence; re-applies and restarts gateway if missing |
| `ai.openclaw.wechat-ce-patch.plist` | LaunchAgent: triggers on login AND whenever npm dist JS is overwritten |

**Two automatic triggers:**
1. **Every reboot/login** (`RunAtLoad: true`) — ensures patch is present after any restart
2. **WatchPaths on the npm dist JS** — fires the instant `openclaw update` overwrites it, re-patches and restarts gateway automatically

**v1.3 change:** WatchPaths watches the JS dist (not the TypeScript extension source):
```
~/.openclaw/npm/node_modules/@tencent-weixin/openclaw-weixin/dist/src/messaging/process-message.js
```

### One-time setup

```bash
cp ~/.openclaw/workspace/skills/wechat-ce/ai.openclaw.wechat-ce-patch.plist \
   ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/ai.openclaw.wechat-ce-patch.plist
```

**Verify:**
```bash
launchctl list | grep wechat-ce   # → -  0  ai.openclaw.wechat-ce-patch
tail -20 /tmp/openclaw/wechat-ce-patch.log
```

### Manual fallback

```bash
bash ~/.openclaw/workspace/skills/wechat-ce/patch.sh --check
bash ~/.openclaw/workspace/skills/wechat-ce/patch.sh
openclaw gateway restart
```

### patch.sh reference

```bash
bash patch.sh            # apply (copies process-message.patched.js → npm dist)
bash patch.sh --check    # read-only check for _isCEModeOn marker
bash patch.sh --restore  # restore from pre-patch backup
```

---

## Race Condition Notes

CE mode is checked **before** the media download in `process-message.js`. This means:

- A `/ce off` command that arrives just before a voice message will write `false` to disk
- The voice message reads the file before starting its (potentially slow) download
- The race window is reduced to effectively zero for sequential messages

For truly simultaneous messages (recorded voice + `/ce off` sent within milliseconds), a small race remains. In practice this is indistinguishable from the user's intent being ambiguous.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| CE mode won't turn off | Concurrent voice processing read mode before `/ce off` | Wait ~5s after `/ce off` before sending new voice |
| CE sends raw JSON as text | Old intercept code before v1.3 fix | Run `bash patch.sh` to re-apply updated reference |
| No audio file returned | Edge TTS script path wrong | Check `EDGE_TTS_SCRIPT`; verify `tts-converter.js` exists |
| `CE exited 1: ...` | Whisper or Ollama not running | `ollama serve &` and check Whisper install |
| Translation garbled | Wrong Ollama model loaded | `ollama list`; `ollama pull qwen2.5:7b-instruct` |
| CE translation stops after `openclaw update` | npm reinstall overwrote `process-message.js` | Run `bash patch.sh --check`, then `bash patch.sh && openclaw gateway restart` |
| `patch.sh` says "reference file not found" | `process-message.patched.js` missing from skill dir | Re-clone the repo or copy the file from GitHub |
| `/ce` returns "Unknown command" | Gateway loaded unpatched npm dist | Run `bash patch.sh && openclaw gateway restart` |
