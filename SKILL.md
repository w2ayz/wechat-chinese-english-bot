---
name: openclaw-wechat-ce
description: >
  CE (Chinese↔English) real-time translation for WeChat via Openclaw plugin-level
  intercept. Translation is handled automatically before reaching the agent.
  This skill only manages the CE mode toggle UI responses.
  Do NOT translate messages yourself — the platform handles it.
---

# WeChat CE Skill — Openclaw Implementation Guide

CE (Chinese↔English) translation is handled **automatically at the plugin level** by patching the `openclaw-weixin` extension. Messages are intercepted in `process-message.ts`, routed through the `ce-handler.py` pipeline (Whisper → Ollama → Edge TTS), and delivered back to the user — all before the agent sees the message.

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

### Plugin patch: `process-message.ts`

The CE logic is injected into `openclaw-weixin/src/messaging/process-message.ts` in three places:

#### A. Imports (top of file)
```typescript
import os from "node:os";
```

#### B. Helper functions (before `processOneMessage`)

```typescript
/** Read CE mode state from disk. */
async function _isCEModeOn(): Promise<boolean> {
  const modePath = os.homedir() + "/.openclaw/memory/wechat_ce_mode.json";
  try {
    const { readFile } = await import("node:fs/promises");
    const raw = await readFile(modePath, "utf-8");
    return JSON.parse(raw)?.enabled === true;
  } catch { return false; }
}

/** True if message contains a voice item. */
function _hasVoiceItem(full: WeixinMessage): boolean {
  if (!full?.item_list) return false;
  for (const item of full.item_list) { if (item?.voice_item) return true; }
  return false;
}

/** Handle /CE slash commands; returns reply text or null if not a CE command. */
async function _handleCECommand(text: string): Promise<string | null> {
  const t = text.trim().toLowerCase();
  const modePath = os.homedir() + "/.openclaw/memory/wechat_ce_mode.json";
  const { readFile, writeFile, mkdir } = await import("node:fs/promises");

  const readMode = async (): Promise<boolean> => {
    try { return JSON.parse(await readFile(modePath, "utf-8"))?.enabled === true; }
    catch { return false; }
  };
  const writeMode = async (enabled: boolean): Promise<void> => {
    await mkdir(os.homedir() + "/.openclaw/memory", { recursive: true });
    await writeFile(modePath, JSON.stringify({ enabled }), "utf-8");
  };

  if (t === "/ce" || t === "ce") {
    const cur = await readMode();
    await writeMode(!cur);
    return !cur
      ? "✅ CE mode ON — I'll translate every message and voice note."
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

#### C. Early CE mode check (inside `processOneMessage`, before media download)

Add immediately after `const textBody = extractTextBody(full.item_list);`:

```typescript
// --- CE slash command: handle /CE, /CE on, /CE off directly (no agent) ---
const ceReply = await _handleCECommand(textBody);
if (ceReply !== null) {
  const ceTo = full.from_user_id ?? "";
  const ceCtx = full.context_token ?? undefined;
  try {
    await sendMessageWeixin({
      to: ceTo,
      text: ceReply,
      opts: { baseUrl: deps.baseUrl, token: deps.token, contextToken: ceCtx },
    });
    logger.info(`[ce] command handled: "${textBody.trim()}" → mode updated`);
  } catch (e) { deps.errLog(`[ce] command reply error: ${String(e)}`); }
  return;
}
```

#### D. CE mode flag (before media download, to avoid race condition)

Add immediately before the media download section:

```typescript
// Check CE mode BEFORE downloading media so a concurrent /ce off is already on disk.
const _ceActive = !textBody.startsWith("/") && (await _isCEModeOn());
const _hasVoice = _hasVoiceItem(full);
const _hasText  = !!textBody && !textBody.startsWith("/");
```

#### E. CE intercept block (after media download, before agent dispatch)

Replace the existing `// === CE INTERCEPT ===` section:

