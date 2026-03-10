"""Tabbed settings modal — Settings, Usage, and Activity tabs.

Full-screen overlay with three tabs:
  - Settings: all configuration (agents, identity, voice, inference, etc.)
  - Usage: per-agent token/inference tracking
  - Activity: unified audit log (tool calls, heartbeats, inference)
"""
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QScrollArea, QComboBox, QCheckBox, QSpinBox, QSlider, QFrame,
    QStackedWidget, QApplication, QSizePolicy,
)


# ── Styles ──────────────────────────────────────────────────────

_STYLE = """
    QWidget#settingsModal {
        background: transparent;
    }
    QScrollArea {
        background: transparent;
        border: none;
    }
    QScrollArea > QWidget > QWidget {
        background: transparent;
    }
    QScrollBar:vertical {
        background: rgba(255, 255, 255, 10);
        width: 6px;
        margin: 0;
        border-radius: 3px;
    }
    QScrollBar::handle:vertical {
        background: rgba(255, 255, 255, 40);
        min-height: 30px;
        border-radius: 3px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }
    QLabel {
        color: rgba(255, 255, 255, 0.85);
        font-size: 13px;
        background: transparent;
    }
    QLabel#sectionHeader {
        color: rgba(255, 255, 255, 0.5);
        font-size: 11px;
        font-weight: bold;
        text-transform: uppercase;
        padding-top: 12px;
        padding-bottom: 4px;
        background: transparent;
    }
    QLabel#settingLabel {
        color: rgba(255, 255, 255, 0.7);
        font-size: 12px;
        background: transparent;
    }
    QSlider::groove:horizontal {
        height: 4px;
        background: rgba(255, 255, 255, 0.15);
        border-radius: 2px;
    }
    QSlider::handle:horizontal {
        width: 14px;
        height: 14px;
        margin: -5px 0;
        background: rgba(255, 255, 255, 0.8);
        border-radius: 7px;
    }
    QSlider::sub-page:horizontal {
        background: rgba(255, 255, 255, 0.35);
        border-radius: 2px;
    }
    QComboBox {
        background: rgba(255, 255, 255, 0.08);
        color: rgba(255, 255, 255, 0.85);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 12px;
        min-width: 120px;
    }
    QComboBox::drop-down {
        border: none;
        width: 20px;
    }
    QComboBox::down-arrow {
        image: none;
        border: none;
    }
    QComboBox QAbstractItemView {
        background: rgb(30, 30, 35);
        color: rgba(255, 255, 255, 0.85);
        border: 1px solid rgba(255, 255, 255, 0.1);
        selection-background-color: rgba(255, 255, 255, 0.15);
    }
    QCheckBox {
        color: rgba(255, 255, 255, 0.85);
        font-size: 12px;
        spacing: 6px;
        background: transparent;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 1px solid rgba(255, 255, 255, 0.3);
        border-radius: 4px;
        background: rgba(255, 255, 255, 0.05);
    }
    QCheckBox::indicator:checked {
        background: rgba(255, 255, 255, 0.3);
        border-color: rgba(255, 255, 255, 0.5);
    }
    QSpinBox, QDoubleSpinBox {
        background: rgba(255, 255, 255, 0.08);
        color: rgba(255, 255, 255, 0.85);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 12px;
        min-width: 80px;
    }
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
        width: 16px;
        border: none;
        background: rgba(255, 255, 255, 0.05);
    }
    QLineEdit#settingsInput {
        background: rgba(255, 255, 255, 0.08);
        color: rgba(255, 255, 255, 0.85);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 12px;
    }
    QPushButton#saveButton {
        background: rgba(255, 255, 255, 0.12);
        color: rgba(255, 255, 255, 0.9);
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 8px;
        padding: 8px 20px;
        font-size: 13px;
        font-weight: bold;
    }
    QPushButton#saveButton:hover {
        background: rgba(255, 255, 255, 0.18);
    }
    QPushButton#closeButton {
        background: transparent;
        color: rgba(255, 255, 255, 0.5);
        border: none;
        font-size: 20px;
        font-weight: bold;
    }
    QPushButton#closeButton:hover {
        color: rgba(255, 255, 255, 0.9);
    }
    QLineEdit#searchInput {
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 6px;
        color: white;
        padding: 6px 10px;
        font-size: 13px;
    }
"""


# ── Tab Button ──────────────────────────────────────────────────

class _TabButton(QPushButton):
    """Pill-shaped tab button."""
    def __init__(self, label, parent=None):
        super().__init__(label, parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        self.setMinimumWidth(80)
        self._update_style()
        self.toggled.connect(lambda: self._update_style())

    def _update_style(self):
        if self.isChecked():
            self.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,0.15); "
                "color: rgba(255,255,255,0.95); border: 1px solid rgba(255,255,255,0.2); "
                "border-radius: 15px; padding: 4px 16px; font-size: 12px; font-weight: bold; }"
            )
        else:
            self.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,0.04); "
                "color: rgba(255,255,255,0.45); border: 1px solid rgba(255,255,255,0.08); "
                "border-radius: 15px; padding: 4px 16px; font-size: 12px; }"
                "QPushButton:hover { background: rgba(255,255,255,0.08); "
                "color: rgba(255,255,255,0.7); }"
            )


# ── Filter Button ──────────────────────────────────────────────

class _FilterButton(QPushButton):
    """Small filter pill for audit tab."""
    def __init__(self, label, parent=None):
        super().__init__(label, parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(24)
        self._update_style()
        self.toggled.connect(lambda: self._update_style())

    def _update_style(self):
        if self.isChecked():
            self.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,0.15); "
                "color: rgba(255,255,255,0.9); border: 1px solid rgba(255,255,255,0.25); "
                "border-radius: 12px; padding: 2px 10px; font-size: 11px; }"
            )
        else:
            self.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,0.04); "
                "color: rgba(255,255,255,0.4); border: 1px solid rgba(255,255,255,0.08); "
                "border-radius: 12px; padding: 2px 10px; font-size: 11px; }"
                "QPushButton:hover { background: rgba(255,255,255,0.08); }"
            )


# ── Usage Tab ───────────────────────────────────────────────────

