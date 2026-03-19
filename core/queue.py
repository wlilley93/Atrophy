"""Thread-safe message queue for inter-process communication.

All cron scripts and background jobs use this to enqueue messages
for the GUI to pick up. File locking prevents race conditions when
multiple jobs fire simultaneously.
"""
import fcntl
import json
from datetime import datetime
from pathlib import Path


def queue_message(
    queue_file: Path,
    text: str,
    source: str = "task",
    audio_path: str = "",
):
    """Append a message to the queue file with file locking.

    Safe to call from multiple processes concurrently — uses
    fcntl.flock to serialize reads and writes.
    """
    queue_file.parent.mkdir(parents=True, exist_ok=True)

    lock_path = queue_file.with_suffix(".lock")

    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            queue = []
            if queue_file.exists():
                try:
                    queue = json.loads(queue_file.read_text())
                except (json.JSONDecodeError, OSError):
                    queue = []

            queue.append({
                "text": text,
                "audio_path": audio_path,
                "source": source,
                "created_at": datetime.now().isoformat(),
            })

            queue_file.write_text(json.dumps(queue, indent=2))
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
