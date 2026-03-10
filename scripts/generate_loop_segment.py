#!/usr/bin/env python3
"""Generate a single loop segment from a request.

Called by the add_avatar_loop MCP tool or manually. Generates a paired
clip sequence (source → expression → source) via Kling 3.0, crossfades
them into a loop, and rebuilds the master ambient_loop.mp4.

Usage:
  python scripts/generate_loop_segment.py --agent general_montgomery --name contemplation
  python scripts/generate_loop_segment.py --agent companion --name curiosity --prompt "..."
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

KLING_MODEL = "fal-ai/kling-video/v3/pro/image-to-video"

NEGATIVE_PROMPT = (
    "blur, distort, low quality, sudden movement, jump cut, morphing, "
    "face distortion, extra fingers, unnatural skin, plastic skin, "
    "uncanny valley, teeth showing too much, exaggerated expression"
)


def _load_request(agent: str, name: str) -> dict | None:
    """Load a pending request file."""
    user_data = Path.home() / ".atrophy"
    request_path = user_data / "agents" / agent / "avatar" / ".loop_requests" / f"{name}.json"
    if request_path.exists():
        return json.loads(request_path.read_text())
    return None


def _update_request(agent: str, name: str, status: str, **extra):
    user_data = Path.home() / ".atrophy"
    request_path = user_data / "agents" / agent / "avatar" / ".loop_requests" / f"{name}.json"
    if request_path.exists():
        data = json.loads(request_path.read_text())
    else:
        data = {"name": name, "agent": agent}
    data["status"] = status
    data.update(extra)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(data, indent=2) + "\n")


def _get_source_image(agent: str) -> Path:
    """Find the source face image — check bundle first, then user data."""
    import importlib
    os.environ["AGENT"] = agent
    import config as cfg
    importlib.reload(cfg)
    return cfg.SOURCE_IMAGE


def _get_loops_dir(agent: str) -> Path:
    return Path.home() / ".atrophy" / "agents" / agent / "avatar" / "loops"


def _build_clip1_prompt(prompt: str, agent: str) -> str:
    """Build clip 1 prompt — neutral → expression."""
    # Load agent manifest for physical description
    import importlib
    os.environ["AGENT"] = agent
    import config as cfg
    importlib.reload(cfg)

    manifest_path = cfg.AGENT_DIR / "data" / "agent.json"
    desc = ""
    if manifest_path.exists():
        data = json.loads(manifest_path.read_text())
        desc = data.get("avatar_description", "")

    if not desc:
        desc = "A person sits in soft interior light. They begin in stillness: gaze middle-distance, expression composed, mouth closed."

    return f"""\
{desc}

{prompt}

Cinematic. 4K. Shallow depth of field. Static camera. No sudden movement.
"""


def _build_clip2_prompt(prompt: str) -> str:
    """Build clip 2 prompt — expression → return to neutral."""
    return f"""\
Continuation. Same person, same light. They begin {prompt}.

Gradually, without rush, everything settles. Their gaze returns to the \
middle distance. Expression smooths into composed neutrality. Mouth \
closes. A controlled breath. Still.

By the final frame they are neutral — gaze middle-distance, expression \
composed, mouth closed, breathing steady.

Cinematic. 4K. Shallow depth of field. Static camera. No sudden movement.
FINAL FRAME: middle-distance gaze, composed neutral expression, \
mouth closed. Matches the source portrait exactly.\
"""


def upload(path: Path) -> str:
    import fal_client
    print(f"  Uploading {path.name}...", end="", flush=True)
    url = fal_client.upload_file(path)
    print(" done")
    return url


def generate_clip(prompt, start_image_url, output_path, label, end_image_url=None):
    import fal_client
    import httpx

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
        print(f"  FAILED to join clips")
        sys.exit(1)


def generate_segment(agent: str, name: str, prompt: str):
    """Full pipeline: generate clip pair, crossfade, rebuild master."""
    source_image = _get_source_image(agent)
    if not source_image.exists():
        print(f"Error: Source image not found at {source_image}")
        _update_request(agent, name, "failed", error="No source image")
        return False

    loops_dir = _get_loops_dir(agent)
    loops_dir.mkdir(parents=True, exist_ok=True)

    clip1_path = loops_dir / f"{name}_clip1.mp4"
    clip2_path = loops_dir / f"{name}_clip2.mp4"
    endframe_path = loops_dir / f"{name}_endframe.jpg"
    loop_path = loops_dir / f"loop_{name}.mp4"

    if loop_path.exists():
        print(f"Loop already exists: {loop_path}")
        return True

    _update_request(agent, name, "generating")

    try:
        source_url = upload(source_image)

        # Clip 1: neutral → expression
        clip1_prompt = _build_clip1_prompt(prompt, agent)
        generate_clip(clip1_prompt, source_url, clip1_path, f"{name} clip 1")

        # Extract last frame as start for clip 2
        extract_last_frame(clip1_path, endframe_path)
        endframe_url = upload(endframe_path)

        # Clip 2: expression → neutral (with source as end image for guidance)
        clip2_prompt = _build_clip2_prompt(prompt)
        generate_clip(clip2_prompt, endframe_url, clip2_path,
                      f"{name} clip 2", end_image_url=source_url)

        # Crossfade
        join_clips(clip1_path, clip2_path, loop_path)

        if loop_path.exists():
            print(f"  Loop generated: {loop_path}")
            _update_request(agent, name, "done", loop_path=str(loop_path))

            # Rebuild master ambient loop
            print("\n  Rebuilding ambient loop...")
            rebuild_script = PROJECT_ROOT / "scripts" / "rebuild_ambient_loop.py"
            subprocess.run(
                [sys.executable, str(rebuild_script), "--agent", agent],
                cwd=str(PROJECT_ROOT),
                timeout=120,
            )
            return True
        else:
            _update_request(agent, name, "failed", error="Crossfade failed")
            return False

    except Exception as e:
        print(f"  FAILED: {e}")
        _update_request(agent, name, "failed", error=str(e))
        return False


def main():
    parser = argparse.ArgumentParser(description="Generate a single loop segment")
    parser.add_argument("--agent", required=True, help="Agent name")
    parser.add_argument("--name", required=True, help="Segment name")
    parser.add_argument("--prompt", default=None, help="Override prompt (otherwise reads from request file)")
    args = parser.parse_args()

    # Get prompt from request file or CLI
    prompt = args.prompt
    if not prompt:
        request = _load_request(args.agent, args.name)
        if request:
            prompt = request.get("prompt")
        if not prompt:
            print(f"Error: No prompt found. Provide --prompt or create a request file.")
            sys.exit(1)

    print(f"Generating loop: {args.name} for {args.agent}")
    print(f"Prompt: {prompt[:100]}...")
    success = generate_segment(args.agent, args.name, prompt)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
