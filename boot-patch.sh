#!/usr/bin/env bash
# boot-patch.sh — Called by LaunchAgent on login and whenever process-message.ts changes.
# Checks if CE patch is present; if not, re-applies it and restarts the gateway.

LOG="/tmp/openclaw/wechat-ce-patch.log"
PATCH_SCRIPT="$HOME/.openclaw/workspace/skills/openclaw-wechat-ce/patch.sh"
TARGET="$HOME/.openclaw/extensions/openclaw-weixin/src/messaging/process-message.ts"

mkdir -p /tmp/openclaw
echo "[$(date '+%Y-%m-%d %H:%M:%S')] boot-patch.sh triggered" >> "$LOG"

# Check if patch is present
if grep -q "_isCEModeOn" "$TARGET" 2>/dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] CE patch already present — nothing to do" >> "$LOG"
    exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] CE patch missing — applying..." >> "$LOG"

# Apply patch
if bash "$PATCH_SCRIPT" >> "$LOG" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Patch applied OK — restarting gateway..." >> "$LOG"
    # Give openclaw a moment if it's mid-update
    sleep 3
    /opt/homebrew/bin/openclaw gateway --force >> "$LOG" 2>&1 &
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Gateway restart issued" >> "$LOG"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: patch.sh failed" >> "$LOG"
    exit 1
fi
