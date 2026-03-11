#!/usr/bin/env python3
"""Generate the three idle loop videos for the companion avatar.

Requires:
  - Source image at avatar/source/companion.png
  - LivePortrait installed
  - Idle driver audio at avatar/source/idle_driver.wav (generated if missing)

Renders:
  - avatar/idle_loop.mp4      - neutral, at rest
  - avatar/idle_thinking.mp4  - slight downward gaze
  - avatar/idle_listening.mp4 - forward attention
"""
import subprocess
import sys
import wave
import struct
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    SOURCE_IMAGE, LIVEPORTRAIT_PATH,
    IDLE_LOOP, IDLE_THINKING, IDLE_LISTENING, IDLE_DRIVER,
    AVATAR_RESOLUTION,
)

IDLE_DURATION_SEC = 12
SAMPLE_RATE = 16000


def generate_idle_driver():
    if IDLE_DRIVER.exists():
        print(f"Idle driver already exists: {IDLE_DRIVER}")
        return

    IDLE_DRIVER.parent.mkdir(parents=True, exist_ok=True)
    n_samples = SAMPLE_RATE * IDLE_DURATION_SEC

    with wave.open(str(IDLE_DRIVER), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)

        for i in range(n_samples):
            t = i / SAMPLE_RATE
            breath = math.sin(2 * math.pi * 0.2 * t) * 50
            noise = (hash(i) % 20) - 10
            sample = int(breath + noise)
            sample = max(-32768, min(32767, sample))
            wf.writeframes(struct.pack("<h", sample))

    print(f"Generated idle driver audio: {IDLE_DRIVER}")


def render_idle(output_path: Path, label: str):
    if output_path.exists():
        print(f"Already exists: {output_path} - skipping")
        return

    print(f"Rendering {label}...", flush=True)

    env = {
        **subprocess.os.environ,
        "PYTORCH_ENABLE_MPS_FALLBACK": "1",
    }

    result = subprocess.run(
        [
            "python", "inference.py",
            "--source_image", str(SOURCE_IMAGE),
            "--driving_audio", str(IDLE_DRIVER),
            "--output", str(output_path),
            "--size", str(AVATAR_RESOLUTION),
        ],
        cwd=str(LIVEPORTRAIT_PATH),
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )

    if result.returncode != 0:
        print(f"  FAILED: {result.stderr[:300]}")
        return

    if output_path.exists():
        print(f"  Done: {output_path}")
    else:
        print(f"  Warning: render completed but file not found at {output_path}")


def main():
    if not SOURCE_IMAGE.exists():
        print(f"Error: Source image not found at {SOURCE_IMAGE}")
        print("Run scripts/generate_face.py first and select a face.")
        sys.exit(1)

    if not LIVEPORTRAIT_PATH.exists():
        print(f"Error: LivePortrait not found at {LIVEPORTRAIT_PATH}")
        sys.exit(1)

    generate_idle_driver()
    render_idle(IDLE_LOOP, "idle_loop (rest)")
    render_idle(IDLE_THINKING, "idle_thinking")
    render_idle(IDLE_LISTENING, "idle_listening")

    print("\nIdle loop generation complete.")
    missing = [p for p in [IDLE_LOOP, IDLE_THINKING, IDLE_LISTENING] if not p.exists()]
    if missing:
        print(f"Warning: {len(missing)} loops failed to render.")
    else:
        print("All three idle states ready.")


if __name__ == "__main__":
    main()
