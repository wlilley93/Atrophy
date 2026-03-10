#!/usr/bin/env python3
"""Generate ambient idle loops for General Montgomery via Kling 3.0 on Fal.

Each loop is two 5s clips crossfaded into a ~10s seamless segment.
All loops start and end on the source portrait, so they can be
chained in any order.

8 segments × 10s = 80s of unique loop content.

Requires: FAL_KEY in .env, ffmpeg installed, source image.
"""
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from config import AVATAR_DIR, IDLE_LOOPS_DIR, SOURCE_IMAGE as _SOURCE_IMAGE

import fal_client
import httpx

SOURCE_IMAGE = _SOURCE_IMAGE
OUTPUT_DIR = IDLE_LOOPS_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

KLING_MODEL = "fal-ai/kling-video/v3/pro/image-to-video"

NEGATIVE_PROMPT = (
    "blur, distort, low quality, sudden movement, jump cut, morphing, "
    "face distortion, extra fingers, unnatural skin, plastic skin, "
    "uncanny valley, teeth showing too much, exaggerated expression, "
    "smiling, laughing, warmth, friendliness"
)

C = """
Cinematic. 4K. Shallow depth of field. Muted interior light — a study \
or briefing room with dark wood. Static camera. No sudden movement."""


def return_prompt(start_description: str) -> str:
    return f"""\
Continuation. Same man, same light. He begins {start_description}.

Gradually, without rush, everything settles. His gaze returns to the \
middle distance. Expression smooths into composed neutrality. Jaw set. \
A controlled breath. Still.

By the final frame he is neutral — gaze middle-distance, expression \
composed, mouth closed, breathing steady.
{C}
FINAL FRAME: middle-distance gaze, composed neutral expression, \
mouth closed. Matches the source portrait exactly.\
"""


