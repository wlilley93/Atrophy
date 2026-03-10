"""Secure temp file creation for voice modules."""
import os
import tempfile
from pathlib import Path


def secure_tmp(suffix: str, namespace: str = "atrophy") -> Path:
    """Create a temp file in a user-only directory (mode 700).

    Args:
        suffix: File extension (e.g. ".wav", ".mp3")
        namespace: Subdirectory name under system temp dir
    """
    d = Path(tempfile.gettempdir()) / namespace
    d.mkdir(mode=0o700, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=suffix, dir=str(d))
    os.close(fd)
    return Path(path)
