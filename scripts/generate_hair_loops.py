#!/usr/bin/env python3
"""Generate 2 additional hair-play loops and rebuild ambient_loop with them interspersed."""
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from config import PROJECT_ROOT

import fal_client
import httpx

SOURCE_IMAGE = PROJECT_ROOT / "avatar" / "candidates" / "natural_02.png"
OUTPUT_DIR = PROJECT_ROOT / "avatar" / "loops"
KLING_MODEL = "fal-ai/kling-video/v3/pro/image-to-video"

NEGATIVE_PROMPT = (
    "blur, distort, low quality, sudden movement, jump cut, morphing, "
    "face distortion, extra fingers, unnatural skin, plastic skin, "
    "uncanny valley, teeth showing too much, exaggerated expression"
)

C = """
Cinematic. 4K. Shallow depth of field. Warm ambient interior light, \
cool from the window. Static camera. No sudden movement."""

def return_prompt(start_description: str) -> str:
    return f"""\
Continuation. Same young woman, same light. She begins {start_description}.

Gradually, without rush, everything settles. Her gaze drifts to the \
middle distance. Expression smooths into open neutrality. Lips close \
softly. A quiet breath. Still.

By the final frame she is neutral — gaze middle-distance, expression \
open, mouth softly closed, breathing slowly.
{C}
FINAL FRAME: middle-distance gaze, neutral open expression, \
mouth softly closed. Matches the source portrait exactly.\
"""


HAIR_SEGMENTS = [
    (
        "16_hair_play",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

She lifts one hand and gathers her hair to one side, fingers threading \
through the lengths slowly. She twists a section around two fingers — \
absent, dreamy. The light catches individual strands as they move. She \
releases the twist and her fingers trail down through the ends, \
letting them fall. A small smile arrives at the corner of her mouth — \
the private kind, as if the gesture itself was the thought.

By the final frame she is mid-gesture, fingers in her hair near her \
shoulder, a private half-smile, eyes soft and unfocused.
{C}
FINAL FRAME: fingers in hair near shoulder, private half-smile, \
eyes soft, dreamy expression.\
""",
        return_prompt("with her fingers in her hair near her shoulder, a private half-smile, dreamy expression"),
    ),

    (
        "17_hair_behind_ear",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

A strand of hair falls across her face. She notices. Her hand comes up \
slowly and hooks it with one finger, pulling it back. But instead of \
tucking it behind her ear immediately, she pauses — finger still in the \
strand, holding it away from her face. She looks directly at the camera \
for a beat. Then she tucks it behind her ear in one smooth motion and \
her hand trails down to her jaw, fingertips resting there briefly.

Her chin lifts. Something knowing passes behind her eyes.

By the final frame she has just finished the tuck, fingertips resting \
on her jaw, chin lifted, looking directly at camera with quiet intent.
{C}
FINAL FRAME: hair freshly tucked, fingertips on jaw, chin lifted, \
direct eye contact, quiet knowing expression.\
""",
        return_prompt("with hair freshly tucked behind her ear, fingertips on her jaw, direct eye contact"),
    ),
]


def upload(path: Path) -> str:
    print(f"  Uploading {path.name}...", end="", flush=True)
    url = fal_client.upload_file(path)
    print(" done")
    return url


def generate_clip(prompt, start_image_url, output_path, label, end_image_url=None):
    if output_path.exists():
        print(f"  {label}: exists — skipping")
        return

    print(f"  {label}: generating...", flush=True)

    args = {
        "prompt": prompt,
        "start_image_url": start_image_url,
        "duration": 5,
        "aspect_ratio": "9:16",
        "negative_prompt": NEGATIVE_PROMPT,
        "cfg_scale": 0.5,
        "generate_audio": False,
    }
    if end_image_url:
        args["end_image_url"] = end_image_url

    result = fal_client.subscribe(KLING_MODEL, arguments=args)
    video_url = result["video"]["url"]

    print(f"  {label}: downloading...", end="", flush=True)
    data = httpx.get(video_url, timeout=120).content
    output_path.write_bytes(data)
    print(f" saved ({len(data) / 1024 / 1024:.1f} MB)")


def extract_last_frame(video_path, output_path):
    if output_path.exists():
        return
    subprocess.run(
        ["ffmpeg", "-sseof", "-0.1", "-i", str(video_path),
         "-vframes", "1", "-q:v", "2", str(output_path)],
        capture_output=True, timeout=30,
    )
    if not output_path.exists():
        print(f"  FAILED to extract frame from {video_path.name}")
        sys.exit(1)


