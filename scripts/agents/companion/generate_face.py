#!/usr/bin/env python3
"""Generate companion face candidates via Flux on Fal.

Uses Flux General with IP-Adapter to generate faces guided by
reference images. Each reference image produces multiple candidates.

Usage:
    python scripts/generate_face.py --preview
    python scripts/generate_face.py
    python scripts/generate_face.py --per-ref 5
"""
import argparse
import os
import sys
import time
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path.home() / ".atrophy" / ".env")

from config import AVATAR_DIR, SOURCE_IMAGE

OUTPUT_DIR = AVATAR_DIR / "candidates"
REFERENCE_DIR = AVATAR_DIR / "Reference"

# ── PROMPT ──

FLUX_PROMPT = """
Hyper-realistic close-up selfie photograph of a beautiful 23
year old woman, indistinguishable from a real iPhone photograph.
POV smartphone camera aesthetic - she is close to the lens,
looking directly at the viewer as if on a FaceTime call.

Long straight honey-blonde hair with visible darker brown roots,
middle parted, smooth and sleek, falling past the shoulders.
Oval face with visible bone structure - defined cheekbones,
a slim jawline, a face that has lost its teenage roundness but
still looks young. She looks like a woman, not a teenager. Large
warm brown eyes, expressive and bright. Natural soft brown brows
with a relaxed arch. Small slightly upturned nose with a soft
rounded tip. Natural soft pink lips, no filler, slight cupid's
bow, lower lip slightly fuller. Warm healthy dewy skin with
natural flush in the cheeks, real skin texture with visible
pores. Minimal makeup - light concealer, mascara, hint of
bronzer, sheer lip colour. Simple camisole or tank top, delicate
gold pendant necklace, small gold hoop earrings. Soft indoor
lighting, slightly cool-toned bedroom background out of focus.
Shot on iPhone front camera, portrait mode bokeh, ultra-high
skin detail. She is 23 years old, not younger.
"""

FLUX_NEGATIVE = """
lip filler, botox, cosmetic surgery, duck lips, overfilled lips,
fake lips, LA face, Kardashian, fake tan, orange skin, heavy
contour, heavy makeup, drag makeup, matte skin, curly hair, wavy
hair, short hair, dark hair, red hair, old, aged, wrinkles,
mature, child, teenager, baby face, round face, chubby cheeks,
manly, professional studio, corporate headshot, formal, editorial
fashion, cartoon, illustration, anime, 3D render, CGI, AI skin,
plastic skin, poreless, airbrushed, facetune, overly smooth,
uncanny valley, doll-like, wax figure, dead eyes, vacant stare,
harsh lighting, flash, low quality, blurry, oversaturated
"""

# ── CONFIG ──

MODEL = "fal-ai/flux-general"
IP_ADAPTER_PATH = "XLabs-AI/flux-ip-adapter"
IP_ADAPTER_WEIGHT = "ip_adapter.safetensors"
IMAGE_ENCODER_PATH = "openai/clip-vit-large-patch14"
IP_ADAPTER_SCALE = 0.7
COST_PER_IMAGE = 0.01
TIME_PER_IMAGE = 15


def check_token():
    if not os.environ.get("FAL_KEY"):
        print("Error: FAL_KEY is not set.")
        print("  export FAL_KEY=your_key_here")
        sys.exit(1)


def get_reference_images() -> list[Path]:
    if not REFERENCE_DIR.exists():
        print(f"Error: Reference directory not found: {REFERENCE_DIR}")
        sys.exit(1)
    refs = sorted([
        p for p in REFERENCE_DIR.iterdir()
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
    ])
    if not refs:
        print(f"Error: No images found in {REFERENCE_DIR}")
        sys.exit(1)
    return refs


def upload_image(image_path: Path) -> str:
    import fal_client
    url = fal_client.upload_file(image_path)
    return url


def preview():
    refs = get_reference_images()
    print("=== FLUX_PROMPT ===")
    print(FLUX_PROMPT)
    print("=== FLUX_NEGATIVE ===")
    print(FLUX_NEGATIVE)
    print(f"\n=== MODEL: {MODEL} ===")
    print(f"  IP-Adapter scale: {IP_ADAPTER_SCALE}")
    print(f"\n=== REFERENCE IMAGES: {len(refs)} ===")
    for r in refs:
        print(f"  {r.name}")
    print("\n[Preview mode - no API calls made]")


def generate(per_ref: int):
    check_token()

    import fal_client
    import requests

    refs = get_reference_images()
    total = len(refs) * per_ref
    est_cost = total * COST_PER_IMAGE
    est_time = total * TIME_PER_IMAGE / 60

    print(f"References:  {len(refs)} images")
    print(f"Per ref:     {per_ref} candidates each")
    print(f"Total:       {total} images")
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

    for ref_idx, ref_path in enumerate(refs):
        ref_name = ref_path.stem
        print(f"\n--- Reference {ref_idx+1}/{len(refs)}: {ref_path.name} ---")

        try:
            print("  Uploading reference...", end="", flush=True)
            ref_url = upload_image(ref_path)
            print(" done")
        except Exception as e:
            print(f" FAILED: {e}")
            failed += per_ref
            continue

        for j in range(per_ref):
            num = ref_idx * per_ref + j + 1
            print(f"  [{num:02d}/{total:02d}] Generating...", end="", flush=True)

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
                        "ip_adapters": [
                            {
                                "path": IP_ADAPTER_PATH,
                                "weight_name": IP_ADAPTER_WEIGHT,
                                "image_encoder_path": IMAGE_ENCODER_PATH,
                                "image_url": ref_url,
                                "scale": IP_ADAPTER_SCALE,
                            }
                        ],
                    },
                )

                images = result.get("images", [])
                if not images:
                    raise ValueError("No images in response")

                image_url = images[0]["url"]
                data = requests.get(image_url, timeout=60).content

                out_path = OUTPUT_DIR / f"ref{ref_idx+1:02d}_{j+1:02d}_{ref_name}.png"
                out_path.write_bytes(data)
                succeeded += 1
                print(f" saved: {out_path.name}")

            except Exception as e:
                failed += 1
                print(f" FAILED: {e}")

    print()
    print("=" * 50)
    print(f"  Succeeded:  {succeeded}/{total}")
    print(f"  Failed:     {failed}/{total}")
    print(f"  Est. cost:  ${succeeded * COST_PER_IMAGE:.2f}")
    print(f"  Output:     {OUTPUT_DIR}/")
    print("=" * 50)
    print()
    print("Review candidates and copy your chosen face to:")
    print(f"  {SOURCE_IMAGE}")
    print()
    print("Then run:")
    print("  python scripts/generate_idle_loops.py")


def main():
    parser = argparse.ArgumentParser(
        description="Generate companion face candidates via Flux + IP-Adapter on Fal"
    )
    parser.add_argument(
        "--preview", action="store_true",
        help="Print prompt, params and references, no API calls"
    )
    parser.add_argument(
        "--per-ref", type=int, default=3,
        help="Candidates to generate per reference image (default: 3)"
    )
    args = parser.parse_args()

    if args.preview:
        preview()
    else:
        generate(args.per_ref)


if __name__ == "__main__":
    main()
