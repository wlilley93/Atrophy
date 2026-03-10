"""LivePortrait animation wrapper.

Takes a TTS audio file, drives the companion's source image,
returns path to the rendered video. Runs as subprocess with
MPS fallback enabled.
"""
import subprocess
import tempfile
from pathlib import Path

from config import SOURCE_IMAGE, LIVEPORTRAIT_PATH, AVATAR_RESOLUTION


def render_response(audio_path: Path) -> Path:
    """Drive the companion face with TTS audio.

    Args:
        audio_path: Path to TTS-generated audio file.

    Returns:
        Path to rendered video file.

    Raises:
        RuntimeError: If LivePortrait fails or is not installed.
    """
    if not LIVEPORTRAIT_PATH.exists():
        raise RuntimeError(f"LivePortrait not found at {LIVEPORTRAIT_PATH}")

    if not SOURCE_IMAGE.exists():
        raise RuntimeError(f"Source image not found at {SOURCE_IMAGE}")

    output_dir = tempfile.mkdtemp(prefix="companion_anim_")
    output_path = Path(output_dir) / "response.mp4"

    env = {
        "PYTORCH_ENABLE_MPS_FALLBACK": "1",
        "PATH": subprocess.os.environ.get("PATH", ""),
    }

    result = subprocess.run(
        [
            "python", "inference.py",
            "--source_image", str(SOURCE_IMAGE),
            "--driving_audio", str(audio_path),
            "--output", str(output_path),
            "--size", str(AVATAR_RESOLUTION),
        ],
        cwd=str(LIVEPORTRAIT_PATH),
        capture_output=True,
        text=True,
        timeout=300,
        env={**subprocess.os.environ, **env},
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"LivePortrait failed (exit {result.returncode}): {result.stderr[:500]}"
        )

    if not output_path.exists():
        raise RuntimeError("LivePortrait completed but output file not found")

    return output_path
