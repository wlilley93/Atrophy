#!/usr/bin/env python3
"""
Maritime chokepoint trend chart - PNG delivered to Telegram.
Run: ~/.atrophy/venv/bin/python3 maritime_chart.py
"""
import sys
import os
import io
import sqlite3
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.expanduser('~/.atrophy/venv/lib/python3.14/site-packages'))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from send_photo import send_photo

DB_PATH = os.path.expanduser('~/.atrophy/agents/general_montgomery/data/intelligence.db')

COLOURS = {
    'Strait of Hormuz': '#e74c3c',
    'Bab el-Mandeb': '#f39c12',
    'Cape of Good Hope': '#3498db',
    'Dover Strait': '#2ecc71',
    'Bosporus Strait': '#9b59b6',
    'Taiwan Strait': '#1abc9c',
    'Suez Canal': '#e67e22',
    'Strait of Malacca': '#e91e63',
}


def load_series():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT chokepoint, change_pct, date(recorded_at) as day
        FROM maritime_history
        WHERE change_pct IS NOT NULL
        ORDER BY recorded_at ASC
    """)
    series = defaultdict(list)
    for chokepoint, pct, day in cur.fetchall():
        series[chokepoint].append((day, pct))
    conn.close()
    return series


def render(series):
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#16213e')

    for chokepoint, points in series.items():
        dates = [datetime.strptime(p[0], '%Y-%m-%d') for p in points]
        vals = [p[1] for p in points]
        colour = COLOURS.get(chokepoint, '#888888')
        marker = 'D' if len(dates) == 1 else 'o'
        ax.plot(dates, vals, label=chokepoint, color=colour,
                linewidth=2.5, marker=marker, markersize=6)

    ax.axhline(0, color='#666688', linewidth=0.8, linestyle='--')
    ax.set_title('Maritime Chokepoint Traffic', color='white',
                 fontsize=14, fontweight='bold', pad=12)
    ax.set_xlabel('Date', color='#aaaaaa', fontsize=10)
    ax.set_ylabel('Traffic Change %', color='#aaaaaa', fontsize=10)
    ax.tick_params(colors='#aaaaaa')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha='right')
    for spine in ax.spines.values():
        spine.set_edgecolor('#444466')
    ax.grid(color='#2a2a4a', linestyle='--', linewidth=0.6)
    ax.legend(loc='upper left', facecolor='#1a1a2e', edgecolor='#444466',
              labelcolor='white', fontsize=8)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    buf.seek(0)
    img = buf.read()
    plt.close()
    return img


def main():
    series = load_series()
    if not series:
        print("No maritime data in DB")
        return
    img = render(series)
    today = datetime.now().strftime('%d %b %Y')
    result = send_photo(img, f"Maritime Chokepoint Traffic | {today}")
    print(f"Sent: {result.get('ok')} | msg_id: {result.get('result', {}).get('message_id')}")


if __name__ == '__main__':
    main()
