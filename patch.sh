#!/usr/bin/env bash
# patch.sh — Apply CE translation patches to the openclaw-weixin plugin.
#
# Run this after any openclaw-weixin plugin update, which auto-overwrites
# the extension files from npm and removes these patches.
#
# Usage:
#   bash patch.sh            # apply patches
#   bash patch.sh --check    # check if patches are already applied
#   bash patch.sh --restore  # restore from backup (undo patches)
#
# What it patches:
#   ~/.openclaw/extensions/openclaw-weixin/src/messaging/process-message.ts
#
# The patch adds:
#   A. import os from "node:os"
#   B. _isCEModeOn(), _hasVoiceItem(), _handleCECommand() helpers
#   C. CE command handler (before slash command block)
#   D. Early CE mode flag (before media download, closes race window)
#   E. CE intercept block (after media download, before agent dispatch)

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.openclaw/extensions/openclaw-weixin/src/messaging/process-message.ts"
BACKUP="${TARGET}.bak-pre-ce-patch"
PATCHED_REF="$SKILL_DIR/process-message.patched.ts"

# ── helpers ──────────────────────────────────────────────────────────────────

red()   { echo -e "\033[31m$*\033[0m"; }
green() { echo -e "\033[32m$*\033[0m"; }
yellow(){ echo -e "\033[33m$*\033[0m"; }

check_already_patched() {
  grep -q "_isCEModeOn" "$TARGET" 2>/dev/null
}

# ── --check ──────────────────────────────────────────────────────────────────

if [[ "${1:-}" == "--check" ]]; then
  if check_already_patched; then
    green "✅ CE patches are present in process-message.ts"
  else
    red "❌ CE patches are NOT present — run: bash patch.sh"
  fi
  exit 0
fi

# ── --restore ────────────────────────────────────────────────────────────────

if [[ "${1:-}" == "--restore" ]]; then
  if [[ -f "$BACKUP" ]]; then
    cp "$BACKUP" "$TARGET"
    green "✅ Restored original process-message.ts from $BACKUP"
  else
    red "❌ No backup found at $BACKUP"
    exit 1
  fi
  exit 0
fi

# ── apply patches ────────────────────────────────────────────────────────────

if [[ ! -f "$TARGET" ]]; then
  red "❌ Target not found: $TARGET"
  red "   Is the openclaw-weixin plugin installed?"
  exit 1
fi

if check_already_patched; then
  yellow "⚠️  CE patches already present. Nothing to do."
  yellow "   Run with --check to verify, or --restore to undo."
  exit 0
fi

# Use the pre-patched reference file if available
if [[ -f "$PATCHED_REF" ]]; then
  echo "Backing up original → $BACKUP"
  cp "$TARGET" "$BACKUP"
  echo "Applying patch from reference file…"
  cp "$PATCHED_REF" "$TARGET"
  green "✅ Patch applied from $PATCHED_REF"
  echo ""
  echo "Restart the gateway to pick up changes:"
  echo "  openclaw gateway --force"
  exit 0
fi

red "❌ Reference patch file not found: $PATCHED_REF"
red "   Clone the full skill repo to get process-message.patched.ts"
exit 1