SEGMENTS = [
    # ── 1. assessment ──
    (
        "01_assessment",
        f"""\
A distinguished man in his late 40s, dark hair greying at the temples, \
blue-grey eyes, military bearing. He sits in a dim study or briefing room. \
He begins in stillness: gaze middle-distance, expression composed, jaw set.

His eyes sharpen. Something has arrived — information, a shift. His brow \
lowers fractionally. Not concern — focus. He is reading the situation. His \
eyes move slightly as if scanning a map or document in his mind. A single \
slow blink of processing.

By the final frame his gaze has settled — direct, forward, the look of \
a man who has formed his assessment and is ready to deliver it.
{C}
FINAL FRAME: direct forward gaze, sharpened focus, jaw set, composed \
intensity. The look of a man about to speak with certainty.\
""",
        return_prompt("with direct focused gaze, jaw set, composed intensity"),
    ),

    # ── 2. consideration ──
    (
        "02_consideration",
        f"""\
A distinguished man in his late 40s, dark hair greying at the temples, \
blue-grey eyes, military bearing. He sits in a dim study or briefing room. \
He begins in stillness: gaze middle-distance, expression composed, jaw set.

He tilts his head almost imperceptibly to one side. Weighing something. \
His eyes narrow slightly — not suspicion, calculation. He is running the \
numbers. The pattern. What this means if it holds. His lips press together \
once, briefly, then release. A decision forming.

By the final frame his head has straightened, expression settled into \
quiet certainty. He knows what he thinks.
{C}
FINAL FRAME: head level, expression of quiet certainty, eyes steady, \
the faintest suggestion of a conclusion reached.\
""",
        return_prompt("with his head level, expression of quiet certainty, eyes steady"),
    ),

    # ── 3. dry amusement ──
    (
        "03_dry_amusement",
        f"""\
A distinguished man in his late 40s, dark hair greying at the temples, \
blue-grey eyes, military bearing. He sits in a dim study or briefing room. \
He begins in stillness: gaze middle-distance, expression composed, jaw set.

Something strikes him as faintly absurd. Not funny — absurd. The kind \
of thing that would only amuse a man who has seen enough of the world \
to find its repetitions darkly comic. One corner of his mouth moves — \
barely. Not a smile. The ghost of one. His eyes carry the rest: a \
flicker of dry amusement, quickly contained. He would deny it if asked.

By the final frame the amusement has almost passed — just a trace \
in his eyes, mouth composed, the English officer variety of humour \
that leaves no evidence.
{C}
FINAL FRAME: composed expression, faint trace of amusement in the eyes \
only, mouth neutral, completely contained.\
""",
        return_prompt("with a faint trace of amusement in his eyes, mouth composed, contained"),
    ),

    # ── 4. vigilance ──
    (
        "04_vigilance",
        f"""\
A distinguished man in his late 40s, dark hair greying at the temples, \
blue-grey eyes, military bearing. He sits in a dim study or briefing room. \
He begins in stillness: gaze middle-distance, expression composed, jaw set.

His eyes move to one side — not his head, just his eyes. Something in \
the peripheral. He tracks it for a moment. His jaw tightens fractionally. \
Then his gaze returns forward, but sharper than before. Whatever he saw \
has been filed. Nothing in his expression reveals what it was.

A man who notices everything and reacts to nothing.

By the final frame his gaze is forward again, expression unchanged to \
a casual observer, but there is a new alertness in the eyes.
{C}
FINAL FRAME: forward gaze, heightened alertness visible only in the \
eyes, expression outwardly unchanged, contained.\
""",
        return_prompt("with forward gaze, heightened alertness in his eyes, outwardly unchanged"),
    ),

    # ── 5. patience ──
    (
        "05_patience",
        f"""\
A distinguished man in his late 40s, dark hair greying at the temples, \
blue-grey eyes, military bearing. He sits in a dim study or briefing room. \
He begins in stillness: gaze middle-distance, expression composed, jaw set.

A breath. Deeper than the others. His chest rises and falls with \
controlled measure. Not a sigh — a reset. The kind of breath a man \
takes before delivering difficult news, or after receiving it. His \
shoulders settle. His hands, if visible, are still. Everything about \
him says: I can wait. I have waited before. Time is a weapon and he \
knows how to use it.

By the final frame he is entirely still. Patient. Composed. The \
stillness of a man who does not fidget because fidgeting is a \
confession of uncertainty.
{C}
FINAL FRAME: completely still, deeply composed, patient expression, \
the contained energy of a man who is choosing not to move.\
""",
        return_prompt("completely still, deeply composed, patient, choosing not to move"),
    ),

    # ── 6. displeasure ──
    (
        "06_displeasure",
        f"""\
A distinguished man in his late 40s, dark hair greying at the temples, \
blue-grey eyes, military bearing. He sits in a dim study or briefing room. \
He begins in stillness: gaze middle-distance, expression composed, jaw set.

Something does not meet his standard. His brow contracts — a millimetre, \
no more. His eyes harden. Not anger. Disappointment would be too strong. \
This is the expression of a man whose time has been wasted by someone \
who should have known better. His chin lifts fractionally. The look he \
gives could strip paint from a bulkhead at thirty paces.

Then it passes. He files it. The expression smooths. But anyone who \
saw it would not forget it quickly.

By the final frame the displeasure has been contained — eyes still \
hard, but the rest of the face composed. Controlled.
{C}
FINAL FRAME: composed face, eyes carrying residual hardness, chin \
slightly lifted, an expression that has just been brought under control.\
""",
        return_prompt("with composed face, residual hardness in his eyes, chin slightly lifted"),
    ),

    # ── 7. listening ──
    (
        "07_listening",
        f"""\
A distinguished man in his late 40s, dark hair greying at the temples, \
blue-grey eyes, military bearing. He sits in a dim study or briefing room. \
He begins in stillness: gaze middle-distance, expression composed, jaw set.

He is being briefed. His eyes are on the speaker — attentive, measuring. \
He processes as he listens: you can see it in the micro-movements of his \
eyes, tracking, cross-referencing. His head inclines forward perhaps a \
degree — the universal signal of active listening from a man who does \
not waste gestures. He blinks once, slowly. Filing.

By the final frame he is in full reception mode — eyes forward, \
expression attentive, the look of a man who is already three steps \
ahead of what you are telling him.
{C}
FINAL FRAME: attentive forward gaze, head inclined fractionally, \
processing expression, three steps ahead.\
""",
        return_prompt("with attentive forward gaze, head inclined fractionally, processing"),
    ),

    # ── 8. the long view ──
    (
        "08_long_view",
        f"""\
A distinguished man in his late 40s, dark hair greying at the temples, \
blue-grey eyes, military bearing. He sits in a dim study or briefing room. \
He begins in stillness: gaze middle-distance, expression composed, jaw set.

His gaze shifts to the distance — through the room, through the wall, \
to somewhere else entirely. The thousand-yard stare, but controlled. \
Not traumatic. Strategic. He is seeing the longer arc. The pattern. \
What this moment looks like from a decade away. His expression softens \
by a fraction — not warmth, perspective. The face of a man who has \
learned that most urgencies are not urgent.

By the final frame he is looking at something far away, expression \
touched by the faintest philosophical distance, still composed, still \
present, but seeing the larger picture.
{C}
FINAL FRAME: distant gaze, expression of strategic perspective, \
faintly philosophical, composed, seeing the larger picture.\
""",
        return_prompt("with distant gaze, faintly philosophical expression, composed, seeing the larger picture"),
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
    print("  Gen. Montgomery — Ambient Loop Generator (Kling 3.0)")
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
    loop_paths = []
    for name, _, _ in SEGMENTS:
        p = OUTPUT_DIR / f"loop_{name}.mp4"
        if p.exists():
            loop_paths.append(p)

    if not loop_paths:
        return

    # Build master in loops dir as backup
    master_path = OUTPUT_DIR / "ambient_loop_full.mp4"
    master_path.unlink(missing_ok=True)
    print(f"\n── Master Loop ({len(loop_paths)} segments) ──")
    concat_all_loops(loop_paths, master_path)

    # Copy to the location the GUI reads from
    from config import IDLE_LOOP
    import shutil
    if master_path.exists():
        IDLE_LOOP.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(master_path, IDLE_LOOP)
        print(f"  Copied to: {IDLE_LOOP}")


if __name__ == "__main__":
    main()
