#!/usr/bin/env python3
"""CE pipeline handler for WeChat — Whisper → Ollama → Edge TTS.
Usage:
  --text "some text"          Translate text input
  --file /path/to/audio.ext   Transcribe + translate audio file
  --fast                      Skip Ollama; use Whisper translate task (audio) or TTS as-is (text)
Output: single JSON line → {"label": "...", "text": "...", "audio": "/tmp/...mp3"}
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")
DEFAULT_EDGE_TTS_SCRIPT = (
    Path(__file__).resolve().parents[2] / "edge-tts" / "scripts" / "tts-converter.js"
)
EDGE_TTS_SCRIPT = Path(
    os.environ.get("EDGE_TTS_SCRIPT") or str(DEFAULT_EDGE_TTS_SCRIPT)
)
TMP_DIR = Path(os.environ.get("TMP_DIR", "/tmp/ce-wechat"))


def run_cmd(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "command failed")
    return p.stdout.strip()


def detect_language(text: str) -> str:
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf':
            return 'zh'
    return 'en'


def clean_ollama(text: str) -> str:
    text = re.sub(r"\x1B\[[0-9;?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"[\x00-\x1F\x7F]", "", text)
    return text.strip()


def translate(text: str, source: str, target: str) -> str:
    source_label = "Chinese" if source == "zh" else "English"
    target_label = "English" if target == "en" else "Chinese"
    prompt = (
        f"Translate the following {source_label} to {target_label}. "
        "Keep names, numbers, dates, and IDs exact. "
        f"Do not add facts. Output only {target_label} text in natural style.\n\n"
        f"{source_label}:\n{text}"
    )
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps({"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode())
    return result.get("response", "").strip() or "(translation failed)"


def transcribe_audio(audio_path: Path, task: str = "transcribe") -> str:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    run_cmd([
        "whisper", str(audio_path),
        "--model", "turbo",
        "--task", task,
        "--output_format", "txt",
        "--output_dir", str(TMP_DIR),
    ])
    txt_path = TMP_DIR / f"{audio_path.stem}.txt"
    if not txt_path.exists():
        raise RuntimeError(f"Whisper transcript not found at {txt_path}")
    return txt_path.read_text(encoding="utf-8").strip()


def tts_edge(text: str, out_mp3: Path, voice: str) -> Path:
    if not EDGE_TTS_SCRIPT.exists():
        raise RuntimeError(f"Edge TTS script not found: {EDGE_TTS_SCRIPT}")
    run_cmd(["node", str(EDGE_TTS_SCRIPT), text, "--voice", voice, "--output", str(out_mp3)])
    return out_mp3


def main():
    parser = argparse.ArgumentParser(description="CE WeChat handler")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Input text to translate + synthesise")
    group.add_argument("--file", help="Path to audio file to transcribe, translate, synthesise")
    parser.add_argument("--fast", action="store_true",
                        help="Fast mode: Whisper translate task (audio) or TTS as-is (text)")
    args = parser.parse_args()

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    ts = str(int(time.time() * 1000))

    try:
        if args.file:
            audio_path = Path(args.file)
            if not audio_path.exists():
                print(json.dumps({"error": f"File not found: {args.file}"}))
                sys.exit(1)

            if args.fast:
                output_text = transcribe_audio(audio_path, task="translate")
                voice    = "en-US-AriaNeural"
                out_mp3  = TMP_DIR / f"ce_{ts}_en_fast.mp3"
                label    = "English text"
            else:
                transcript = transcribe_audio(audio_path)
                lang = detect_language(transcript)
                if lang == "zh":
                    output_text = translate(transcript, "zh", "en")
                    voice   = "en-US-AriaNeural"
                    out_mp3 = TMP_DIR / f"ce_{ts}_en.mp3"
                    label   = "English text"
                else:
                    output_text = translate(transcript, "en", "zh")
                    voice   = "zh-CN-XiaoxiaoNeural"
                    out_mp3 = TMP_DIR / f"ce_{ts}_zh.mp3"
                    label   = "Chinese text"

        else:  # --text
            text = args.text
            lang = detect_language(text)

            if args.fast:
                output_text = text
                voice   = "zh-CN-XiaoxiaoNeural" if lang == "zh" else "en-US-AriaNeural"
                out_mp3 = TMP_DIR / f"ce_{ts}_fast.mp3"
                label   = "Chinese text" if lang == "zh" else "English text"
            elif lang == "zh":
                output_text = translate(text, "zh", "en")
                voice   = "en-US-AriaNeural"
                out_mp3 = TMP_DIR / f"ce_{ts}_en.mp3"
                label   = "English text"
            else:
                output_text = translate(text, "en", "zh")
                voice   = "zh-CN-XiaoxiaoNeural"
                out_mp3 = TMP_DIR / f"ce_{ts}_zh.mp3"
                label   = "Chinese text"

        tts_edge(output_text, out_mp3, voice)

        print(json.dumps({
            "label":  label,
            "text":   output_text,
            "audio":  str(out_mp3),
        }))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
