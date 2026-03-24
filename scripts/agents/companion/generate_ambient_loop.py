#!/usr/bin/env python3
"""Generate modular ambient idle loops from source portrait via Kling 3.0 on Fal.

Each loop is two 5s clips crossfaded into a ~10s seamless segment.
All loops start and end on the source portrait, so they can be
chained in any order for variety.

15 segments × 10s = 150s = 2.5 minutes of unique loop content.

Requires: FAL_KEY in .env, ffmpeg installed, source image.
"""
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path.home() / ".atrophy" / ".env")

from config import AVATAR_DIR, IDLE_LOOPS_DIR

import fal_client
import httpx

SOURCE_IMAGE = AVATAR_DIR / "candidates" / "natural_02.png"
OUTPUT_DIR = IDLE_LOOPS_DIR

KLING_MODEL = "fal-ai/kling-video/v3/pro/image-to-video"

NEGATIVE_PROMPT = (
    "blur, distort, low quality, sudden movement, jump cut, morphing, "
    "face distortion, extra fingers, unnatural skin, plastic skin, "
    "uncanny valley, teeth showing too much, exaggerated expression"
)

C = """
Cinematic. 4K. Shallow depth of field. Warm ambient interior light, \
cool from the window. Static camera. No sudden movement."""

# Return prompt template - all Clip 2s follow the same structure
def return_prompt(start_description: str) -> str:
    return f"""\
Continuation. Same young woman, same light. She begins {start_description}.

Gradually, without rush, everything settles. Her gaze drifts to the \
middle distance. Expression smooths into open neutrality. Lips close \
softly. A quiet breath. Still.

By the final frame she is neutral - gaze middle-distance, expression \
open, mouth softly closed, breathing slowly.
{C}
FINAL FRAME: middle-distance gaze, neutral open expression, \
mouth softly closed. Matches the source portrait exactly.\
"""


