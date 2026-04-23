# Changelog

All notable changes to this project will be documented in this file.

---

## [1.2] — 2026-04-22

### Added
- `boot-patch.sh` — script called by LaunchAgent on login and on file-change events; checks patch presence, re-applies if missing, restarts gateway
- `ai.openclaw.wechat-ce-patch.plist` — macOS LaunchAgent with two triggers: `RunAtLoad` (every reboot/login) and `WatchPaths` on `process-message.ts` (fires instantly when npm update overwrites the file)

### Changed
- Patch survival is now **fully automatic** — no manual re-apply needed after Openclaw plugin updates
- README and SKILL.md updated with LaunchAgent setup instructions and boot-patch.sh logic documentation

---

## [1.1] — 2026-04-22

### Added
- `patch.sh` — one-command script to apply, check, and restore the CE patch to `process-message.ts`
- `process-message.patched.ts` — pre-patched plugin file included in the repo for reference and use by `patch.sh`

### Fixed
- **Auto-update wipe problem**: Openclaw auto-updates `openclaw-weixin` from npm, which overwrites `process-message.ts` and removes all CE patches. Documented the problem, detection command, and manual re-apply steps in both README and SKILL.md
- **CE-off race condition**: CE mode is now checked before media download, so a `/ce off` command is guaranteed to be seen by any message arriving after it
- **AES key encoding**: Fixed `Buffer.from(aeskey, "hex")` encoding for voice message decryption

### Changed
- Audio translated output is now delivered as an MP3 file attachment instead of a WeChat voice bubble (voice bubble API does not reliably render for bot accounts)
- Updated README Installation step 3 with `patch.sh` workflow and auto-update warning
- Updated SKILL.md with dedicated Auto-Update Problem section, `patch.sh` reference, and two new Troubleshooting entries

---

## [1.0] — 2026-04-21

### Added
- Initial release
- Real-time Chinese↔English translation via plugin-level intercept in `openclaw-weixin`
- `/ce on` / `/ce off` / `/ce` toggle commands handled directly at plugin level (no agent round-trip)
- Text message pipeline: language detection → Ollama (qwen2.5:7b) translation → Edge TTS → MP3
- Voice message pipeline: Whisper turbo transcription → language detection → Ollama translation → Edge TTS → MP3
- `ce-handler.py` — main pipeline script (Whisper → Ollama HTTP API → Edge TTS)
- `mode.py` — CLI helper to read/set/toggle CE mode from the terminal
- `process-message.ts` patch with 5 injection points: `import os`, helper functions, CE command handler, early mode check (race condition fix), CE intercept block
- `SKILL.md` with full Openclaw implementation guide including all patch points with exact code blocks
