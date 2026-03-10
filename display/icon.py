"""
Programmatic orb icon generator for the companion app.

Generates a luminous consciousness orb using layered radial gradients.
Works standalone (generates icon files) or as an import (get_app_icon).
"""

import os
import math

from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import (
    QColor, QIcon, QImage, QPainter, QPixmap, QRadialGradient, QPen,
    QLinearGradient,
)

ICON_SIZES = [16, 32, 128, 256, 512, 1024]
ICONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")

_cached_icon = None


def _render_orb(size: int) -> QImage:
    """Render the consciousness orb at the given pixel size."""
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    cx, cy = size / 2, size / 2
    radius = size / 2

    # -- Layer 1: Outermost ambient glow (very faint, large) --
    # Slightly off-center upward to suggest overhead light
    g_ambient = QRadialGradient(QPointF(cx, cy * 0.95), radius * 0.95)
    g_ambient.setColorAt(0.0, QColor(120, 140, 220, 40))
    g_ambient.setColorAt(0.4, QColor(80, 90, 160, 28))
    g_ambient.setColorAt(0.7, QColor(40, 30, 80, 12))
    g_ambient.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(g_ambient)
    p.drawEllipse(QRectF(0, 0, size, size))

    # -- Layer 2: Outer halo — soft purple/blue envelope --
    g_outer = QRadialGradient(QPointF(cx, cy * 0.97), radius * 0.78)
    g_outer.setColorAt(0.0, QColor(140, 160, 255, 100))
    g_outer.setColorAt(0.3, QColor(100, 110, 210, 75))
    g_outer.setColorAt(0.6, QColor(60, 50, 140, 45))
    g_outer.setColorAt(0.85, QColor(25, 15, 60, 15))
    g_outer.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.setBrush(g_outer)
    p.drawEllipse(QRectF(0, 0, size, size))

    # -- Layer 3: Mid-glow — the visible body of the orb --
    g_mid = QRadialGradient(QPointF(cx, cy * 0.93), radius * 0.55)
    g_mid.setColorAt(0.0, QColor(190, 210, 255, 200))
    g_mid.setColorAt(0.25, QColor(150, 170, 245, 160))
    g_mid.setColorAt(0.5, QColor(110, 120, 220, 110))
    g_mid.setColorAt(0.75, QColor(65, 65, 170, 55))
    g_mid.setColorAt(1.0, QColor(20, 15, 60, 0))
    p.setBrush(g_mid)
    p.drawEllipse(QRectF(0, 0, size, size))

    # -- Layer 4: Inner bright core — white/blue hot center --
    # Offset upward and slightly left for depth
    core_cx = cx * 0.96
    core_cy = cy * 0.85
    g_core = QRadialGradient(QPointF(core_cx, core_cy), radius * 0.32)
    g_core.setColorAt(0.0, QColor(255, 255, 255, 250))
    g_core.setColorAt(0.15, QColor(235, 245, 255, 230))
    g_core.setColorAt(0.35, QColor(190, 215, 255, 180))
    g_core.setColorAt(0.6, QColor(140, 165, 245, 100))
    g_core.setColorAt(0.85, QColor(100, 120, 220, 40))
    g_core.setColorAt(1.0, QColor(70, 80, 170, 0))
    p.setBrush(g_core)
    p.drawEllipse(QRectF(0, 0, size, size))

    # -- Layer 5: Hot specular highlight — the "window reflection" --
    spec_cx = cx * 0.88
    spec_cy = cy * 0.72
    spec_r = radius * 0.15
    g_spec = QRadialGradient(QPointF(spec_cx, spec_cy), spec_r)
    g_spec.setColorAt(0.0, QColor(255, 255, 255, 200))
    g_spec.setColorAt(0.3, QColor(240, 248, 255, 140))
    g_spec.setColorAt(0.7, QColor(200, 220, 255, 40))
    g_spec.setColorAt(1.0, QColor(160, 180, 240, 0))
    p.setBrush(g_spec)
    p.drawEllipse(QRectF(0, 0, size, size))

    # -- Layer 6: Light flare — vertical streak through the orb --
    # Use a narrow ellipse with a linear gradient for the flare
    p.save()
    p.translate(cx, cy)
    p.rotate(-15)  # Slight tilt

    flare_w = radius * 0.08
    flare_h = radius * 0.7
    flare_rect = QRectF(-flare_w, -flare_h, flare_w * 2, flare_h * 2)

    g_flare = QRadialGradient(QPointF(0, -flare_h * 0.2), max(flare_h, flare_w))
    g_flare.setColorAt(0.0, QColor(255, 255, 255, 60))
    g_flare.setColorAt(0.3, QColor(200, 220, 255, 35))
    g_flare.setColorAt(0.6, QColor(160, 180, 240, 15))
    g_flare.setColorAt(1.0, QColor(100, 120, 200, 0))
    p.setBrush(g_flare)
    p.drawEllipse(flare_rect)
    p.restore()

    # -- Layer 7: Secondary smaller flare (cross) --
    p.save()
    p.translate(cx, cy)
    p.rotate(75)

    flare_w2 = radius * 0.05
    flare_h2 = radius * 0.45
    flare_rect2 = QRectF(-flare_w2, -flare_h2, flare_w2 * 2, flare_h2 * 2)

    g_flare2 = QRadialGradient(QPointF(0, 0), max(flare_h2, flare_w2))
    g_flare2.setColorAt(0.0, QColor(255, 255, 255, 35))
    g_flare2.setColorAt(0.4, QColor(180, 200, 255, 20))
    g_flare2.setColorAt(1.0, QColor(120, 140, 220, 0))
    p.setBrush(g_flare2)
    p.drawEllipse(flare_rect2)
    p.restore()

    # -- Layer 8: Faint rim light on the bottom edge --
    rim_cy = cy * 1.15
    g_rim = QRadialGradient(QPointF(cx, rim_cy), radius * 0.50)
    g_rim.setColorAt(0.0, QColor(160, 180, 240, 30))
    g_rim.setColorAt(0.4, QColor(120, 140, 210, 18))
    g_rim.setColorAt(0.7, QColor(80, 90, 170, 8))
    g_rim.setColorAt(1.0, QColor(40, 40, 100, 0))
    p.setBrush(g_rim)
    p.drawEllipse(QRectF(0, 0, size, size))

    p.end()
    return image


