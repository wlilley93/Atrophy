"""Lucide icon helper - renders SVG icons as QPixmaps for PyQt5 buttons.

Uses python-lucide for offline SVG generation + QSvgRenderer for rendering.
Caches rendered pixmaps by (name, size, color) to avoid re-rendering.
"""
from PyQt5.QtCore import Qt, QByteArray
from PyQt5.QtGui import QPixmap, QPainter, QIcon

_cache: dict[tuple, QPixmap] = {}


def pixmap(name: str, size: int = 18, color: str = "rgba(255,255,255,0.75)",
           stroke_width: float = 2.0) -> QPixmap:
    """Render a Lucide icon as a QPixmap."""
    key = (name, size, color, stroke_width)
    if key in _cache:
        return _cache[key]

    from lucide import lucide_icon
    svg = lucide_icon(name, width=size, height=size,
                      stroke=color, stroke_width=stroke_width)

    from PyQt5.QtSvg import QSvgRenderer
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))

    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    renderer.render(p)
    p.end()

    _cache[key] = pix
    return pix


def icon(name: str, size: int = 18, color: str = "rgba(255,255,255,0.75)",
         stroke_width: float = 2.0) -> QIcon:
    """Render a Lucide icon as a QIcon."""
    return QIcon(pixmap(name, size, color, stroke_width))