def join_clips(clip1, clip2, output):
    if output.exists():
        return
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(clip1)],
        capture_output=True, text=True, timeout=15,
    )
    duration = float(result.stdout.strip())
    offset = duration - 0.15

    subprocess.run(
        ["ffmpeg", "-i", str(clip1), "-i", str(clip2),
         "-filter_complex",
         f"[0:v][1:v]xfade=transition=fade:duration=0.15:offset={offset:.3f}[v]",
         "-map", "[v]", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
         str(output)],
        capture_output=True, timeout=120,
    )
    if not output.exists():
        print(f"  FAILED to join {clip1.name} + {clip2.name}")
        sys.exit(1)


def generate_segment(name, clip1_prompt, clip2_prompt, source_url):
    clip1_path = OUTPUT_DIR / f"{name}_clip1.mp4"
    clip2_path = OUTPUT_DIR / f"{name}_clip2.mp4"
    endframe_path = OUTPUT_DIR / f"{name}_endframe.jpg"
    loop_path = OUTPUT_DIR / f"loop_{name}.mp4"

    generate_clip(clip1_prompt, source_url, clip1_path, f"{name} clip 1")
    extract_last_frame(clip1_path, endframe_path)
    endframe_url = upload(endframe_path)
    generate_clip(clip2_prompt, start_image_url=endframe_url,
                  output_path=clip2_path, label=f"{name} clip 2",
                  end_image_url=source_url)
    join_clips(clip1_path, clip2_path, loop_path)
    return loop_path


# Final loop order — intersperse the 2 new hair segments among existing ones
FINAL_ORDER = [
    "loop_01_arrival.mp4",
    "loop_02_smile.mp4",
    "loop_03_hair_tuck.mp4",       # original hair
    "loop_04_presence.mp4",
    "loop_16_hair_play.mp4",       # NEW — hair play
    "loop_05_sigh.mp4",
    "loop_06_amusement.mp4",
    "loop_17_hair_behind_ear.mp4", # NEW — hair tuck 2
    "loop_07_glance.mp4",
]


def rebuild_master():
    """Rebuild ambient_loop from all segments in FINAL_ORDER."""
    loop_paths = []
    for name in FINAL_ORDER:
        p = OUTPUT_DIR / name
        if p.exists():
            loop_paths.append(p)
        else:
            print(f"  WARNING: {name} missing — skipping")

    if not loop_paths:
        print("  No loops to concatenate")
        return

    master = PROJECT_ROOT / "avatar" / "ambient_loop.mp4"
    master_loops = OUTPUT_DIR / "ambient_loop_full.mp4"

    # Remove old masters
    master.unlink(missing_ok=True)
    master_loops.unlink(missing_ok=True)

    concat_list = OUTPUT_DIR / "concat_list.txt"
    with open(concat_list, "w") as f:
        for p in loop_paths:
            f.write(f"file '{p}'\n")

    print(f"\n  Concatenating {len(loop_paths)} segments...", end="", flush=True)
    subprocess.run(
        ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(master)],
        capture_output=True, timeout=300,
    )
    concat_list.unlink(missing_ok=True)

    if master.exists():
        size = master.stat().st_size / 1024 / 1024
        print(f" done ({size:.1f} MB)")
        print(f"  Output: {master}")
    else:
        print(" FAILED")


def main():
    if not SOURCE_IMAGE.exists():
        print(f"Error: Source image not found at {SOURCE_IMAGE}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 55)
    print("  Hair Loop Generator — 2 new segments")
    print("=" * 55)

    source_url = upload(SOURCE_IMAGE)

    for name, c1, c2 in HAIR_SEGMENTS:
        loop_path = OUTPUT_DIR / f"loop_{name}.mp4"
        if loop_path.exists():
            print(f"\n  {name}: already exists — skipping")
            continue
        print(f"\n── {name} ──")
        try:
            path = generate_segment(name, c1, c2, source_url)
            print(f"  done: {path.name}")
        except Exception as e:
            print(f"  FAILED: {e}")
            continue

    print("\n── Rebuilding master ambient loop ──")
    rebuild_master()

    print("\n" + "=" * 55)
    print("  Done. New loop order:")
    for i, name in enumerate(FINAL_ORDER, 1):
        exists = "ok" if (OUTPUT_DIR / name).exists() else "MISSING"
        print(f"    {i}. {name} [{exists}]")
    print("=" * 55)


if __name__ == "__main__":
    main()
