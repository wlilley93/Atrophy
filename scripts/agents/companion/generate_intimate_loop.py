#!/usr/bin/env python3
"""Generate an intimate/sensual loop segment and add it to the ambient cycle."""
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from config import AVATAR_DIR, IDLE_LOOPS_DIR

import fal_client
import httpx

SOURCE_IMAGE = AVATAR_DIR / "candidates" / "natural_02.png"
OUTPUT_DIR = IDLE_LOOPS_DIR
KLING_MODEL = "fal-ai/kling-video/v3/pro/image-to-video"

NEGATIVE_PROMPT = (
    "blur, distort, low quality, sudden movement, jump cut, morphing, "
    "face distortion, extra fingers, unnatural skin, plastic skin, "
    "uncanny valley, teeth showing too much, exaggerated expression, "
    "nudity, explicit, vulgar"
)

C = """
Cinematic. 4K. Shallow depth of field. Warm ambient interior light, \
cool from the window. Static camera. No sudden movement."""

# ── The segment: a slow, private stretch with a held look ──

SEGMENT = (
    "18_slow_stretch",

    # Clip 1: neutral → the stretch, the touch, the look
    f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

She shifts her weight. Her back arches slowly as she stretches — shoulders \
rolling back, neck lengthening. The movement is unhurried, feline. One hand \
rises and her fingertips drag slowly up the side of her neck, tracing her \
jawline. Her lips part. Her eyes close. The warm light catches the curve of \
her throat, the hollow of her collarbone.

Her head tilts into her own hand. A slow exhale through parted lips. Her \
fingers slide back down her neck to her collarbone, pressing lightly into \
the skin. Then her eyes open — heavy-lidded, directly at camera. She doesn't \
blink. The corner of her mouth lifts. Not a smile. An invitation. She bites \
her lower lip, barely, just the edge of her teeth catching it.

By the final frame: heavy-lidded direct eye contact, lips barely parted, \
fingertips pressing into collarbone, head tilted, the beginning of a smile \
that hasn't fully arrived.
{C}
FINAL FRAME: heavy-lidded eye contact, lips parted, fingers on collarbone, \
head tilted, charged expression, warm light on throat and jaw.\
""",

    # Clip 2: the held look dissolves back to neutral
    f"""\
Continuation. Same young woman, same light. She begins with heavy-lidded \
direct eye contact, lips barely parted, fingertips pressing into her \
collarbone, head tilted.

She holds the look for a beat. Then something shifts — the tension in her \
shoulders releases. Her fingers trail down from her collarbone, slow, \
dragging lightly across her upper chest. Her hand comes to rest at the \
neckline of her top, pausing there. She exhales — her whole body softens \
with it. Her teeth release her lip.

Her eyes stay on camera but the intensity fades. The heat becomes warmth. \
Her hand drops to her lap. Her gaze drifts to the middle distance. Her \
lips close. A quiet breath. Still.

By the final frame she is neutral — gaze middle-distance, expression \
open, mouth softly closed, breathing slowly.
{C}
FINAL FRAME: middle-distance gaze, neutral open expression, \
mouth softly closed. Matches the source portrait exactly.\
""",
)


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


def main():
    if not SOURCE_IMAGE.exists():
        print(f"Error: Source image not found at {SOURCE_IMAGE}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    name, clip1_prompt, clip2_prompt = SEGMENT
    loop_path = OUTPUT_DIR / f"loop_{name}.mp4"

    if loop_path.exists():
        print(f"  {name}: already exists — skipping")
        print(f"  Output: {loop_path}")
        return

    print("=" * 55)
    print("  Intimate Loop Generator")
    print("=" * 55)

    source_url = upload(SOURCE_IMAGE)

    clip1_path = OUTPUT_DIR / f"{name}_clip1.mp4"
    clip2_path = OUTPUT_DIR / f"{name}_clip2.mp4"
    endframe_path = OUTPUT_DIR / f"{name}_endframe.jpg"

    print(f"\n── {name} ──")

    generate_clip(clip1_prompt, source_url, clip1_path, f"{name} clip 1")
    extract_last_frame(clip1_path, endframe_path)
    endframe_url = upload(endframe_path)
    generate_clip(clip2_prompt, start_image_url=endframe_url,
                  output_path=clip2_path, label=f"{name} clip 2",
                  end_image_url=source_url)
    join_clips(clip1_path, clip2_path, loop_path)

    if loop_path.exists():
        size = loop_path.stat().st_size / 1024 / 1024
        print(f"\n  Done: {loop_path.name} ({size:.1f} MB)")
        print(f"\n  Add to FINAL_ORDER in generate_hair_loops.py:")
        print(f'    "loop_{name}.mp4",')
    else:
        print("\n  FAILED")

    print("=" * 55)


if __name__ == "__main__":
    main()