class _UsageTab(QWidget):
    """Token usage dashboard with per-agent breakdowns."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._period_days = None  # None = all time
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(12)

        # Period selector
        period_row = QHBoxLayout()
        period_row.setSpacing(6)
        self._period_btns = {}
        for label, days in [("Today", 1), ("7 days", 7), ("30 days", 30), ("All", None)]:
            btn = _FilterButton(label)
            btn.setChecked(days is None)
            btn.clicked.connect(lambda _, d=days: self._set_period(d))
            period_row.addWidget(btn)
            self._period_btns[days] = btn
        period_row.addStretch()
        layout.addLayout(period_row)

        # Stats container (will be rebuilt on refresh)
        self._stats_scroll = QScrollArea()
        self._stats_scroll.setWidgetResizable(True)
        self._stats_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._stats_widget = QWidget()
        self._stats_layout = QVBoxLayout(self._stats_widget)
        self._stats_layout.setContentsMargins(0, 0, 0, 0)
        self._stats_layout.setSpacing(8)
        self._stats_scroll.setWidget(self._stats_widget)
        layout.addWidget(self._stats_scroll)

    def _set_period(self, days):
        self._period_days = days
        for d, btn in self._period_btns.items():
            btn.setChecked(d == days)
        self.refresh()

    def refresh(self):
        """Reload usage data and rebuild the display."""
        # Clear existing content
        while self._stats_layout.count():
            item = self._stats_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            from core.usage import get_all_agents_usage, format_tokens, format_duration
            agents = get_all_agents_usage(self._period_days)
        except Exception as e:
            lbl = QLabel(f"Failed to load usage data: {e}")
            lbl.setStyleSheet("color: rgba(255,100,100,0.7); font-size: 12px;")
            self._stats_layout.addWidget(lbl)
            self._stats_layout.addStretch()
            return

        if not agents or all(a["total_calls"] == 0 for a in agents):
            lbl = QLabel("No usage data yet. Stats will appear after inference calls.")
            lbl.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 13px;")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setContentsMargins(0, 40, 0, 0)
            self._stats_layout.addWidget(lbl)
            self._stats_layout.addStretch()
            return

        # Totals bar
        total_calls = sum(a["total_calls"] for a in agents)
        total_tokens = sum(a["total_tokens"] for a in agents)
        total_duration = sum(a["total_duration_ms"] for a in agents)
        total_tools = sum(a["total_tools"] for a in agents)

        totals = QWidget()
        totals.setStyleSheet(
            "QWidget { background: rgba(255,255,255,0.04); border-radius: 8px; }"
        )
        totals_layout = QHBoxLayout(totals)
        totals_layout.setContentsMargins(16, 12, 16, 12)

        for label, value in [
            ("Inferences", str(total_calls)),
            ("Tokens (est.)", format_tokens(total_tokens)),
            ("Time", format_duration(total_duration)),
            ("Tool Calls", str(total_tools)),
        ]:
            col = QVBoxLayout()
            col.setSpacing(2)
            val_lbl = QLabel(value)
            val_lbl.setStyleSheet(
                "color: rgba(255,255,255,0.95); font-size: 20px; font-weight: bold;"
            )
            val_lbl.setAlignment(Qt.AlignCenter)
            col.addWidget(val_lbl)
            desc_lbl = QLabel(label)
            desc_lbl.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 10px;")
            desc_lbl.setAlignment(Qt.AlignCenter)
            col.addWidget(desc_lbl)
            totals_layout.addLayout(col)

        self._stats_layout.addWidget(totals)

        # Per-agent cards
        for agent in agents:
            if agent["total_calls"] == 0:
                continue
            card = self._make_agent_card(agent)
            self._stats_layout.addWidget(card)

        self._stats_layout.addStretch()

    def _make_agent_card(self, agent: dict) -> QWidget:
        from core.usage import format_tokens, format_duration

        card = QWidget()
        card.setStyleSheet(
            "QWidget { background: rgba(255,255,255,0.03); border-radius: 8px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        # Header row: agent name + total tokens
        header = QHBoxLayout()
        name = QLabel(agent["display_name"])
        name.setStyleSheet(
            "color: rgba(255,255,255,0.9); font-size: 14px; font-weight: bold;"
        )
        header.addWidget(name)
        header.addStretch()
        tokens = QLabel(f"{format_tokens(agent['total_tokens'])} tokens")
        tokens.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 12px;")
        header.addWidget(tokens)
        layout.addLayout(header)

        # Stats row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)
        for label, value in [
            ("calls", str(agent["total_calls"])),
            ("in", format_tokens(agent["total_tokens_in"])),
            ("out", format_tokens(agent["total_tokens_out"])),
            ("time", format_duration(agent["total_duration_ms"])),
            ("tools", str(agent["total_tools"])),
        ]:
            stat = QLabel(f"{value} {label}")
            stat.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 11px;")
            stats_row.addWidget(stat)
        stats_row.addStretch()
        layout.addLayout(stats_row)

        # Source breakdown
        if agent.get("by_source"):
            src_row = QHBoxLayout()
            src_row.setSpacing(8)
            for src in agent["by_source"][:5]:
                pill = QLabel(f"{src['source']} ({src['calls']})")
                pill.setStyleSheet(
                    "color: rgba(255,255,255,0.35); font-size: 10px; "
                    "background: rgba(255,255,255,0.04); border-radius: 4px; "
                    "padding: 1px 6px;"
                )
                src_row.addWidget(pill)
            src_row.addStretch()
            layout.addLayout(src_row)

        return card


# ── Activity Tab ────────────────────────────────────────────────

_CATEGORY_BADGES = {
    "tool_call": ("TOOL", "#4a9eff"),
    "heartbeat": ("BEAT", "#9b59b6"),
    "inference": ("INFER", "#2ecc71"),
}

_CATEGORY_ORDER = ["tool_call", "heartbeat", "inference"]


class _ActivityCard(QWidget):
    """Single activity entry — click to expand/collapse detail."""

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self._item = item
        self._expanded = False
        self.setCursor(Qt.PointingHandCursor)
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(
            "QWidget { background: rgba(255,255,255,0.03); border-radius: 6px; }"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 6, 10, 6)
        self._layout.setSpacing(4)

        # Summary row
        row = QHBoxLayout()
        row.setSpacing(8)

        # Category badge
        cat = self._item.get("category", "")
        badge_text, badge_color = _CATEGORY_BADGES.get(cat, (cat.upper(), "#888"))
        badge = QLabel(badge_text)
        badge.setFixedWidth(44)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"color: {badge_color}; font-size: 9px; font-weight: bold; "
            f"background: rgba(255,255,255,0.05); border-radius: 4px; "
            f"padding: 2px 4px;"
        )
        row.addWidget(badge)

        # Flagged indicator
        if self._item.get("flagged"):
            flag = QLabel("!")
            flag.setFixedWidth(16)
            flag.setAlignment(Qt.AlignCenter)
            flag.setStyleSheet(
                "color: #ff6b6b; font-size: 11px; font-weight: bold; "
                "background: rgba(255,100,100,0.15); border-radius: 8px;"
            )
            row.addWidget(flag)

        # Action name
        action = QLabel(self._item.get("action", ""))
        action.setStyleSheet(
            "color: rgba(255,255,255,0.85); font-size: 12px; font-weight: bold;"
        )
        row.addWidget(action)

        # Agent name
        agent = QLabel(self._item.get("agent", "").replace("_", " "))
        agent.setStyleSheet("color: rgba(255,255,255,0.35); font-size: 11px;")
        row.addWidget(agent)

        row.addStretch()

        # Timestamp
        ts = self._item.get("timestamp", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts)
                time_str = dt.strftime("%H:%M:%S")
                date_str = dt.strftime("%b %d")
                ts_label = QLabel(f"{date_str}  {time_str}")
            except (ValueError, TypeError):
                ts_label = QLabel(ts[:19])
            ts_label.setStyleSheet("color: rgba(255,255,255,0.3); font-size: 11px;")
            row.addWidget(ts_label)

        self._layout.addLayout(row)

        # Detail (hidden initially)
        self._detail_widget = QLabel()
        self._detail_widget.setWordWrap(True)
        self._detail_widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._detail_widget.setStyleSheet(
            "color: rgba(255,255,255,0.5); font-size: 11px; "
            "background: rgba(255,255,255,0.03); border-radius: 4px; "
            "padding: 8px; font-family: monospace;"
        )
        detail_text = self._item.get("detail", "")
        # Format JSON nicely if it looks like JSON
        if detail_text.startswith("{") or detail_text.startswith("["):
            try:
                parsed = json.loads(detail_text)
                detail_text = json.dumps(parsed, indent=2)
            except (json.JSONDecodeError, TypeError):
                pass
        if len(detail_text) > 1000:
            detail_text = detail_text[:1000] + "\n..."
        self._detail_widget.setText(detail_text or "(no detail)")
        self._detail_widget.hide()
        self._layout.addWidget(self._detail_widget)

    def mousePressEvent(self, event):
        self._expanded = not self._expanded
        self._detail_widget.setVisible(self._expanded)
        self.setStyleSheet(
            "QWidget { background: rgba(255,255,255,0.06); border-radius: 6px; }"
            if self._expanded else
            "QWidget { background: rgba(255,255,255,0.03); border-radius: 6px; }"
        )


class _ActivityTab(QWidget):
    """Scrollable audit log with search and filter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter = "all"
        self._agent_filter = "all"
        self._items = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(8)

        # Search bar
        self._search = QLineEdit()
        self._search.setObjectName("searchInput")
        self._search.setPlaceholderText("Search activity...")
        self._search.textChanged.connect(self._rebuild_list)
        layout.addWidget(self._search)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)

        self._filter_btns = {}
        for label, key in [("All", "all"), ("Tools", "tool_call"),
                           ("Heartbeats", "heartbeat"), ("Inference", "inference"),
                           ("Flagged", "flagged")]:
            btn = _FilterButton(label)
            btn.setChecked(key == "all")
            btn.clicked.connect(lambda _, k=key: self._set_filter(k))
            filter_row.addWidget(btn)
            self._filter_btns[key] = btn

        filter_row.addStretch()

        # Agent filter combo
        self._agent_combo = QComboBox()
        self._agent_combo.addItem("All agents")
        self._agent_combo.setStyleSheet(
            "QComboBox { background: rgba(255,255,255,0.06); "
            "border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; "
            "color: rgba(255,255,255,0.6); padding: 2px 8px; font-size: 11px; "
            "min-width: 100px; }"
        )
        self._agent_combo.currentTextChanged.connect(self._on_agent_changed)
        filter_row.addWidget(self._agent_combo)

        layout.addLayout(filter_row)

        # Count label
        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: rgba(255,255,255,0.3); font-size: 11px;")
        layout.addWidget(self._count_label)

        # Scrollable list
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        self._scroll.setWidget(self._list_widget)
        layout.addWidget(self._scroll)

    def _set_filter(self, key):
        self._filter = key
        for k, btn in self._filter_btns.items():
            btn.setChecked(k == key)
        self._rebuild_list()

    def _on_agent_changed(self, text):
        self._agent_filter = "all" if text == "All agents" else text.replace(" ", "_")
        self._rebuild_list()

    def refresh(self):
        """Reload activity data from all agent databases."""
        try:
            from core.usage import get_all_activity
            self._items = get_all_activity(days=30, limit=500)
        except Exception as e:
            self._items = []
            print(f"  [audit] Failed to load activity: {e}")

        # Update agent combo
        agents = sorted(set(it["agent"] for it in self._items))
        current = self._agent_combo.currentText()
        self._agent_combo.blockSignals(True)
        self._agent_combo.clear()
        self._agent_combo.addItem("All agents")
        for a in agents:
            self._agent_combo.addItem(a.replace("_", " "))
        if current in [self._agent_combo.itemText(i) for i in range(self._agent_combo.count())]:
            self._agent_combo.setCurrentText(current)
        self._agent_combo.blockSignals(False)

        self._rebuild_list()

    def _rebuild_list(self):
        """Filter and display activity items."""
        # Clear existing
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        query = self._search.text().lower().strip()
        shown = 0

        for item in self._items:
            # Category filter
            if self._filter == "flagged":
                if not item.get("flagged"):
                    continue
            elif self._filter != "all" and item.get("category") != self._filter:
                continue

            # Agent filter
            if self._agent_filter != "all" and item.get("agent") != self._agent_filter:
                continue

            # Search
            if query:
                searchable = f"{item.get('action', '')} {item.get('detail', '')} {item.get('agent', '')}".lower()
                if query not in searchable:
                    continue

            card = _ActivityCard(item)
            self._list_layout.addWidget(card)
            shown += 1

            if shown >= 200:
                break

        self._count_label.setText(
            f"{shown} of {len(self._items)} entries"
            if self._items else "No activity recorded yet"
        )
        self._list_layout.addStretch()