SEGMENTS = [
    # ── 1. arrival ──
    (
        "01_arrival",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins in stillness: gaze middle-distance, expression \
open and neutral, lips softly closed. Simply present.

Something arrives - a recognition. The expression shifts at the edges: \
jaw softens, eyes settle into quieter focus. The corners of her mouth \
move toward a smile that never quite completes itself.

Her hair shifts slightly in an unseen draught.

By the final frame she is looking directly at the camera. Softly. Lips \
slightly parted. The ghost of that almost-smile still present.
{C}
FINAL FRAME: direct soft eye contact, lips slightly parted, \
trace of warmth at mouth corners.\
""",
        return_prompt("in direct soft eye contact with the camera - lips slightly parted, quiet warmth at her mouth corners"),
    ),

    # ── 2. smile ──
    (
        "02_smile",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

A thought crosses her mind - something privately amusing. Her eyes narrow \
slightly in a smize, the muscles around her eyes engaging before her mouth \
does. Then the smile arrives: not a grin, not performed. A real smile that \
reaches her eyes. Warm. Knowing.

She holds it - the kind of smile that says she's remembered something good. \
Her eyes catch the light. Cheeks lift naturally.

By the final frame she is smiling genuinely, eyes bright with a smize, \
looking slightly off-camera.
{C}
FINAL FRAME: genuine warm smile, smize engaged, eyes bright, \
cheeks naturally lifted.\
""",
        return_prompt("with a genuine warm smile, smize engaged, eyes bright"),
    ),

    # ── 3. hair tuck ──
    (
        "03_hair_tuck",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

She reaches up with one hand and tucks a strand of hair behind her ear - \
casual, absent-minded. Then her fingers move through her hair near the \
crown, a light ruffle. Her head tilts slightly. The hair falls back into \
place, catching the window light. She runs her fingers through the length \
once - not styling, just feeling.

By the final frame her hand is lowering, hair freshly displaced, \
a slight tilt to her head, expression soft and unguarded.
{C}
FINAL FRAME: hand lowering from hair, slight head tilt, hair \
catching light, expression soft.\
""",
        return_prompt("with her hand lowering from her hair, slight head tilt, expression soft"),
    ),

    # ── 4. presence ──
    (
        "04_presence",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

Her eyes shift toward something internal. A quiet intensity gathers. Her \
brow lowers almost imperceptibly - not a frown, focus. Her chin lifts \
slightly. A slow, deliberate blink. When her eyes open they are sharper, \
more present. She looks directly at the camera - assured. Knowing. The \
faintest narrowing of her eyes. A smize without the smile.

By the final frame she is holding steady eye contact. Quiet confidence. \
The look of someone who has decided something.
{C}
FINAL FRAME: direct eye contact, quiet intensity, chin slightly lifted, \
knowing expression, completely still.\
""",
        return_prompt("with direct eye contact, quiet intensity, knowing expression"),
    ),

    # ── 5. sigh ──
    (
        "05_sigh",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

A deep breath in - her chest rises visibly, shoulders lift slightly. She \
holds it for a moment. Then a long, slow exhale through parted lips. Her \
shoulders drop. Her whole body settles lower, heavier, more present. The \
exhale carries something with it - not sadness, release. The kind of sigh \
that means she's finally stopped holding something.

Her eyes soften. Her jaw unclenches. She sinks slightly into wherever \
she's sitting.

By the final frame she is more relaxed than she started - eyes half-lidded, \
lips slightly parted from the exhale, deeply settled.
{C}
FINAL FRAME: deeply relaxed, eyes half-lidded, lips slightly parted, \
shoulders dropped, settled.\
""",
        return_prompt("deeply relaxed, eyes half-lidded, lips slightly parted, shoulders dropped"),
    ),

    # ── 6. amusement ──
    (
        "06_amusement",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

Something strikes her as funny. Not a joke - an observation. The kind of \
thing that's only amusing if you see it from exactly the right angle. Her \
lips press together, suppressing it. Her eyes widen slightly. The laugh \
tries to escape through her nose - a small huff of air. She loses the \
battle: a quick, quiet laugh breaks through, her shoulders shaking once.

She bites her lower lip briefly, composing herself. The amusement stays \
in her eyes even as her mouth settles.

By the final frame she's biting back the last of it - eyes bright, the \
ghost of a laugh still in her expression.
{C}
FINAL FRAME: eyes bright with amusement, lips pressed together \
suppressing a smile, slight shake in the shoulders.\
""",
        return_prompt("with bright amused eyes, lips pressed together suppressing a smile"),
    ),

    # ── 7. glance ──
    (
        "07_glance",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

Something catches her attention to one side - a sound, a movement, a shift \
in the light. Her eyes move first, then her head follows with a slight turn. \
Not alarmed. Curious. She looks at something off-camera for a moment, her \
expression open and attentive.

Whatever it was resolves. She blinks. Her attention softens. She begins \
to turn back.

By the final frame she is mid-return, gaze coming back toward centre, \
expression curious and open, head slightly turned.
{C}
FINAL FRAME: head slightly turned, gaze returning to centre, \
expression open and curious.\
""",
        return_prompt("with her head slightly turned, gaze returning to centre, expression curious"),
    ),

    # ── 8. eyes closed ──
    (
        "08_eyes_closed",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

Her eyelids grow heavy. A slow blink that doesn't fully reopen - her eyes \
close and stay closed. Not sleeping. Resting. The kind of eyes-closed that \
means she's feeling something inward. Her face is completely relaxed. Jaw \
soft. Lips barely parted.

A breath moves through her. The light from the window plays across her \
closed eyelids. She is still.

By the final frame her eyes are peacefully closed, face completely at rest, \
bathed in soft window light.
{C}
FINAL FRAME: eyes closed, face completely at rest, peaceful, \
lips barely parted, bathed in light.\
""",
        return_prompt("with her eyes peacefully closed, face completely at rest"),
    ),

    # ── 9. hair flip ──
    (
        "09_hair_flip",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

She tilts her head to one side, then sweeps her hair back over her \
shoulder with one hand - a fluid, casual gesture. The hair catches \
the light as it moves, blonde strands fanning briefly. She shakes \
her head once, gently, settling the hair into place.

Her hand lingers near her collarbone for a moment before dropping. \
The movement was entirely unselfconscious.

By the final frame her hair is resettled over one shoulder, her hand \
near her collarbone, head still slightly tilted, expression easy.
{C}
FINAL FRAME: hair swept back over shoulder, hand near collarbone, \
slight head tilt, relaxed expression.\
""",
        return_prompt("with hair swept over one shoulder, hand near collarbone, slight head tilt"),
    ),

    # ── 10. tease ──
    (
        "10_tease",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

One eyebrow lifts - just slightly. The beginning of something. Then a \
slow, asymmetric smile: one corner of her mouth rises more than the other. \
Playful. Not performing - genuinely amused by something, or someone. Her \
eyes narrow into a slight smize. She holds the look, chin tilting down \
just a fraction, looking up through her lashes.

The expression says: I know something you don't.

By the final frame she holds that one-sided smile, eyebrow slightly raised, \
looking directly at camera through her lashes.
{C}
FINAL FRAME: asymmetric smile, one eyebrow raised, looking through \
lashes at camera, playful knowing expression.\
""",
        return_prompt("with an asymmetric playful smile, eyebrow raised, looking through her lashes"),
    ),

    # ── 11. light shift ──
    (
        "11_light",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

The light from the window shifts - a cloud passing, or the sun moving. \
Warmer light spills across her face. She notices. Her eyes move toward \
the window. She turns her face slightly into the light, eyes closing \
halfway, the way you might lean into warmth on a cool day.

The light catches the honey tones in her hair. Her skin warms. She \
stays there for a moment, absorbing it.

By the final frame she is turned slightly toward the window, eyes \
half-closed, face bathed in warm light, expression of simple pleasure.
{C}
FINAL FRAME: face turned toward window, eyes half-closed, warm light \
across features, expression of quiet pleasure.\
""",
        return_prompt("turned slightly toward the window, eyes half-closed, warm light on her face"),
    ),

    # ── 12. chin rest ──
    (
        "12_chin_rest",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

She brings one hand up and rests her chin on it - elbow on something \
below frame. A thinking posture. Her fingers curl loosely against her \
jaw. Her eyes move slightly as if following a thought. She shifts the \
weight of her head in her hand once, settling.

The gesture is natural, unhurried. She could stay like this for a while.

By the final frame she is resting her chin on her hand, eyes thoughtful, \
gaze middle-distance, completely at ease.
{C}
FINAL FRAME: chin resting on hand, fingers against jaw, thoughtful \
expression, gaze middle-distance, at ease.\
""",
        return_prompt("resting her chin on her hand, thoughtful expression, at ease"),
    ),

    # ── 13. stretch ──
    (
        "13_stretch",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

She rolls her neck slowly - chin dropping toward one shoulder, then \
sweeping across and up to the other side. Her eyes close during the \
movement. A small, private relief. Her shoulders rise toward her ears \
and then drop with an exhale. The kind of micro-stretch that happens \
when you've been still too long.

Her head settles back to centre. She opens her eyes.

By the final frame her neck has completed its roll, shoulders have \
dropped, she looks refreshed, eyes open and clear.
{C}
FINAL FRAME: head centred, shoulders dropped and relaxed, eyes open \
and clear, slightly refreshed expression.\
""",
        return_prompt("with her head centred, shoulders relaxed, eyes open and clear, slightly refreshed"),
    ),

    # ── 14. wistful ──
    (
        "14_wistful",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

Something crosses her mind - a memory, maybe. Her eyes soften and go \
slightly distant. Not sad. The kind of remembering that is warm and far \
away at the same time. Her head tilts slightly. The corners of her mouth \
move but can't decide between a smile and something else.

Her fingers move absently - touching her necklace, a small unconscious \
gesture. She's somewhere else for a moment.

By the final frame her expression is soft and distant, touched by \
something from another time, fingers near her necklace.
{C}
FINAL FRAME: soft distant expression, slightly wistful, fingers \
near necklace, head slightly tilted, far away.\
""",
        return_prompt("with a soft distant expression, slightly wistful, fingers near her necklace"),
    ),

    # ── 15. direct ──
    (
        "15_direct",
        f"""\
A young woman with blonde hair sits in soft natural light near a window. \
Grey-green eyes. She begins neutral, gaze middle-distance, lips softly closed.

Without preamble her gaze shifts directly to the camera. Not the soft \
arrival of recognition - something more direct. She sees you. Her \
expression doesn't change much - maybe a millimetre of movement at the \
mouth, the hint of acknowledgment. But the eyes do all the work: steady, \
clear, present. Fully here.

She holds the look. Unhurried. Not challenging, not warm. Just: I see you.

By the final frame she is looking straight at camera with complete \
presence. Expression minimal but alive. Steady.
{C}
FINAL FRAME: direct steady eye contact, minimal expression, completely \
present, unhurried, alive.\
""",
        return_prompt("looking directly at camera with steady presence, minimal expression"),
    ),
]


