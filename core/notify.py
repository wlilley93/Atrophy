"""macOS native notification helper.

Uses pyobjc NSUserNotificationCenter to send notifications.
Click handler brings the companion window to front if running.
"""
import subprocess


def send_notification(title: str, body: str, subtitle: str = ""):
    """Send a macOS notification via osascript.

    Uses AppleScript for reliability - no pyobjc dependency required.
    If the companion app is running, clicking the notification brings it forward.
    Gated by NOTIFICATIONS_ENABLED config - silenced when disabled.
    """
    try:
        from config import NOTIFICATIONS_ENABLED
        if not NOTIFICATIONS_ENABLED:
            return
    except ImportError:
        pass
    # Escape for AppleScript string literals
    for char in (('\\', '\\\\'), ('"', '\\"')):
        title = title.replace(*char)
        body = body.replace(*char)
        subtitle = subtitle.replace(*char)
    # Newlines break AppleScript - replace with spaces
    title = title.replace('\n', ' ').replace('\r', ' ')
    body = body.replace('\n', ' ').replace('\r', ' ')
    subtitle = subtitle.replace('\n', ' ').replace('\r', ' ')

    script_parts = [f'display notification "{body}" with title "{title}"']
    if subtitle:
        script_parts[0] = f'display notification "{body}" with title "{title}" subtitle "{subtitle}"'

    try:
        subprocess.run(
            ["osascript", "-e", script_parts[0]],
            capture_output=True, timeout=5,
        )
    except Exception as e:
        print(f"[notify] failed: {e}")
