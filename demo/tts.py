"""Narration for the demo video: one audio clip per line of a script.

  python demo/tts.py script.txt out_dir [--model qwen3-tts-flash] [--voice Cherry]

Each non-empty line of script.txt becomes out_dir/01.wav, 02.wav, ...
Models verified with our Bailian key (2026-10-03):
  qwen3-tts-flash, qwen3-tts-instruct-flash      voices e.g. Cherry, Ethan
  cosyvoice-v3-plus, cosyvoice-v3-flash          voices e.g. longanyang
  cosyvoice-v2                                   voices e.g. longxiaochun_v2
qwen3-tts-instruct-flash also takes --instructions (speaking style).
Reads DASHSCOPE_API_KEY from the environment or backend/.env.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def api_key() -> str:
    if os.environ.get("DASHSCOPE_API_KEY"):
        return os.environ["DASHSCOPE_API_KEY"]
    for line in (ROOT / "backend" / ".env").read_text().splitlines():
        if line.startswith("DASHSCOPE_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("DASHSCOPE_API_KEY not set")


def qwen_tts(text: str, model: str, voice: str, instructions: str | None) -> bytes:
    body = {"model": model,
            "input": {"text": text, "voice": voice, "language_type": "Chinese"}}
    if instructions:
        body["input"]["instructions"] = instructions
    req = urllib.request.Request(
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {api_key()}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        url = json.load(r)["output"]["audio"]["url"]
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def cosyvoice(text: str, model: str, voice: str) -> bytes:
    import dashscope  # pip install dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer
    dashscope.api_key = api_key()
    return SpeechSynthesizer(model=model, voice=voice).call(text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("out")
    ap.add_argument("--model", default="qwen3-tts-flash")
    ap.add_argument("--voice", default=None)
    ap.add_argument("--instructions", default=None)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    lines = [ln.strip() for ln in Path(a.script).read_text().splitlines() if ln.strip()]
    cosy = a.model.startswith("cosyvoice")
    voice = a.voice or ("longanyang" if cosy else "Cherry")
    for i, text in enumerate(lines, 1):
        audio = cosyvoice(text, a.model, voice) if cosy \
            else qwen_tts(text, a.model, voice, a.instructions)
        f = out / f"{i:02d}.{'mp3' if cosy else 'wav'}"
        f.write_bytes(audio)
        print(f, text[:30])


if __name__ == "__main__":
    main()
