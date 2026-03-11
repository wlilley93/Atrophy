#!/usr/bin/env python3
"""Rebuild an agent's ambient_loop.mp4 from all loop segments.

Globs all loop_*.mp4 in the agent's loops directory and concatenates
them into a single ambient_loop.mp4. No hardcoded segment list - just
whatever's there.

Usage:
  python scripts/rebuild_ambient_loop.py                    # Current agent
  AGENT=general_montgomery python scripts/rebuild_ambient_loop.py
  python scripts/rebuild_ambient_loop.py --agent companion
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def rebuild(agent_name: str | None = None):
    if agent_name:
        os.environ["AGENT"] = agent_name

    import importlib
    import config as cfg
    if agent_name:
        importlib.reload(cfg)

    loops_dir = cfg.IDLE_LOOPS_DIR
    output = cfg.IDLE_LOOP

    if not loops_dir.is_dir():
        print(f"No loops directory: {loops_dir}")
        return

    # Glob all loop segments, sorted by name
    segments = sorted(loops_dir.glob("loop_*.mp4"))
    if not segments:
        print(f"No loop_*.mp4 files in {loops_dir}")
        return

    print(f"Agent:    {cfg.AGENT_NAME}")
    print(f"Loops:    {loops_dir}")
    print(f"Segments: {len(segments)}")
    for s in segments:
        size = s.stat().st_size / 1024 / 1024
        print(f"  {s.name}  ({size:.1f} MB)")

    # Build concat list
    concat_list = loops_dir / ".concat_list.txt"
    with open(concat_list, "w") as f:
        for s in segments:
            f.write(f"file '{s}'\n")

    # Remove old master
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    print(f"\nConcatenating {len(segments)} segments...", end="", flush=True)
    result = subprocess.run(
        ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
         str(output)],
        capture_output=True, timeout=300,
    )
    concat_list.unlink(missing_ok=True)

    if output.exists():
        size = output.stat().st_size / 1024 / 1024
        print(f" done ({size:.1f} MB)")
        print(f"Output:   {output}")
    else:
        print(" FAILED")
        if result.stderr:
            print(result.stderr.decode()[:500])


def main():
    parser = argparse.ArgumentParser(description="Rebuild ambient_loop.mp4 from loop segments")
    parser.add_argument("--agent", default=None, help="Agent name")
    args = parser.parse_args()
    rebuild(args.agent)


if __name__ == "__main__":
    main()