# ── Settings Modal ──────────────────────────────────────────────

class SettingsModal(QWidget):
    """Full-screen tabbed settings modal."""
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsModal")
        self.setStyleSheet(_STYLE)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._controls = {}
        self._build_ui()
        self.hide()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header bar
        header = QHBoxLayout()
        header.setContentsMargins(24, 16, 24, 8)
        title = QLabel("Settings")
        title.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: rgba(255,255,255,0.9);"
        )
        header.addWidget(title)
        header.addStretch()

        close_btn = QPushButton("×")
        close_btn.setObjectName("closeButton")
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self._close)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # Tab bar
        tab_bar = QHBoxLayout()
        tab_bar.setContentsMargins(24, 0, 24, 12)
        tab_bar.setSpacing(6)

        self._tab_btns = {}
        for i, (label, icon) in enumerate([
            ("Settings", ""),
            ("Usage", ""),
            ("Activity", ""),
        ]):
            btn = _TabButton(label)
            btn.setChecked(i == 0)
            btn.clicked.connect(lambda _, idx=i: self._switch_tab(idx))
            tab_bar.addWidget(btn)
            self._tab_btns[i] = btn
        tab_bar.addStretch()
        layout.addLayout(tab_bar)

        # Stacked widget for tab content
        self._stack = QStackedWidget()

        # Tab 0: Settings
        self._settings_scroll = QScrollArea()
        self._settings_scroll.setWidgetResizable(True)
        self._settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        settings_content = QWidget()
        self._content_layout = QVBoxLayout(settings_content)
        self._content_layout.setContentsMargins(24, 8, 24, 24)
        self._content_layout.setSpacing(4)
        self._build_settings_sections()
        self._content_layout.addStretch()

        # Save/Apply buttons
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("saveButton")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._save_settings)
        save_row.addWidget(save_btn)
        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("saveButton")
        apply_btn.setCursor(Qt.PointingHandCursor)
        apply_btn.clicked.connect(self._apply_settings)
        save_row.addWidget(apply_btn)
        save_row.addStretch()
        self._content_layout.addLayout(save_row)

        self._settings_scroll.setWidget(settings_content)
        self._stack.addWidget(self._settings_scroll)

        # Tab 1: Usage
        self._usage_tab = _UsageTab()
        self._stack.addWidget(self._usage_tab)

        # Tab 2: Activity
        self._activity_tab = _ActivityTab()
        self._stack.addWidget(self._activity_tab)

        layout.addWidget(self._stack)

    def _switch_tab(self, idx):
        for i, btn in self._tab_btns.items():
            btn.setChecked(i == idx)
        self._stack.setCurrentIndex(idx)

        # Refresh data tabs when switching to them
        if idx == 1:
            self._usage_tab.refresh()
        elif idx == 2:
            self._activity_tab.refresh()

    def show(self):
        super().show()
        # Refresh data tabs
        if self._stack.currentIndex() == 1:
            self._usage_tab.refresh()
        elif self._stack.currentIndex() == 2:
            self._activity_tab.refresh()

    # ── Settings helpers (identical to original) ────────────────

    def _add_section(self, title):
        label = QLabel(title)
        label.setObjectName("sectionHeader")
        self._content_layout.addWidget(label)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(255,255,255,0.08);")
        self._content_layout.addWidget(line)

    def _add_slider(self, key, label, min_val, max_val, current, decimals=2, step=0.01):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setObjectName("settingLabel")
        lbl.setFixedWidth(160)
        row.addWidget(lbl)
        slider = QSlider(Qt.Horizontal)
        scale = 10 ** decimals
        slider.setMinimum(int(min_val * scale))
        slider.setMaximum(int(max_val * scale))
        slider.setValue(int(current * scale))
        slider.setSingleStep(int(step * scale))
        val_label = QLabel(f"{current:.{decimals}f}")
        val_label.setFixedWidth(50)
        val_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        val_label.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 12px;")
        def on_change(v, s=scale, d=decimals, vl=val_label):
            vl.setText(f"{v / s:.{d}f}")
        slider.valueChanged.connect(on_change)
        row.addWidget(slider, 1)
        row.addWidget(val_label)
        self._content_layout.addLayout(row)
        self._controls[key] = ("slider", slider, scale, decimals)

    def _add_combo(self, key, label, options, current):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setObjectName("settingLabel")
        lbl.setFixedWidth(160)
        row.addWidget(lbl)
        combo = QComboBox()
        combo.addItems(options)
        if current in options:
            combo.setCurrentText(current)
        row.addWidget(combo)
        row.addStretch()
        self._content_layout.addLayout(row)
        self._controls[key] = ("combo", combo)

    def _add_checkbox(self, key, label, checked):
        row = QHBoxLayout()
        cb = QCheckBox(label)
        cb.setChecked(checked)
        row.addWidget(cb)
        row.addStretch()
        self._content_layout.addLayout(row)
        self._controls[key] = ("checkbox", cb)

    def _add_spinbox(self, key, label, min_val, max_val, current, suffix=""):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setObjectName("settingLabel")
        lbl.setFixedWidth(160)
        row.addWidget(lbl)
        spin = QSpinBox()
        spin.setMinimum(min_val)
        spin.setMaximum(max_val)
        spin.setValue(current)
        if suffix:
            spin.setSuffix(f" {suffix}")
        row.addWidget(spin)
        row.addStretch()
        self._content_layout.addLayout(row)
        self._controls[key] = ("spinbox", spin)

    def _add_text(self, key, label, current, password=False):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setObjectName("settingLabel")
        lbl.setFixedWidth(160)
        row.addWidget(lbl)
        inp = QLineEdit()
        inp.setObjectName("settingsInput")
        inp.setText(str(current))
        if password:
            inp.setEchoMode(QLineEdit.Password)
        row.addWidget(inp, 1)
        self._content_layout.addLayout(row)
        self._controls[key] = ("text", inp)

    def _add_info(self, key, label, value):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setObjectName("settingLabel")
        lbl.setFixedWidth(160)
        row.addWidget(lbl)
        val = QLabel(str(value))
        val.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 12px;")
        val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(val)
        row.addStretch()
        self._content_layout.addLayout(row)
        self._controls[key] = ("info", val)

    # ── Build all settings sections ─────────────────────────────

    def _build_settings_sections(self):
        import config as cfg
        from core.agent_manager import discover_agents, get_agent_state

        # ── Agents ──
        self._add_section("AGENTS")
        self._agent_controls = {}
        agents = discover_agents()
        for agent in agents:
            name = agent["name"]
            display = agent["display_name"]
            state = get_agent_state(name)
            is_current = (name == cfg.AGENT_NAME)

            row = QHBoxLayout()
            label_text = f"  {display}"
            name_lbl = QLabel(label_text)
            name_lbl.setFixedWidth(140)
            if is_current:
                name_lbl.setStyleSheet(
                    "color: rgba(255,255,255,0.95); font-weight: bold; font-size: 13px;"
                )
            else:
                name_lbl.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 13px;")
            row.addWidget(name_lbl)

            enabled_cb = QCheckBox("Enabled")
            enabled_cb.setChecked(state.get("enabled", True))
            row.addWidget(enabled_cb)

            muted_cb = QCheckBox("Muted")
            muted_cb.setChecked(state.get("muted", False))
            row.addWidget(muted_cb)

            if not is_current:
                switch_btn = QPushButton("Switch")
                switch_btn.setObjectName("saveButton")
                switch_btn.setFixedWidth(70)
                switch_btn.setCursor(Qt.PointingHandCursor)
                switch_btn.clicked.connect(
                    lambda checked, a=name: self._switch_to_agent(a)
                )
                row.addWidget(switch_btn)
            else:
                current_lbl = QLabel("active")
                current_lbl.setStyleSheet("color: rgba(255,255,255,0.3); font-size: 11px;")
                row.addWidget(current_lbl)

            row.addStretch()
            self._content_layout.addLayout(row)
            self._agent_controls[name] = {
                "enabled": enabled_cb,
                "muted": muted_cb,
                "label": name_lbl,
            }

        # New agent button
        new_agent_row = QHBoxLayout()
        new_agent_btn = QPushButton("+ New Agent")
        new_agent_btn.setObjectName("saveButton")
        new_agent_btn.setFixedWidth(120)
        new_agent_btn.setCursor(Qt.PointingHandCursor)
        new_agent_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.7); "
            "border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; padding: 6px 12px; "
            "font-size: 12px; } "
            "QPushButton:hover { background: rgba(255,255,255,0.15); color: rgba(255,255,255,0.9); }"
        )
        new_agent_btn.clicked.connect(self._run_new_agent_flow)
        new_agent_row.addWidget(new_agent_btn)
        new_agent_row.addStretch()
        self._content_layout.addLayout(new_agent_row)

        # ── Agent Identity ──
        self._add_section("AGENT IDENTITY")
        self._add_info("agent_name", "Agent Slug", cfg.AGENT_NAME)
        self._add_text("agent_display_name", "Display Name", cfg.AGENT_DISPLAY_NAME)
        self._add_text("user_name", "User Name", cfg.USER_NAME)
        self._add_text("opening_line", "Opening Line", cfg.OPENING_LINE)
        self._add_text("wake_words", "Wake Words", ", ".join(cfg.WAKE_WORDS))

        # ── Per-Agent Tool Disabling ──
        self._add_section("TOOLS")
        self._tool_checkboxes = {}
        _toggleable_tools = [
            ("mcp__memory__defer_to_agent", "Agent deferral"),
            ("mcp__memory__send_telegram", "Telegram messaging"),
            ("mcp__memory__set_reminder", "Reminders"),
            ("mcp__memory__set_timer", "Timers"),
            ("mcp__memory__create_task", "Task scheduling"),
            ("mcp__memory__render_canvas", "Canvas overlay"),
            ("mcp__memory__write_note", "Write Obsidian notes"),
            ("mcp__memory__prompt_journal", "Journal prompting"),
            ("mcp__memory__update_emotional_state", "Emotional state"),
            ("mcp__memory__create_artefact", "Artefact creation"),
            ("mcp__memory__manage_schedule", "Schedule management"),
            ("mcp__puppeteer__*", "Browser (Puppeteer)"),
            ("mcp__fal__*", "Media generation (fal)"),
        ]
        _disabled = set(cfg.DISABLED_TOOLS)
        for tool_id, label in _toggleable_tools:
            cb = QCheckBox(label)
            cb.setChecked(tool_id not in _disabled)
            cb.setStyleSheet("color: rgba(255,255,255,0.7); font-size: 12px; padding-left: 8px;")
            self._content_layout.addWidget(cb)
            self._tool_checkboxes[tool_id] = cb

        # ── Display / Window ──
        self._add_section("WINDOW")
        self._add_spinbox("window_width", "Window Width",
                          300, 1920, cfg.WINDOW_WIDTH, suffix="px")
        self._add_spinbox("window_height", "Window Height",
                          400, 1080, cfg.WINDOW_HEIGHT, suffix="px")
        self._add_text("window_title", "Window Title",
                       cfg.AGENT.get("display", {}).get("title",
                           f"THE ATROPHIED MIND -- {cfg.AGENT_DISPLAY_NAME}"))
        self._add_checkbox("avatar_enabled", "Avatar Enabled", cfg.AVATAR_ENABLED)
        self._add_spinbox("avatar_resolution", "Avatar Resolution",
                          128, 1024, cfg.AVATAR_RESOLUTION)

        # ── Voice / TTS ──
        self._add_section("VOICE & TTS")
        self._add_combo("tts_backend", "TTS Backend",
                        ["elevenlabs", "fal", "none"], cfg.TTS_BACKEND)
        self._add_text("elevenlabs_api_key", "ElevenLabs API Key",
                       cfg.ELEVENLABS_API_KEY, password=True)
        self._add_text("elevenlabs_voice_id", "ElevenLabs Voice ID",
                       cfg.ELEVENLABS_VOICE_ID)
        self._add_combo("elevenlabs_model", "ElevenLabs Model",
                        ["eleven_v3", "eleven_v2", "eleven_multilingual_v2",
                         "eleven_turbo_v2_5", "eleven_flash_v2_5"],
                        cfg.ELEVENLABS_MODEL)
        self._add_slider("elevenlabs_stability", "Stability",
                         0.0, 1.0, cfg.ELEVENLABS_STABILITY)
        self._add_slider("elevenlabs_similarity", "Similarity",
                         0.0, 1.0, cfg.ELEVENLABS_SIMILARITY)
        self._add_slider("elevenlabs_style", "Style",
                         0.0, 1.0, cfg.ELEVENLABS_STYLE)
        self._add_slider("tts_playback_rate", "Playback Rate",
                         0.5, 2.0, cfg.TTS_PLAYBACK_RATE)
        self._add_text("fal_voice_id", "Fal Voice ID", cfg.FAL_VOICE_ID)

        # ── Input ──
        self._add_section("INPUT")
        self._add_combo("input_mode", "Input Mode",
                        ["dual", "voice", "text"], cfg.INPUT_MODE)
        self._add_text("ptt_key", "Push-to-Talk Key", cfg.PTT_KEY)
        self._add_checkbox("wake_word_enabled", "Wake Word Detection",
                           cfg.WAKE_WORD_ENABLED)
        self._add_spinbox("wake_chunk_seconds", "Wake Chunk Duration",
                          1, 10, cfg.WAKE_CHUNK_SECONDS, suffix="sec")

        # ── Notifications ──
        self._add_section("NOTIFICATIONS")
        self._add_checkbox("notifications_enabled", "macOS Notifications",
                           cfg.NOTIFICATIONS_ENABLED)

        # ── Audio Capture ──
        self._add_section("AUDIO CAPTURE")
        self._add_spinbox("sample_rate", "Sample Rate",
                          8000, 48000, cfg.SAMPLE_RATE, suffix="Hz")
        self._add_spinbox("max_record_sec", "Max Record Duration",
                          10, 300, cfg.MAX_RECORD_SEC, suffix="sec")

        # ── Inference ──
        self._add_section("INFERENCE")
        self._add_text("claude_bin", "Claude Binary", cfg.CLAUDE_BIN)
        self._add_combo("claude_effort", "Claude Effort",
                        ["low", "medium", "high"], cfg.CLAUDE_EFFORT)
        self._add_checkbox("adaptive_effort", "Adaptive Effort",
                           cfg.ADAPTIVE_EFFORT)

        # ── Memory ──
        self._add_section("MEMORY & CONTEXT")
        self._add_spinbox("context_summaries", "Context Summaries",
                          0, 20, cfg.CONTEXT_SUMMARIES)
        self._add_spinbox("max_context_tokens", "Max Context Tokens",
                          10000, 500000, cfg.MAX_CONTEXT_TOKENS)
        self._add_slider("vector_search_weight", "Vector Search Weight",
                         0.0, 1.0, cfg.VECTOR_SEARCH_WEIGHT)
        self._add_text("embedding_model", "Embedding Model", cfg.EMBEDDING_MODEL)
        self._add_spinbox("embedding_dim", "Embedding Dimensions",
                          64, 2048, cfg.EMBEDDING_DIM)

        # ── Session ──
        self._add_section("SESSION")
        self._add_spinbox("session_soft_limit", "Soft Limit",
                          10, 480, cfg.SESSION_SOFT_LIMIT_MINS, suffix="min")

        # ── Heartbeat ──
        self._add_section("HEARTBEAT")
        self._add_spinbox("heartbeat_start", "Active Start Hour",
                          0, 23, cfg.HEARTBEAT_ACTIVE_START, suffix="h")
        self._add_spinbox("heartbeat_end", "Active End Hour",
                          0, 23, cfg.HEARTBEAT_ACTIVE_END, suffix="h")
        self._add_spinbox("heartbeat_interval", "Interval",
                          5, 120, cfg.HEARTBEAT_INTERVAL_MINS, suffix="min")

        # ── Paths ──
        self._add_section("PATHS")
        self._add_text("obsidian_vault", "Obsidian Vault", str(cfg.OBSIDIAN_VAULT))
        self._add_info("db_path", "Database", str(cfg.DB_PATH))
        self._add_info("whisper_bin", "Whisper Binary", str(cfg.WHISPER_BIN))

        # ── Telegram ──
        self._add_section("TELEGRAM")
        self._add_text("telegram_bot_token", "Bot Token",
                       cfg.TELEGRAM_BOT_TOKEN, password=True)
        self._add_text("telegram_chat_id", "Chat ID", cfg.TELEGRAM_CHAT_ID)

        # ── About ──
        self._add_section("ABOUT")
        self._add_info("app_version", "Version", cfg.VERSION)
        self._add_info("build_root", "Install Path", str(cfg.BUNDLE_ROOT))

        # Check for updates
        update_row = QHBoxLayout()
        self._update_label = QLabel("")
        self._update_label.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 11px;")
        update_row.addWidget(self._update_label)
        update_row.addStretch()
        update_btn = QPushButton("Check for Updates")
        update_btn.setObjectName("saveButton")
        update_btn.setFixedWidth(150)
        update_btn.setCursor(Qt.PointingHandCursor)
        update_btn.clicked.connect(self._check_for_updates)
        update_row.addWidget(update_btn)
        self._content_layout.addLayout(update_row)

    # ── Update checking ─────────────────────────────────────────

    def _check_for_updates(self):
        import config as cfg
        self._update_label.setText("Checking...")
        self._update_label.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 11px;")
        QApplication.processEvents()
        try:
            subprocess.run(
                ["git", "fetch", "--quiet"],
                cwd=str(cfg.BUNDLE_ROOT),
                capture_output=True, timeout=15,
            )
            result = subprocess.run(
                ["git", "rev-list", "--count", "HEAD..@{u}"],
                cwd=str(cfg.BUNDLE_ROOT),
                capture_output=True, text=True, timeout=10,
            )
            behind = int(result.stdout.strip()) if result.returncode == 0 else 0
            if behind == 0:
                self._update_label.setText(f"v{cfg.VERSION} — up to date")
                self._update_label.setStyleSheet(
                    "color: rgba(100,255,100,0.7); font-size: 11px;")
            else:
                self._update_label.setText(
                    f"{behind} update{'s' if behind != 1 else ''} available")
                self._update_label.setStyleSheet(
                    "color: rgba(255,200,100,0.9); font-size: 11px;")
                self._offer_update(behind)
        except Exception as e:
            self._update_label.setText(f"Check failed: {e}")
            self._update_label.setStyleSheet(
                "color: rgba(255,100,100,0.7); font-size: 11px;")

    def _offer_update(self, behind: int):
        import config as cfg
        update_btn = QPushButton(f"Update Now ({behind})")
        update_btn.setObjectName("saveButton")
        update_btn.setFixedWidth(150)
        update_btn.setCursor(Qt.PointingHandCursor)
        update_btn.setStyleSheet(
            "QPushButton { background: rgba(100,200,100,0.2); color: rgba(100,255,100,0.9); "
            "border: 1px solid rgba(100,255,100,0.3); border-radius: 6px; padding: 6px 12px; "
            "font-size: 12px; font-weight: bold; } "
            "QPushButton:hover { background: rgba(100,200,100,0.35); }"
        )
        update_btn.clicked.connect(lambda: self._do_update(cfg.BUNDLE_ROOT))
        self._update_label.parent().layout().addWidget(update_btn)

    def _do_update(self, bundle_root):
        self._update_label.setText("Updating...")
        QApplication.processEvents()
        try:
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=str(bundle_root),
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                version_file = bundle_root / "VERSION"
                new_version = version_file.read_text().strip() if version_file.exists() else "?"
                self._update_label.setText(
                    f"Updated to v{new_version} — restart to apply")
                self._update_label.setStyleSheet(
                    "color: rgba(100,255,100,0.9); font-size: 11px;")
            else:
                self._update_label.setText(f"Update failed: {result.stderr[:80]}")
                self._update_label.setStyleSheet(
                    "color: rgba(255,100,100,0.7); font-size: 11px;")
        except Exception as e:
            self._update_label.setText(f"Update failed: {e}")
            self._update_label.setStyleSheet(
                "color: rgba(255,100,100,0.7); font-size: 11px;")

    # ── Agent management ─────────────────────────────────────────

    def _switch_to_agent(self, agent_name: str):
        companion = self.parent()
        if companion and hasattr(companion, 'switch_agent'):
            self._close()
            companion.switch_agent(agent_name)

    def _run_new_agent_flow(self):
        import config as cfg
        script = Path(cfg.BUNDLE_ROOT) / "scripts" / "create_agent.py"
        if not script.exists():
            return
        cmd = (
            f'tell application "Terminal" to do script '
            f'"cd {str(cfg.BUNDLE_ROOT).replace(chr(34), chr(92)+chr(34))} && '
            f'python3 {str(script).replace(chr(34), chr(92)+chr(34))}"'
        )
        subprocess.Popen(["osascript", "-e", cmd])

    # ── Settings read/apply/save ─────────────────────────────────

    def _get_value(self, key):
        if key not in self._controls:
            return None
        kind = self._controls[key][0]
        if kind == "slider":
            _, slider, scale, decimals = self._controls[key]
            return round(slider.value() / scale, decimals)
        elif kind == "combo":
            return self._controls[key][1].currentText()
        elif kind == "checkbox":
            return self._controls[key][1].isChecked()
        elif kind == "spinbox":
            return self._controls[key][1].value()
        elif kind == "text":
            return self._controls[key][1].text()
        elif kind == "info":
            return self._controls[key][1].text()
        return None

    def _apply_settings(self):
        import config as cfg
        from core.agent_manager import set_agent_state

        # Per-agent states
        for name, controls in self._agent_controls.items():
            set_agent_state(
                name,
                muted=controls["muted"].isChecked(),
                enabled=controls["enabled"].isChecked(),
            )

        companion = self.parent()
        if companion and hasattr(companion, '_agent_muted'):
            current = cfg.AGENT_NAME
            if current in self._agent_controls:
                companion._agent_muted = self._agent_controls[current]["muted"].isChecked()
                companion._muted = companion._global_muted or companion._agent_muted

        # Agent identity
        cfg.AGENT_DISPLAY_NAME = self._get_value("agent_display_name")
        cfg.USER_NAME = self._get_value("user_name")
        cfg.OPENING_LINE = self._get_value("opening_line")
        wake_str = self._get_value("wake_words") or ""
        new_wake = [w.strip() for w in wake_str.split(",") if w.strip()]
        wake_changed = new_wake != cfg.WAKE_WORDS
        cfg.WAKE_WORDS = new_wake

        # Window
        cfg.WINDOW_WIDTH = self._get_value("window_width")
        cfg.WINDOW_HEIGHT = self._get_value("window_height")
        cfg.AVATAR_ENABLED = self._get_value("avatar_enabled")
        cfg.AVATAR_RESOLUTION = self._get_value("avatar_resolution")

        # Voice / TTS
        cfg.TTS_BACKEND = self._get_value("tts_backend")
        cfg.ELEVENLABS_API_KEY = self._get_value("elevenlabs_api_key")
        cfg.ELEVENLABS_VOICE_ID = self._get_value("elevenlabs_voice_id")
        cfg.ELEVENLABS_MODEL = self._get_value("elevenlabs_model")
        cfg.ELEVENLABS_STABILITY = self._get_value("elevenlabs_stability")
        cfg.ELEVENLABS_SIMILARITY = self._get_value("elevenlabs_similarity")
        cfg.ELEVENLABS_STYLE = self._get_value("elevenlabs_style")
        cfg.TTS_PLAYBACK_RATE = self._get_value("tts_playback_rate")
        cfg.FAL_VOICE_ID = self._get_value("fal_voice_id")

        # Input
        cfg.INPUT_MODE = self._get_value("input_mode")
        cfg.PTT_KEY = self._get_value("ptt_key")
        cfg.WAKE_WORD_ENABLED = self._get_value("wake_word_enabled")
        cfg.WAKE_CHUNK_SECONDS = self._get_value("wake_chunk_seconds")

        # Notifications
        cfg.NOTIFICATIONS_ENABLED = self._get_value("notifications_enabled")

        # Audio
        cfg.SAMPLE_RATE = self._get_value("sample_rate")
        cfg.MAX_RECORD_SEC = self._get_value("max_record_sec")

        # Inference
        cfg.CLAUDE_BIN = self._get_value("claude_bin")
        cfg.CLAUDE_EFFORT = self._get_value("claude_effort")
        cfg.ADAPTIVE_EFFORT = self._get_value("adaptive_effort")

        # Memory
        cfg.CONTEXT_SUMMARIES = self._get_value("context_summaries")
        cfg.MAX_CONTEXT_TOKENS = self._get_value("max_context_tokens")
        cfg.VECTOR_SEARCH_WEIGHT = self._get_value("vector_search_weight")
        cfg.EMBEDDING_MODEL = self._get_value("embedding_model")
        cfg.EMBEDDING_DIM = self._get_value("embedding_dim")

        # Session
        cfg.SESSION_SOFT_LIMIT_MINS = self._get_value("session_soft_limit")

        # Heartbeat
        cfg.HEARTBEAT_ACTIVE_START = self._get_value("heartbeat_start")
        cfg.HEARTBEAT_ACTIVE_END = self._get_value("heartbeat_end")
        cfg.HEARTBEAT_INTERVAL_MINS = self._get_value("heartbeat_interval")

        # Paths
        vault_path = self._get_value("obsidian_vault")
        if vault_path:
            cfg.OBSIDIAN_VAULT = Path(vault_path)

        # Telegram
        cfg.TELEGRAM_BOT_TOKEN = self._get_value("telegram_bot_token")
        cfg.TELEGRAM_CHAT_ID = self._get_value("telegram_chat_id")

        # Per-agent tool disabling
        disabled = []
        for tool_id, cb in self._tool_checkboxes.items():
            if not cb.isChecked():
                disabled.append(tool_id)
        cfg.DISABLED_TOOLS = disabled
        from core.inference import reset_mcp_config
        reset_mcp_config()

        # Update env vars
        os.environ["TTS_BACKEND"] = cfg.TTS_BACKEND
        os.environ["ELEVENLABS_API_KEY"] = cfg.ELEVENLABS_API_KEY
        os.environ["ELEVENLABS_VOICE_ID"] = cfg.ELEVENLABS_VOICE_ID
        os.environ["ELEVENLABS_MODEL"] = cfg.ELEVENLABS_MODEL
        os.environ["ELEVENLABS_STABILITY"] = str(cfg.ELEVENLABS_STABILITY)
        os.environ["ELEVENLABS_SIMILARITY"] = str(cfg.ELEVENLABS_SIMILARITY)
        os.environ["ELEVENLABS_STYLE"] = str(cfg.ELEVENLABS_STYLE)
        os.environ["TTS_PLAYBACK_RATE"] = str(cfg.TTS_PLAYBACK_RATE)
        os.environ["INPUT_MODE"] = cfg.INPUT_MODE
        os.environ["CLAUDE_BIN"] = cfg.CLAUDE_BIN
        os.environ["CLAUDE_EFFORT"] = cfg.CLAUDE_EFFORT
        os.environ["ADAPTIVE_EFFORT"] = str(cfg.ADAPTIVE_EFFORT).lower()
        os.environ["WAKE_WORD_ENABLED"] = str(cfg.WAKE_WORD_ENABLED).lower()
        os.environ["AVATAR_ENABLED"] = str(cfg.AVATAR_ENABLED).lower()
        os.environ["NOTIFICATIONS_ENABLED"] = str(cfg.NOTIFICATIONS_ENABLED).lower()

        # Update audio player rate
        if hasattr(self.parent(), '_audio_player'):
            self.parent()._audio_player._rate = str(cfg.TTS_PLAYBACK_RATE)

        # Restart wake word listener if words changed
        companion = self.parent()
        if wake_changed and hasattr(companion, '_wake_listener'):
            if companion._wake_listener:
                companion._stop_wake_listener()
            if companion._wake_enabled:
                companion._start_wake_listener()

        print("  [Settings applied]")

    def _save_settings(self):
        self._apply_settings()
        import config as cfg

        # Save agent.json
        manifest_path = cfg.AGENT_DIR / "data" / "agent.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
        else:
            manifest = {}

        manifest["name"] = cfg.AGENT_NAME
        manifest["display_name"] = cfg.AGENT_DISPLAY_NAME
        manifest["user_name"] = cfg.USER_NAME
        manifest["opening_line"] = cfg.OPENING_LINE
        manifest["wake_words"] = cfg.WAKE_WORDS

        manifest.setdefault("voice", {})
        manifest["voice"]["tts_backend"] = cfg.TTS_BACKEND
        manifest["voice"]["elevenlabs_voice_id"] = cfg.ELEVENLABS_VOICE_ID
        manifest["voice"]["elevenlabs_model"] = cfg.ELEVENLABS_MODEL
        manifest["voice"]["elevenlabs_stability"] = cfg.ELEVENLABS_STABILITY
        manifest["voice"]["elevenlabs_similarity"] = cfg.ELEVENLABS_SIMILARITY
        manifest["voice"]["elevenlabs_style"] = cfg.ELEVENLABS_STYLE
        manifest["voice"]["fal_voice_id"] = cfg.FAL_VOICE_ID
        manifest["voice"]["playback_rate"] = cfg.TTS_PLAYBACK_RATE

        manifest.setdefault("display", {})
        manifest["display"]["window_width"] = cfg.WINDOW_WIDTH
        manifest["display"]["window_height"] = cfg.WINDOW_HEIGHT
        manifest["display"]["title"] = (
            self._get_value("window_title")
            or f"THE ATROPHIED MIND -- {cfg.AGENT_DISPLAY_NAME}"
        )

        manifest.setdefault("heartbeat", {})
        manifest["heartbeat"]["active_start"] = cfg.HEARTBEAT_ACTIVE_START
        manifest["heartbeat"]["active_end"] = cfg.HEARTBEAT_ACTIVE_END
        manifest["heartbeat"]["interval_mins"] = cfg.HEARTBEAT_INTERVAL_MINS

        manifest["disabled_tools"] = cfg.DISABLED_TOOLS

        manifest.setdefault("telegram", {})
        tg = manifest["telegram"]
        token_env = tg.get("bot_token_env", f"TELEGRAM_BOT_TOKEN_{cfg.AGENT_NAME.upper()}")
        chat_env = tg.get("chat_id_env", f"TELEGRAM_CHAT_ID_{cfg.AGENT_NAME.upper()}")
        manifest["telegram"]["bot_token_env"] = token_env
        manifest["telegram"]["chat_id_env"] = chat_env

        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"  [Saved agent.json: {manifest_path}]")

        # Save config.json
        user_cfg = {
            "AGENT": cfg.AGENT_NAME,
            "INPUT_MODE": cfg.INPUT_MODE,
            "WAKE_WORD_ENABLED": str(cfg.WAKE_WORD_ENABLED).lower(),
            "CLAUDE_BIN": cfg.CLAUDE_BIN,
            "CLAUDE_EFFORT": cfg.CLAUDE_EFFORT,
            "ADAPTIVE_EFFORT": str(cfg.ADAPTIVE_EFFORT).lower(),
            "AVATAR_ENABLED": str(cfg.AVATAR_ENABLED).lower(),
            "NOTIFICATIONS_ENABLED": str(cfg.NOTIFICATIONS_ENABLED).lower(),
            "OBSIDIAN_VAULT": str(cfg.OBSIDIAN_VAULT),
        }
        if cfg.ELEVENLABS_API_KEY:
            user_cfg["ELEVENLABS_API_KEY"] = cfg.ELEVENLABS_API_KEY
        if cfg.TELEGRAM_BOT_TOKEN:
            user_cfg[token_env] = cfg.TELEGRAM_BOT_TOKEN
        if cfg.TELEGRAM_CHAT_ID:
            user_cfg[chat_env] = cfg.TELEGRAM_CHAT_ID

        cfg.save_user_config(user_cfg)
        print(f"  [Saved config.json: {cfg.USER_DATA / 'config.json'}]")

    # ── Modal lifecycle ──────────────────────────────────────────

    def _close(self):
        self.hide()
        self.closed.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(14, 14, 16, 245))
        p.end()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._close()
        else:
            super().keyPressEvent(event)
