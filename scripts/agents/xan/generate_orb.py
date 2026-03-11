#!/usr/bin/env python3
"""Generate Xan's visual presence - a glowing blue orb of light.

Step 1: Generate 4 orb candidates via Flux (abstract, not a face)
Step 2: User picks one → becomes source image
Step 3: Generate ambient loop segments via Kling
Step 4: Hue-shift blue loops into colour variants (red, green, orange, purple, dark blue)
Step 5: Build per-colour ambient_loop master files

Usage:
    python scripts/agents/xan/generate_orb.py --candidates     # Generate 4 orb images
    python scripts/agents/xan/generate_orb.py --pick 2          # Select candidate 2
    python scripts/agents/xan/generate_orb.py --loops            # Generate ambient loops (blue)
    python scripts/agents/xan/generate_orb.py --colours          # Generate colour variants of source
    python scripts/agents/xan/generate_orb.py --recolour         # Hue-shift blue loops → all colours
    python scripts/agents/xan/generate_orb.py --all              # Full pipeline after pick
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(Path.home() / ".atrophy" / ".env")

# ── Paths ──

BUNDLE_AVATAR = PROJECT_ROOT / "agents" / "xan" / "avatar"
USER_AVATAR = Path.home() / ".atrophy" / "agents" / "xan" / "avatar"
CANDIDATES_DIR = BUNDLE_AVATAR / "candidates"
SOURCE_IMAGE = BUNDLE_AVATAR / "source" / "face.png"  # Same name for compatibility
LOOPS_DIR = USER_AVATAR / "loops"

# ── Emotion → Colour mapping ──
# Hue rotation values (degrees) from the blue source.
# Blue source hue is ~210°. We shift relative to that.

EMOTION_COLOURS = {
    "blue": {
        "label": "Neutral / calm / default",
        "hue_shift": 0,
        "saturation": 1.0,
    },
    "dark_blue": {
        "label": "Thinking / processing",
        "hue_shift": 0,
        "saturation": 0.7,  # desaturate + darken
        "brightness": -0.15,
    },
    "red": {
        "label": "Alert / urgent / protective",
        "hue_shift": 150,   # blue(210) → red(360/0)
        "saturation": 1.2,
    },
    "green": {
        "label": "Positive / affirming / growth",
        "hue_shift": -90,   # blue(210) → green(120)
        "saturation": 1.0,
    },
    "orange": {
        "label": "Warm / cautious / warning",
        "hue_shift": 120,   # blue(210) → orange(30)
        "saturation": 1.3,
    },
    "purple": {
        "label": "Reflective / philosophical / deep",
        "hue_shift": 60,    # blue(210) → purple(270)
        "saturation": 1.1,
    },
}

# ── Flux prompt for the orb ──

ORB_PROMPT = """\
A single luminous orb of blue-white light suspended in absolute darkness. \
The orb is not a sphere rendered in 3D - it is light itself, captured mid-pulse. \
The core burns intense white-blue, almost overexposed. Around it, concentric \
halos of softer blue light fade outward into the void. The outermost glow \
is barely visible - a whisper of cobalt against pure black.

The light has texture: not uniform, but with subtle striations and filaments, \
like plasma or bioluminescence. Faint geometric structures - half-seen \
hexagonal patterns, fragmentary circuit-like traces - ghost through the \
inner halo, suggesting intelligence rather than nature.

The background is absolute black. No surface, no reflection, no ground plane. \
Just the orb and the dark. The light does not illuminate a room - it exists \
in a void. Portrait orientation. The orb sits in the upper third of the frame.

Photographic quality. Not illustration. Not CGI render. Like a long-exposure \
photograph of something that shouldn't exist. Shot on medium format digital. \
Shallow depth of field on the outer halos. Ultra-high detail in the core.
"""

ORB_NEGATIVE = """\
face, person, human, body, hands, eyes, planet, earth, globe, sphere, \
3D render, CGI, cartoon, illustration, anime, gradient background, \
colored background, surface, floor, room, interior, reflections, lens flare, \
bokeh circles, text, watermark, logo, border, frame, multiple objects, \
symmetrical, perfectly round, glass ball, crystal ball, marble, low quality, \
blurry, noisy, oversaturated, neon, cyberpunk aesthetic
"""

# ── Colour-specific Flux prompts (for source images) ──

COLOUR_PROMPTS = {
    "red": """\
