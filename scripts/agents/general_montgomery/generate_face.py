#!/usr/bin/env python3
"""Generate General Montgomery face candidates via Flux on Fal.

No reference images — generates from prompt only using Flux.

Usage:
    python scripts/agents/general_montgomery/generate_face.py --preview
    python scripts/agents/general_montgomery/generate_face.py
    python scripts/agents/general_montgomery/generate_face.py --count 6
"""
import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from config import AVATAR_DIR, SOURCE_IMAGE

OUTPUT_DIR = AVATAR_DIR / "candidates"

# ── PROMPT ──

FLUX_PROMPT = """
RAW photograph, Nikon D850, 85mm f/1.4 lens, natural window light.
Portrait of a distinguished British military officer, 48 years old.
Not young, not old — exactly the age where authority sits naturally.
Dark hair with definite grey through it, more salt-and-pepper than
brown now, cut short and precise, side-parted. A mature face with
real character — visible lines across the forehead and around the
eyes, the weathering of a man who has spent two decades making hard
decisions. Clean-shaven, strong jaw, blue-grey eyes.

He is fit but not athletic-looking. A lean, wiry build — the frame
of a man who has never carried excess anything, including weight.
Real skin — pores, slight ruddiness, crow's feet. He looks like
a real person photographed in real light. Not retouched.

Wearing a dark navy military dress shirt with rank insignia, or a
charcoal wool suit with white shirt and regimental tie. The kind
of man who looks more authoritative in civilian clothes than most
men look in uniform.

Expression: measured, steady, appraising. Not cold — composed. The
look of a man listening to an intelligence briefing and already
forming his assessment. Mouth closed. Direct eye contact with camera.

Background: muted, dark, out of focus. A war room, an office, a
dim briefing room. Bokeh. The subject is the only thing in focus.
Shot on 35mm film grain, slight warmth. Indistinguishable from
a real editorial photograph in GQ or The Times Magazine.
"""

FLUX_NEGATIVE = """
old, elderly, aged, wrinkles, sagging skin, liver spots, white hair,
fully grey, grandfather, retired, overweight, round face, chubby,
baby face, beard, stubble, long hair, unkempt, scruffy, casual,
t-shirt, hoodie, American military, US flag, camouflage fatigues,
combat helmet, body armour, smiling, laughing, grinning, teeth,
cartoon, illustration, painting, anime, 3D render, CGI, digital art,
AI-generated look, plastic skin, poreless, airbrushed, smooth skin,
uncanny valley, doll-like, wax figure, mannequin, over-processed,
harsh flash, ring light, studio backdrop, low quality, blurry,
oversaturated, HDR, stock photo, corporate headshot, generic, bland,
medal ceremony, formal parade, ornate uniform, gold braid, epaulettes
"""

# ── CONFIG ──

MODEL = "fal-ai/flux-general"
COST_PER_IMAGE = 0.01
TIME_PER_IMAGE = 15


def check_token():
    if not os.environ.get("FAL_KEY"):
        print("Error: FAL_KEY is not set.")
        print("  export FAL_KEY=your_key_here")
        sys.exit(1)


def preview():
    print("=== FLUX_PROMPT ===")
    print(FLUX_PROMPT)
    print("=== FLUX_NEGATIVE ===")
    print(FLUX_NEGATIVE)
    print(f"\n=== MODEL: {MODEL} ===")
    print(f"\n=== OUTPUT: {OUTPUT_DIR} ===")
    print(f"=== SOURCE: {SOURCE_IMAGE} ===")
    print("\n[Preview mode — no API calls made]")


def generate(count: int):
    check_token()

    import fal_client
    import requests

    est_cost = count * COST_PER_IMAGE
    est_time = count * TIME_PER_IMAGE / 60

    print(f"Candidates:  {count}")
    print(f"Est. cost:   ${est_cost:.2f}")
    print(f"Est. time:   {est_time:.1f} minutes")
    print()
    confirm = input("Proceed? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    succeeded = 0
    failed = 0

    for i in range(count):
        print(f"  [{i+1:02d}/{count:02d}] Generating...", end="", flush=True)

        try:
            result = fal_client.subscribe(
                MODEL,
                arguments={
                    "prompt": FLUX_PROMPT.strip(),
                    "negative_prompt": FLUX_NEGATIVE.strip(),
                    "num_inference_steps": 50,
                    "guidance_scale": 3.5,
                    "image_size": {"width": 768, "height": 1024},
                    "output_format": "png",
                },
            )

            images = result.get("images", [])
            if not images:
                raise ValueError("No images in response")

            image_url = images[0]["url"]
            data = requests.get(image_url, timeout=60).content

            out_path = OUTPUT_DIR / f"montgomery_{i+1:02d}.png"
            out_path.write_bytes(data)
            succeeded += 1
            print(f" saved: {out_path.name}")

        except Exception as e:
            failed += 1
            print(f" FAILED: {e}")

    print()
    print("=" * 50)
    print(f"  Succeeded:  {succeeded}/{count}")
    print(f"  Failed:     {failed}/{count}")
    print(f"  Est. cost:  ${succeeded * COST_PER_IMAGE:.2f}")
    print(f"  Output:     {OUTPUT_DIR}/")
    print("=" * 50)
    print()
    print("Review candidates and copy your chosen face to:")
    print(f"  {SOURCE_IMAGE}")
    print()
    print("Then run:")
    print(f"  AGENT=general_montgomery python scripts/agents/companion/generate_idle_loops.py")


def main():
    parser = argparse.ArgumentParser(
        description="Generate General Montgomery face candidates via Flux on Fal"
    )
    parser.add_argument(
        "--preview", action="store_true",
        help="Print prompt and params, no API calls"
    )
    parser.add_argument(
        "--count", type=int, default=4,
        help="Number of candidates to generate (default: 4)"
    )
    args = parser.parse_args()

    if args.preview:
        preview()
    else:
        generate(args.count)


if __name__ == "__main__":
    main()
