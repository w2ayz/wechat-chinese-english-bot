#!/usr/bin/env python3
"""Read or toggle WeChat CE mode.
Usage:
  mode.py           → prints "on" or "off"
  mode.py toggle    → flips state, prints new value
  mode.py on        → enables CE mode
  mode.py off       → disables CE mode
"""
import json
import sys
from pathlib import Path

MODE_FILE = Path.home() / ".openclaw/memory/wechat_ce_mode.json"


def read_mode() -> bool:
    if not MODE_FILE.exists():
        return False
    try:
        return json.loads(MODE_FILE.read_text()).get("enabled", False)
    except (json.JSONDecodeError, OSError):
        return False


def set_mode(enabled: bool):
    MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODE_FILE.write_text(json.dumps({"enabled": enabled}))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "read"

    if cmd == "toggle":
        new = not read_mode()
        set_mode(new)
        print("on" if new else "off")
    elif cmd == "on":
        set_mode(True)
        print("on")
    elif cmd == "off":
        set_mode(False)
        print("off")
    else:
        print("on" if read_mode() else "off")
