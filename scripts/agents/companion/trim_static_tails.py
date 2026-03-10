#!/usr/bin/env python3
"""Trim static tails from loop clips.

Analyzes frame-to-frame scene change scores to find where motion ends,
then trims each clip to remove the frozen tail. Keeps a 0.3s buffer
so the cut doesn't feel abrupt.

Overwrites originals after backing up.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import IDLE_LOOPS_DIR

LOOPS_DIR = IDLE_LOOPS_DIR
MOTION_THRESHOLD = 0.004  # rolling avg scene score below this = static
WINDOW_FRAMES = 24        # 1 second rolling window at 24fps
TAIL_BUFFER = 0.3         # keep 0.3s after last motion for smooth end
MIN_TRIM = 0.5            # only trim if saving more than 0.5s


def get_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=15,
    )
    return float(r.stdout.strip())


def find_trim_point(path):
    """Return the time (seconds) to trim to, or None if no trim needed."""
    duration = get_duration(path)

    r = subprocess.run(
        ["ffmpeg", "-i", str(path),
         "-vf", "select='gte(scene,0)',metadata=print:file=/dev/stdout",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60,
    )

    scores = []
    for line in r.stdout.splitlines():
        if "scene_score" in line:
            val = line.split("=")[-1]
            try:
                scores.append(float(val))
            except ValueError:
                pass

    if len(scores) < WINDOW_FRAMES * 2:
        return None

    fps = len(scores) / duration
    w = WINDOW_FRAMES

    # Rolling mean
    means = [sum(scores[i:i+w]) / w for i in range(len(scores) - w)]

    # Find last frame with significant motion
    last_active = 0
    for i, m in enumerate(means):
        if m > MOTION_THRESHOLD:
            last_active = i + w

    trim_time = min(last_active / fps + TAIL_BUFFER, duration)
    saved = duration - trim_time

    if saved < MIN_TRIM:
        return None

    return trim_time


def trim_clip(path, trim_time):
    """Trim clip to trim_time seconds, overwriting original."""
    tmp = path.with_suffix(".trimmed.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(path),
         "-t", f"{trim_time:.3f}",
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
         "-an", str(tmp)],
        capture_output=True, timeout=60,
    )
    if tmp.exists() and tmp.stat().st_size > 0:
        # Backup original
        bak = path.with_suffix(".pretrim.mp4")
        if not bak.exists():
            path.rename(bak)
        else:
            path.unlink()
        tmp.rename(path)
        return True
    return False


def main():
    clips = sorted(LOOPS_DIR.glob("loop_*.mp4"))
    if not clips:
        print("No loop clips found")
        return

    print(f"Analyzing {len(clips)} clips...\n")

    trimmed = 0
    for clip in clips:
        duration = get_duration(clip)
        trim_time = find_trim_point(clip)

        if trim_time is None:
            print(f"  {clip.name}: {duration:.1f}s — no trim needed")
            continue

        saved = duration - trim_time
        print(f"  {clip.name}: {duration:.1f}s -> {trim_time:.1f}s (trimming {saved:.1f}s)")

        if trim_clip(clip, trim_time):
            new_dur = get_duration(clip)
            print(f"    done ({new_dur:.1f}s)")
            trimmed += 1
        else:
            print(f"    FAILED")

    print(f"\nTrimmed {trimmed}/{len(clips)} clips.")
    if trimmed:
        print("Originals backed up as .pretrim.mp4")


if __name__ == "__main__":
    main()
