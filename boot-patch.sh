#!/usr/bin/env bash
# boot-patch.sh — Called by launchd at login and whenever process-message.js changes.
# Re-applies the CE patch to the npm dist (the file the gateway actually loads).
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_SH="$SKILL_DIR/patch.sh"
TARGET="$HOME/.openclaw/npm/node_modules/@tencent-weixin/openclaw-weixin/dist/src/messaging/process-message.js"
OPENCLAW="/opt/homebrew/bin/openclaw"

mkdir -p /tmp/openclaw

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(timestamp)] wechat-ce-patch: $*"; }

if [[ ! -f "$TARGET" ]]; then
  log "Target not found — openclaw-weixin npm package not installed yet, skipping"
  exit 0
fi

if grep -q "_isCEModeOn" "$TARGET" 2>/dev/null; then
  log "CE patches already present — nothing to do"
  exit 0
fi

log "CE patches missing — applying..."
bash "$PATCH_SH"
log "Patch applied. Restarting openclaw gateway..."
"$OPENCLAW" gateway restart 2>&1 || true
log "Done."
