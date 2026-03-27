"""Channel push utility for WorldMonitor.

Pushes channel state (briefings, map data, metadata) to the WorldMonitor
platform at worldmonitor.atrophy.app from agent cron scripts.

Usage:
    from channel_push import push_channel, push_briefing, push_map_state

    # Push a full channel state
    push_channel("general_montgomery", {
        "agent": "general_montgomery",
        "display_name": "Gen. Montgomery",
        "alert_level": "elevated",
        "briefing": {
            "title": "Daily Situation Report",
            "summary": "Escalation in eastern Mediterranean...",
            "body_md": "## Assessment\\n\\nFull markdown body...",
            "sources": ["OSINT", "OREF", "USNI"],
        },
        "map": {
            "center": [35.0, 33.0],
            "zoom": 5,
            "layers": ["fleet", "alerts"],
            "markers": [{"lat": 34.7, "lon": 32.5, "label": "CVN-78"}],
            "regions": [{"id": "eastern-med", "status": "elevated"}],
        },
    })

    # Push just a briefing
    push_briefing(
        "rf_european_security",
        title="Weekly Security Digest",
        summary="NATO posture remains unchanged...",
        body_md="## Key Developments\\n\\n...",
        sources=["NATO SHAPE", "IISS"],
    )

    # Push just map state
    push_map_state(
        "rf_russia_ukraine",
        center=[48.5, 37.5],
        zoom=7,
        markers=[{"lat": 48.0, "lon": 38.0, "label": "Frontline shift"}],
    )

Environment variables:
    CHANNEL_BASE_URL  - API base URL (default: https://worldmonitor.atrophy.app)
    CHANNEL_API_KEY   - Required. API key sent as X-Channel-Key header.
"""

import json
import logging
import os
import urllib.request
import urllib.error

log = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://worldmonitor.atrophy.app"
_TIMEOUT = 15


def _base_url() -> str:
    """Return the base URL, stripping any trailing slash."""
    url = os.environ.get("CHANNEL_BASE_URL", _DEFAULT_BASE_URL)
    return url.rstrip("/")


def _api_key() -> str:
    """Return the channel API key from the environment."""
    return os.environ.get("CHANNEL_API_KEY", "")


def _put(url: str, payload: dict) -> bool:
    """Send a PUT request with JSON body and auth header.

    Returns True on success (2xx), False on any failure.
    Never raises exceptions.
    """
    api_key = _api_key()
    if not api_key:
        log.warning("CHANNEL_API_KEY not set - skipping push to %s", url)
        return False

    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Channel-Key": api_key,
    }

    req = urllib.request.Request(url, data=body, headers=headers, method="PUT")

    try:
        resp = urllib.request.urlopen(req, timeout=_TIMEOUT)
        status = resp.getcode()
        if 200 <= status < 300:
            log.info("Channel push OK: %s (HTTP %d)", url, status)
            return True
        else:
            log.warning("Channel push unexpected status: %s (HTTP %d)", url, status)
            return False
    except urllib.error.HTTPError as e:
        log.warning(
            "Channel push failed: %s (HTTP %d: %s)",
            url, e.code, e.reason,
        )
        return False
    except urllib.error.URLError as e:
        log.warning("Channel push failed: %s (%s)", url, e.reason)
        return False
    except Exception as e:
        log.warning("Channel push failed: %s (%s)", url, e)
        return False


def push_channel(agent_name: str, state: dict) -> bool:
    """Push full channel state to WorldMonitor.

    Args:
        agent_name: Agent identifier used as the channel name in the URL.
        state: Full channel state dict. Expected keys:
            - agent (str): Agent identifier
            - display_name (str): Human-readable agent name
            - alert_level (str): e.g. "normal", "elevated", "critical"
            - briefing (dict): Briefing content with keys:
                - title (str)
                - summary (str)
                - body_md (str): Full markdown body
                - sources (list[str]): Source attributions
            - map (dict): Map state with keys:
                - center (list[float]): [lat, lon]
                - zoom (int)
                - layers (list[str]): Active layer names
                - markers (list[dict]): Map markers
                - regions (list[dict]): Region overlays

    Returns:
        True on success, False on failure.
    """
    url = f"{_base_url()}/api/channels/{agent_name}"
    return _put(url, state)


def push_briefing(
    agent_name: str,
    title: str,
    summary: str,
    body_md: str = "",
    sources: list | None = None,
) -> bool:
    """Push briefing text only to WorldMonitor.

    Args:
        agent_name: Agent identifier used as the channel name.
        title: Briefing title.
        summary: Short summary line.
        body_md: Full markdown body (optional).
        sources: List of source attribution strings (optional).

    Returns:
        True on success, False on failure.
    """
    payload = {
        "title": title,
        "summary": summary,
        "body_md": body_md,
        "sources": sources or [],
    }
    url = f"{_base_url()}/api/channels/{agent_name}/briefing"
    return _put(url, payload)


def push_map_state(
    agent_name: str,
    center: list | None = None,
    zoom: int | None = None,
    layers: list | None = None,
    markers: list | None = None,
    regions: list | None = None,
) -> bool:
    """Push map state only to WorldMonitor.

    Args:
        agent_name: Agent identifier used as the channel name.
        center: Map center as [lat, lon] (optional).
        zoom: Map zoom level (optional).
        layers: List of active layer names (optional).
        markers: List of marker dicts with lat, lon, label, etc. (optional).
        regions: List of region overlay dicts (optional).

    Returns:
        True on success, False on failure.
    """
    payload: dict = {}
    if center is not None:
        payload["center"] = center
    if zoom is not None:
        payload["zoom"] = zoom
    if layers is not None:
        payload["layers"] = layers
    if markers is not None:
        payload["markers"] = markers
    if regions is not None:
        payload["regions"] = regions

    url = f"{_base_url()}/api/channels/{agent_name}/map"
    return _put(url, payload)