def upload(path: Path) -> str:
    print(f"  Uploading {path.name}...", end="", flush=True)
    url = fal_client.upload_file(path)
    print(" done")
    return url


def generate_clip(
    prompt: str,
    start_image_url: str,
    output_path: Path,
    label: str,
    end_image_url: str = None,
):
    if output_path.exists():
        print(f"  {label}: exists - skipping")
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


def extract_last_frame(video_path: Path, output_path: Path):
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


def join_clips(clip1: Path, clip2: Path, output: Path):
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


def generate_segment(name: str, clip1_prompt: str, clip2_prompt: str, source_url: str) -> Path:
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


def concat_all_loops(loop_paths: list[Path], output: Path):
    if output.exists():
        print(f"  Master already exists: {output.name}")
        return

    concat_list = OUTPUT_DIR / "concat_list.txt"
    with open(concat_list, "w") as f:
        for p in loop_paths:
            f.write(f"file '{p}'\n")

    print("  Concatenating all segments...", end="", flush=True)
    subprocess.run(
        ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(output)],
        capture_output=True, timeout=300,
    )
    concat_list.unlink(missing_ok=True)

    if output.exists():
        size = output.stat().st_size / 1024 / 1024
        print(f" done ({size:.1f} MB)")
    else:
        print(" FAILED")