def generate_icons(directory: str = ICONS_DIR, sizes: list = None) -> list:
    """Generate orb icon PNGs at multiple sizes. Returns list of file paths.

    Skips any size where a hand-crafted PNG already exists (brain icons).
    """
    if sizes is None:
        sizes = ICON_SIZES

    os.makedirs(directory, exist_ok=True)
    paths = []

    for s in sizes:
        path = os.path.join(directory, f"icon_{s}x{s}.png")
        if os.path.exists(path):
            print(f"  Skipping {path} (already exists)")
            paths.append(path)
            continue
        image = _render_orb(s)
        image.save(path, "PNG")
        paths.append(path)
        print(f"  Generated {path}")

    return paths


def get_app_icon() -> QIcon:
    """
    Return a QIcon. Prefers the .icns file (hand-crafted brain icon)
    over the generated orb PNGs, which are a fallback only.
    """
    global _cached_icon
    if _cached_icon is not None:
        return _cached_icon

    # Prefer .icns (the brain icon) if it exists
    icns_path = os.path.join(ICONS_DIR, "TheAtrophiedMind.icns")
    if os.path.exists(icns_path):
        icon = QIcon(icns_path)
        if not icon.isNull():
            _cached_icon = icon
            return icon

    # Fallback: generated orb PNGs
    missing = any(
        not os.path.exists(os.path.join(ICONS_DIR, f"icon_{s}x{s}.png"))
        for s in ICON_SIZES
    )
    if missing:
        print("Generating fallback app icons...")
        generate_icons()

    icon = QIcon()
    for s in ICON_SIZES:
        path = os.path.join(ICONS_DIR, f"icon_{s}x{s}.png")
        if os.path.exists(path):
            icon.addPixmap(QPixmap(path))

    _cached_icon = icon
    return icon


if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication

    # QApplication is required for QPainter to work
    app = QApplication(sys.argv)

    print("Generating consciousness orb icons...")
    paths = generate_icons()
    print(f"\nDone. Generated {len(paths)} icons in {ICONS_DIR}")