```typescript
if (!textBody.startsWith("/")) {
  if (_ceActive && (_hasVoice || _hasText)) {
    const ceScriptPath =
      os.homedir() + "/.openclaw/workspace/skills/openclaw-wechat-ce/scripts/ce-handler.py";
    const ceTo = full.from_user_id ?? "";
    const ceContextToken = full.context_token ?? undefined;

    try {
      const { execFile } = await import("node:child_process");

      let pythonArgs: string[];
      let ceTimeout: number;

      if (_hasVoice) {
        let voiceText: string | null = null;
        if (full.item_list) {
          for (const item of full.item_list) {
            if (item?.voice_item?.text) { voiceText = item.voice_item.text; break; }
          }
        }
        if (voiceText) {
          pythonArgs = ["--text", voiceText];
          ceTimeout = 60000;
        } else if (mediaOpts.decryptedVoicePath) {
          pythonArgs = ["--file", mediaOpts.decryptedVoicePath];
          ceTimeout = 180000;
        } else {
          pythonArgs = [];
          ceTimeout = 0;
        }
      } else {
        pythonArgs = ["--text", textBody];
        ceTimeout = 60000;
      }

      if (pythonArgs.length > 0) {
        const { stdout: pyOut } = await new Promise<{ stdout: string }>((resolve, reject) => {
          execFile(
            "/usr/bin/python3",
            [ceScriptPath, ...pythonArgs],
            { timeout: ceTimeout, maxBuffer: 10 * 1024 * 1024 },
            (err, stdout, stderr) => {
              if (err) {
                if (err.signal === "SIGTERM") reject(new Error("CE handler timed out"));
                else reject(new Error("CE exited " + err.exitCode + ": " + stderr.slice(0, 300)));
              } else {
                resolve({ stdout });
              }
            },
          );
        });

        const ceResult = JSON.parse(pyOut.trim());

        if (ceResult.error) {
          await sendMessageWeixin({
            to: ceTo,
            text: `⚠️ CE error: ${ceResult.error}`,
            opts: { baseUrl: deps.baseUrl, token: deps.token, contextToken: ceContextToken },
          });
        } else {
          await sendMessageWeixin({
            to: ceTo,
            text: `${ceResult.label}: ${ceResult.text}`,
            opts: { baseUrl: deps.baseUrl, token: deps.token, contextToken: ceContextToken },
          });
          if (ceResult.audio) {
            try {
              await sendWeixinMediaFile({
                filePath: ceResult.audio,
                to: ceTo,
                text: "",
                opts: { baseUrl: deps.baseUrl, token: deps.token, contextToken: ceContextToken },
                cdnBaseUrl: deps.cdnBaseUrl,
              });
            } catch (audioErr) {
              logger.error(`[ce] audio send error: ${String(audioErr)}`);
            }
          }
        }
        return;
      }
    } catch (ceErr) {
      logger.error(`[ce] pipeline error: ${String(ceErr)}`);
      try {
        await sendMessageWeixin({
          to: full.from_user_id ?? "",
          text: `⚠️ CE pipeline error: ${String(ceErr).slice(0, 200)}`,
          opts: {
            baseUrl: deps.baseUrl,
            token: deps.token,
            contextToken: full.context_token ?? undefined,
          },
        });
      } catch (_) { /* ignore reply error */ }
      return;
    }
  }
}
```

---

### `send-media.ts` — audio as file attachment

In `openclaw-weixin/src/messaging/send-media.ts`, the `audio/*` MIME type falls through to the generic file attachment path. No special voice-bubble route is needed. The file comment on the fallback block should read:

```typescript
// File attachment: pdf, doc, zip, audio, etc.
```

---

### `ce-handler.py` — pipeline script

Full path: `~/.openclaw/workspace/skills/openclaw-wechat-ce/scripts/ce-handler.py`

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
python3 ~/.openclaw/workspace/skills/openclaw-wechat-ce/scripts/mode.py        # print on/off
python3 ~/.openclaw/workspace/skills/openclaw-wechat-ce/scripts/mode.py on     # enable
python3 ~/.openclaw/workspace/skills/openclaw-wechat-ce/scripts/mode.py off    # disable
python3 ~/.openclaw/workspace/skills/openclaw-wechat-ce/scripts/mode.py toggle # flip
```

State file: `~/.openclaw/memory/wechat_ce_mode.json` → `{"enabled": true}`

---

## Race Condition Notes

CE mode is checked **before** the media download in `process-message.ts`. This means:

- A `/ce off` command that arrives just before a voice message will write `false` to disk
- The voice message reads the file before starting its (potentially slow) download
- The race window is reduced to effectively zero for sequential messages

For truly simultaneous messages (recorded voice + `/ce off` sent within milliseconds), a small race remains. In practice this is indistinguishable from the user's intent being ambiguous.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| CE mode won't turn off | Concurrent voice processing read mode before `/ce off` | Wait ~5s after `/ce off` before sending new voice |
| No audio file returned | Edge TTS script path wrong | Check `EDGE_TTS_SCRIPT` env var; verify `tts-converter.js` exists |
| `CE exited 1: ...` | Whisper or Ollama not running | `ollama serve &` and check Whisper install |
| Translation garbled | Wrong Ollama model loaded | `ollama list`; `ollama pull qwen2.5:7b-instruct` |
| Gateway rejects plugin | TypeScript compile error in patch | Check `openclaw-gateway` startup logs in `/tmp/openclaw/` |