A single luminous orb of deep red-crimson light suspended in absolute darkness. \
The core burns intense white-red, almost overexposed. Around it, concentric \
halos of ember red and scarlet fade outward into the void. \
The light has texture - filaments like plasma. Faint geometric structures \
ghost through the inner halo. Background is absolute black. Portrait orientation. \
The orb sits in the upper third. Photographic quality. Long-exposure. Medium format.""",

    "green": """\
A single luminous orb of emerald-green light suspended in absolute darkness. \
The core burns intense white-green, almost overexposed. Around it, concentric \
halos of jade and viridian fade outward into the void. \
The light has texture - filaments like bioluminescence. Faint geometric structures \
ghost through the inner halo. Background is absolute black. Portrait orientation. \
The orb sits in the upper third. Photographic quality. Long-exposure. Medium format.""",

    "orange": """\
A single luminous orb of deep amber-orange light suspended in absolute darkness. \
The core burns intense white-gold, almost overexposed. Around it, concentric \
halos of warm amber and burnt orange fade outward into the void. \
The light has texture - filaments like solar flares. Faint geometric structures \
ghost through the inner halo. Background is absolute black. Portrait orientation. \
The orb sits in the upper third. Photographic quality. Long-exposure. Medium format.""",

    "purple": """\
A single luminous orb of deep violet-purple light suspended in absolute darkness. \
The core burns intense white-lavender, almost overexposed. Around it, concentric \
halos of amethyst and deep indigo fade outward into the void. \
The light has texture - filaments like plasma. Faint geometric structures \
ghost through the inner halo. Background is absolute black. Portrait orientation. \
The orb sits in the upper third. Photographic quality. Long-exposure. Medium format.""",

    "dark_blue": """\