BATCH_SIZE = 2


def main():
    if not SOURCE_IMAGE.exists():
        print(f"Error: Source image not found at {SOURCE_IMAGE}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Check what's already done
    pending = []
    done = []
    for name, c1, c2 in SEGMENTS:
        loop_path = OUTPUT_DIR / f"loop_{name}.mp4"
        if loop_path.exists():
            done.append(name)
        else:
            pending.append((name, c1, c2))

    total_clips = len(SEGMENTS) * 2
    est_cost = len(pending) * 2 * 0.15
    total_time = len(SEGMENTS) * 10

    print("=" * 55)
    print("  Ambient Loop Generator - Kling 3.0 on Fal")
    print(f"  Source:    {SOURCE_IMAGE.name}")
    print(f"  Segments:  {len(SEGMENTS)} × ~10s = ~{total_time}s total")
    print(f"  Done:      {len(done)}/{len(SEGMENTS)}")
    print(f"  Remaining: {len(pending)} (est. ${est_cost:.2f})")
    print("=" * 55)

    if not pending:
        print("\n  All segments already generated.")
        _rebuild_master()
        return

    print(f"\n  Will generate in batches of {BATCH_SIZE}.")
    print(f"  Remaining: {', '.join(n for n, _, _ in pending)}")

    source_url = upload(SOURCE_IMAGE)

    generated = list(done)
    for batch_start in range(0, len(pending), BATCH_SIZE):
        batch = pending[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(pending) + BATCH_SIZE - 1) // BATCH_SIZE

        print(f"\n{'=' * 55}")
        print(f"  Batch {batch_num}/{total_batches}: {', '.join(n for n, _, _ in batch)}")
        confirm = input("  Generate? [y/N/q] ").strip().lower()
        if confirm == "q" or confirm == "n":
            print("  Stopping. Run again to continue from here.")
            break
        if confirm != "y":
            print("  Stopping. Run again to continue from here.")
            break

        for name, clip1_prompt, clip2_prompt in batch:
            idx = next(i for i, (n, _, _) in enumerate(SEGMENTS) if n == name) + 1
            print(f"\n── Segment {idx}/{len(SEGMENTS)}: {name} ──")
            try:
                loop_path = generate_segment(name, clip1_prompt, clip2_prompt, source_url)
                generated.append(name)
                print(f"  ✓ {loop_path.name}")
            except Exception as e:
                print(f"  ✗ {name} FAILED: {e}")
                continue

    _rebuild_master()

    print()
    print("=" * 55)
    total_done = sum(1 for n, _, _ in SEGMENTS if (OUTPUT_DIR / f"loop_{n}.mp4").exists())
    print(f"  Completed: {total_done}/{len(SEGMENTS)} segments")
    if total_done < len(SEGMENTS):
        print("  Run again to generate remaining segments.")
    print(f"  Output: {OUTPUT_DIR}/")
    print("=" * 55)


def _rebuild_master():
    """Rebuild master loop from all existing segments."""
    loop_paths = []
    for name, _, _ in SEGMENTS:
        p = OUTPUT_DIR / f"loop_{name}.mp4"
        if p.exists():
            loop_paths.append(p)

    if not loop_paths:
        return

    master_path = OUTPUT_DIR / "ambient_loop_full.mp4"
    # Always rebuild master to include new segments
    master_path.unlink(missing_ok=True)
    print(f"\n── Master Loop ({len(loop_paths)} segments) ──")
    concat_all_loops(loop_paths, master_path)


if __name__ == "__main__":
    main()