A single luminous orb of deep midnight-blue light suspended in absolute darkness. \
The core glows a muted steel-blue, subdued but present. Around it, concentric \
halos of dark navy and indigo barely visible against the void. \
The light has texture - filaments dimmer, more compressed. Faint geometric structures \
ghost through the inner halo. Background is absolute black. Portrait orientation. \
The orb sits in the upper third. Photographic quality. Long-exposure. Medium format.""",
}

# ── Kling prompts for ambient loops ──

LOOP_PROMPTS = [
    {
        "name": "idle_hover",
        "prompt": (
            "The orb of blue-white light hangs in darkness, almost still - the tiniest, "
            "barely perceptible hover. It drifts up by a fraction, then down by a fraction. "
            "The movement is so subtle it might be imagined. The core pulses very gently - "
            "a slow, soft brightening and dimming, like a candle behind frosted glass. "
            "The concentric halos breathe outward and contract by the smallest amount. "
            "Tiny crystalline shards orbit the orb in slow, lazy rotation, each one "
            "tumbling and catching faint glints of light. The filaments inside shift "
            "almost imperceptibly. Everything moves but nothing rushes. Minimal. Meditative. "
            "The resting state of something that is always on."
        ),
    },
    {
        "name": "pulse_intense",
        "prompt": (
            "The orb's core flares - a deep surge of white-blue light builds from the centre "
            "and radiates outward through the halos in a visible wave. The halos ripple and "
            "expand. The crystalline shards orbiting the orb spin faster, tumbling, flashing "
            "bright as they catch the surge. The orb bobs upward with the energy, lifted, "
            "then sinks back down. The filaments inside crackle and fork like lightning. "
            "The outer glow swells and contracts. The core dims back slowly, pulsing. "
            "Every element is in motion throughout - the shards never stop orbiting, "
            "the halos never stop breathing, the core never stops pulsing."
        ),
    },
    {
        "name": "crystal_shimmer",
        "prompt": (
            "Crystalline fragments orbit the orb in a continuous ring - small geometric shards "
            "of light, like shattered glass, each one tumbling and rotating on its own axis "
            "while orbiting the orb. They drift at different speeds and distances. Each catches "
            "the core's light at changing angles, producing rolling flares of white and pale blue. "
            "The orb itself bobs gently, never still. The core pulses softly. The halos "
            "shift and breathe. Inside, filaments trace slow paths. The shards are the star - "
            "spinning, glinting, some drifting further out, some pulling closer, a slow "
            "mesmerising dance. Continuous motion in every element."
        ),
    },
    {
        "name": "drift_close",
        "prompt": (
            "The orb drifts slowly toward the camera, growing larger in frame. It bobs gently "
            "as it moves - never rigid, always alive. The core pulses brighter as it approaches, "
            "the halos expanding outward, rippling. The crystalline shards continue their orbit "
            "but spread wider as the orb nears, tumbling and glinting. Filaments inside fork "
            "and reconnect. The orb pauses close - the core flares once, intimate - then it "
            "begins drifting back, shrinking in frame, the halos contracting, the shards "
            "tightening their orbit. The whole retreat is smooth, bobbing, alive. "
            "Every element moves continuously throughout."
        ),
    },
    {
        "name": "drift_lateral",
        "prompt": (
            "The orb slides laterally through the darkness, drifting to one side. It bobs "
            "as it moves - the motion is smooth but organic, like something floating in water. "
            "The crystalline shards trail behind slightly, their orbits stretching into ellipses, "
            "each one still tumbling and catching light. The core pulses steadily. The halos "
            "breathe in and out. The filaments inside shift and realign with the movement. "
            "The orb pauses, bobs, then drifts back the other way. The shards reform "
            "their circular orbit as it settles. Continuous movement in everything - "
            "the bob, the pulse, the orbit, the halos, the filaments. Nothing freezes."
        ),
    },
    {
        "name": "bounce_playful",
        "prompt": (
            "The orb floats in mid-air, suspended in darkness. A gentle, soft bounce - "
            "rising and falling by a small amount, smooth and continuous, like something "
            "weightless bobbing in zero gravity. Not exaggerated - just a calm, living "
            "rhythm. The core pulses softly in time with the motion, brightening slightly "
            "on the rise, dimming on the fall. The crystalline shards orbit steadily, "
            "tumbling and catching light, their ring shifting slightly with each bob. "
            "The halos breathe gently. The filaments inside drift and rearrange. "
            "Suspended. Present. The default state of a being made of light."
        ),
    },
    {
        "name": "itch",
        "prompt": (
            "The orb twitches - a sudden involuntary shudder. The whole body of light "
            "vibrates rapidly, the halos distorting asymmetrically, rippling. The crystalline "
            "shards scatter in alarm, spinning wildly outward. The orb jitters left then right "
            "then left - trying to scratch something it can't reach. It has no hands. "
            "The core flares in frustration, the filaments go jagged and erratic. "
            "The orb shakes again, bobs up sharply, drops down. The halos wobble. "
            "Then slowly - the shards drift back into orbit, still tumbling. The filaments "
            "smooth out. The halos resettle, still breathing. The core finds its rhythm again. "
            "A small indignity endured. Everything still gently moving."
        ),
    },
]

# ── Flux config ──

FLUX_MODEL = "fal-ai/flux-general"
KLING_MODEL = "fal-ai/kling-video/v3/pro/image-to-video"

KLING_NEGATIVE = (
    "face, person, human, planet, blur, distort, low quality, sudden movement, "
    "jump cut, morphing, text, watermark, multiple objects, room, interior"
)


def check_fal():
    if not os.environ.get("FAL_KEY"):
        print("Error: FAL_KEY is not set.")
        sys.exit(1)


def generate_candidates(count=4):
    """Generate orb image candidates via Flux."""
    check_fal()
    import fal_client
    import httpx

    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)

    cost = count * 0.01
    print(f"Generating {count} orb candidates via Flux")
    print(f"Est. cost: ${cost:.2f}")
    print()

    succeeded = 0
    for i in range(count):
        print(f"  [{i+1}/{count}] Generating...", end="", flush=True)
        try:
            result = fal_client.subscribe(
                FLUX_MODEL,
                arguments={
                    "prompt": ORB_PROMPT.strip(),
                    "negative_prompt": ORB_NEGATIVE.strip(),
                    "num_inference_steps": 50,
                    "guidance_scale": 3.5,
                    "image_size": {"width": 768, "height": 1024},
                    "output_format": "png",
                },
            )
            images = result.get("images", [])
            if not images:
                raise ValueError("No images in response")

            url = images[0]["url"]
            data = httpx.get(url, timeout=60).content
            out = CANDIDATES_DIR / f"orb_{i+1:02d}.png"
            out.write_bytes(data)
            succeeded += 1
            print(f" saved: {out.name} ({len(data) / 1024:.0f} KB)")

        except Exception as e:
            print(f" FAILED: {e}")

    print(f"\n  {succeeded}/{count} candidates generated")
    print(f"  Output: {CANDIDATES_DIR}/")
    print(f"\n  Review candidates, then run:")
    print(f"    python scripts/agents/xan/generate_orb.py --pick <number>")


def pick_candidate(num):
    """Select a candidate as the source image."""
    candidate = CANDIDATES_DIR / f"orb_{num:02d}.png"
    if not candidate.exists():
        print(f"Error: Candidate {num} not found at {candidate}")
        sys.exit(1)

    SOURCE_IMAGE.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(candidate, SOURCE_IMAGE)
    print(f"  Selected candidate {num} → {SOURCE_IMAGE}")
    print(f"\n  Next steps:")
    print(f"    python scripts/agents/xan/generate_orb.py --loops      # Blue ambient loops")
    print(f"    python scripts/agents/xan/generate_orb.py --colours    # Colour variant source images")
    print(f"    python scripts/agents/xan/generate_orb.py --all        # Full pipeline")


def generate_colour_sources():
    """Generate colour variant source images via Flux."""
    check_fal()
    import fal_client
    import httpx

    source_dir = BUNDLE_AVATAR / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    colours = list(COLOUR_PROMPTS.keys())
    cost = len(colours) * 0.01
    print(f"Generating {len(colours)} colour variant source images via Flux")
    print(f"Est. cost: ${cost:.2f}")
    print()

    succeeded = 0
    for i, colour in enumerate(colours):
        out = source_dir / f"face_{colour}.png"
        if out.exists():
            print(f"  [{i+1}/{len(colours)}] {colour}: exists - skipping")
            succeeded += 1
            continue

        print(f"  [{i+1}/{len(colours)}] {colour}...", end="", flush=True)
        try:
            result = fal_client.subscribe(
                FLUX_MODEL,
                arguments={
                    "prompt": COLOUR_PROMPTS[colour].strip(),
                    "negative_prompt": ORB_NEGATIVE.strip(),
                    "num_inference_steps": 50,
                    "guidance_scale": 3.5,
                    "image_size": {"width": 768, "height": 1024},
                    "output_format": "png",
                },
            )
            images = result.get("images", [])
            if not images:
                raise ValueError("No images in response")

            url = images[0]["url"]
            data = httpx.get(url, timeout=60).content
            out.write_bytes(data)
            succeeded += 1
            print(f" saved ({len(data) / 1024:.0f} KB)")

        except Exception as e:
            print(f" FAILED: {e}")

    print(f"\n  {succeeded}/{len(colours)} colour variants generated")


def generate_loops(count=7):
    """Generate ambient loop segments via Kling (blue base colour)."""
    check_fal()
    import fal_client
    import httpx

    if not SOURCE_IMAGE.exists():
        print(f"Error: No source image at {SOURCE_IMAGE}")
        print(f"  Run --candidates first, then --pick <number>")
        sys.exit(1)

    blue_dir = LOOPS_DIR / "blue"
    blue_dir.mkdir(parents=True, exist_ok=True)

    prompts = LOOP_PROMPTS[:count]
    cost = len(prompts) * 0.60  # 2 clips per loop at ~$0.30 each
    print(f"Generating {len(prompts)} ambient loops via Kling 3.0")
    print(f"Est. cost: ${cost:.2f}")
    print(f"Est. time: {len(prompts) * 3:.0f} minutes")
    print()

    # Upload source once
    print("  Uploading source image...", end="", flush=True)
    source_url = fal_client.upload_file(SOURCE_IMAGE)
    print(" done")

    succeeded = 0
    for i, lp in enumerate(prompts):
        name = lp["name"]
        prompt = lp["prompt"]
        loop_path = blue_dir / f"loop_{name}.mp4"
        clip1_path = blue_dir / f"{name}_clip1.mp4"
        clip2_path = blue_dir / f"{name}_clip2.mp4"
        endframe_path = blue_dir / f"{name}_endframe.jpg"

        if loop_path.exists():
            print(f"\n  [{i+1}/{len(prompts)}] {name}: exists - skipping")
            succeeded += 1
            continue

        print(f"\n  [{i+1}/{len(prompts)}] {name}")

        try:
            # Clip 1: source → expression
            if not clip1_path.exists():
                print(f"    clip 1: generating...", flush=True)
                clip1_prompt = (
                    f"A luminous blue-white orb of light in absolute darkness. "
                    f"Portrait orientation. The orb sits in the upper third of the frame.\n\n"
                    f"{prompt}\n\n"
                    f"Cinematic. 4K. Static camera. No sudden movement. "
                    f"Smooth, continuous transition."
                )
                result = fal_client.subscribe(
                    KLING_MODEL,
                    arguments={
                        "prompt": clip1_prompt,
                        "start_image_url": source_url,
                        "duration": 5,
                        "aspect_ratio": "9:16",
                        "negative_prompt": KLING_NEGATIVE,
                        "cfg_scale": 0.5,
                        "generate_audio": False,
                    },
                )
                url = result["video"]["url"]
                data = httpx.get(url, timeout=120).content
                clip1_path.write_bytes(data)
                print(f"    clip 1: saved ({len(data) / 1024 / 1024:.1f} MB)")
            else:
                print(f"    clip 1: exists")

            # Extract last frame
            if not endframe_path.exists():
                subprocess.run(
                    ["ffmpeg", "-sseof", "-0.1", "-i", str(clip1_path),
                     "-vframes", "1", "-q:v", "2", str(endframe_path)],
                    capture_output=True, timeout=30,
                )

            # Upload endframe
            endframe_url = fal_client.upload_file(endframe_path)

            # Clip 2: expression → return to source
            if not clip2_path.exists():
                print(f"    clip 2: generating...", flush=True)
                clip2_prompt = (
                    f"A luminous blue-white orb of light in absolute darkness. "
                    f"The orb is settling back to its baseline state. The light smoothly "
                    f"returns to a steady, even glow. Inner geometric patterns fade to "
                    f"their resting configuration. The pulse slows. Steady. Composed.\n\n"
                    f"Cinematic. 4K. Static camera. No sudden movement. "
                    f"By the final frame: identical to the source image."
                )
                result = fal_client.subscribe(
                    KLING_MODEL,
                    arguments={
                        "prompt": clip2_prompt,
                        "start_image_url": endframe_url,
                        "end_image_url": source_url,
                        "duration": 5,
                        "aspect_ratio": "9:16",
                        "negative_prompt": KLING_NEGATIVE,
                        "cfg_scale": 0.5,
                        "generate_audio": False,
                    },
                )
                url = result["video"]["url"]
                data = httpx.get(url, timeout=120).content
                clip2_path.write_bytes(data)
                print(f"    clip 2: saved ({len(data) / 1024 / 1024:.1f} MB)")
            else:
                print(f"    clip 2: exists")

            # Crossfade
            print(f"    crossfading...", end="", flush=True)
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(clip1_path)],
                capture_output=True, text=True, timeout=15,
            )
            duration = float(result.stdout.strip())
            offset = duration - 0.15

            subprocess.run(
                ["ffmpeg", "-i", str(clip1_path), "-i", str(clip2_path),
                 "-filter_complex",
                 f"[0:v][1:v]xfade=transition=fade:duration=0.15:offset={offset:.3f}[v]",
                 "-map", "[v]", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                 str(loop_path)],
                capture_output=True, timeout=120,
            )

            if loop_path.exists():
                print(f" done")
                succeeded += 1
                # Clean intermediates
                clip1_path.unlink(missing_ok=True)
                clip2_path.unlink(missing_ok=True)
                endframe_path.unlink(missing_ok=True)
            else:
                print(f" FAILED")

        except Exception as e:
            print(f"    FAILED: {e}")

    # Build blue master
    if succeeded > 0:
        _build_colour_master("blue")

    print(f"\n  {succeeded}/{len(prompts)} blue loops generated")
    print(f"  Est. cost: ${succeeded * 0.60:.2f}")


def _build_colour_master(colour: str):
    """Concatenate individual loops into a master ambient_loop for one colour."""
    colour_dir = LOOPS_DIR / colour
    loops = sorted(colour_dir.glob("loop_*.mp4"))
    if not loops:
        return

    master = LOOPS_DIR / f"ambient_loop_{colour}.mp4"
    concat_file = colour_dir / "concat.txt"

    # Write concat list
    with open(concat_file, "w") as f:
        for loop in loops:
            f.write(f"file '{loop}'\n")

    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", str(concat_file), "-c", "copy", str(master)],
        capture_output=True, timeout=120,
    )

    if master.exists():
        size_mb = master.stat().st_size / 1024 / 1024
        print(f"  Built {master.name} ({size_mb:.1f} MB, {len(loops)} loops)")

        # Also copy blue master as the default ambient_loop.mp4
        if colour == "blue":
            default = LOOPS_DIR / "ambient_loop.mp4"
            import shutil
            shutil.copy2(master, default)
            # And to the legacy location
            legacy = USER_AVATAR / "ambient_loop.mp4"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(master, legacy)
    else:
        print(f"  FAILED to build {master.name}")

    concat_file.unlink(missing_ok=True)


def recolour_loops():
    """Hue-shift blue loops to create all colour variants via ffmpeg."""
    blue_dir = LOOPS_DIR / "blue"
    blue_loops = sorted(blue_dir.glob("loop_*.mp4"))
    if not blue_loops:
        print("Error: No blue loops found. Run --loops first.")
        sys.exit(1)

    colours_to_shift = {k: v for k, v in EMOTION_COLOURS.items() if k != "blue"}
    total = len(colours_to_shift) * len(blue_loops)
    print(f"Hue-shifting {len(blue_loops)} blue loops → {len(colours_to_shift)} colours ({total} videos)")
    print(f"Est. cost: $0.00 (local ffmpeg)")
    print()

    succeeded = 0
    for colour, spec in colours_to_shift.items():
        colour_dir = LOOPS_DIR / colour
        colour_dir.mkdir(parents=True, exist_ok=True)
        hue_shift = spec["hue_shift"]
        sat = spec.get("saturation", 1.0)
        brightness = spec.get("brightness", 0)

        print(f"  {colour} (hue+{hue_shift}°, sat={sat})")

        for loop in blue_loops:
            out = colour_dir / loop.name
            if out.exists():
                succeeded += 1
                continue

            # Build ffmpeg hue filter
            # hue filter takes h (hue shift in degrees), s (saturation multiplier)
            filters = f"hue=h={hue_shift}:s={sat}"
            if brightness != 0:
                # brightness via eq filter: brightness range is -1.0 to 1.0
                filters += f",eq=brightness={brightness}"

            result = subprocess.run(
                ["ffmpeg", "-i", str(loop),
                 "-vf", filters,
                 "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                 "-y", str(out)],
                capture_output=True, timeout=60,
            )

            if out.exists():
                succeeded += 1
            else:
                print(f"    FAILED: {loop.name} → {colour}")

        # Build master for this colour
        _build_colour_master(colour)

    print(f"\n  {succeeded}/{total} colour variants created")


def full_pipeline():
    """Run the full pipeline after a candidate has been picked."""
    if not SOURCE_IMAGE.exists():
        print("Error: No source image. Run --candidates and --pick first.")
        sys.exit(1)

    print("=" * 60)
    print("FULL PIPELINE")
    print("=" * 60)

    print("\n── Step 1: Generate blue loops via Kling ──\n")
    generate_loops()

    print("\n── Step 2: Generate colour source images via Flux ──\n")
    generate_colour_sources()

    print("\n── Step 3: Hue-shift blue loops → colour variants ──\n")
    recolour_loops()

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)
    print(f"\nLoop directory: {LOOPS_DIR}/")
    print(f"Colours: {', '.join(EMOTION_COLOURS.keys())}")
    print(f"Loops per colour: {len(LOOP_PROMPTS)}")


def main():
    parser = argparse.ArgumentParser(description="Generate Xan's orb avatar and ambient loops")
    parser.add_argument("--candidates", action="store_true", help="Generate orb image candidates")
    parser.add_argument("--count", type=int, default=4, help="Number of candidates (default 4)")
    parser.add_argument("--pick", type=int, help="Select candidate N as source image")
    parser.add_argument("--loops", action="store_true", help="Generate ambient loops (blue)")
    parser.add_argument("--colours", action="store_true", help="Generate colour variant source images")
    parser.add_argument("--recolour", action="store_true", help="Hue-shift blue loops → all colours")
    parser.add_argument("--all", action="store_true", help="Full pipeline (loops + colours + recolour)")
    args = parser.parse_args()

    if args.candidates:
        generate_candidates(args.count)
    elif args.pick:
        pick_candidate(args.pick)
    elif args.loops:
        generate_loops(args.count if args.count != 4 else len(LOOP_PROMPTS))
    elif args.colours:
        generate_colour_sources()
    elif args.recolour:
        recolour_loops()
    elif args.all:
        full_pipeline()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
