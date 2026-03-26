#!/usr/bin/env python3
"""
Meridian Institute org chart - PNG delivered to Telegram.
Run: ~/.atrophy/venv/bin/python3 org_chart.py
"""
import sys
import os
import io
from datetime import datetime

sys.path.insert(0, os.path.expanduser('~/.atrophy/venv/lib/python3.14/site-packages'))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from send_photo import send_photo

BG = '#1a1a2e'
CARD_BG = '#16213e'

TIER_COLOURS = {
    'command': '#c0392b',
    'analysis': '#2980b9',
    'research': '#27ae60',
    'support': '#8e44ad',
    'output': '#d35400',
}

# (label, tier, x, y, width)
NODES = [
    ('General Montgomery\nCommand', 'command', 0.50, 0.91, 0.22),

    ('Chief of Staff', 'support', 0.18, 0.76, 0.16),
    ('QC Agent', 'support', 0.82, 0.76, 0.14),

    ('SIGINT Analyst', 'analysis', 0.10, 0.59, 0.14),
    ('Economic IO', 'analysis', 0.28, 0.59, 0.14),
    ('Librarian', 'analysis', 0.46, 0.59, 0.13),
    ('Viz Agent', 'output', 0.64, 0.59, 0.13),
    ('Red Team', 'support', 0.82, 0.59, 0.13),

    ('RF: Gulf/Iran', 'research', 0.08, 0.41, 0.13),
    ('RF: Russia/UKR', 'research', 0.24, 0.41, 0.13),
    ('RF: UK Defence', 'research', 0.40, 0.41, 0.13),
    ('RF: Eur Security', 'research', 0.56, 0.41, 0.14),
    ('RF: Indo-Pacific', 'research', 0.73, 0.41, 0.14),

    ('AMB: USA', 'analysis', 0.07, 0.22, 0.10),
    ('AMB: Russia', 'analysis', 0.19, 0.22, 0.10),
    ('AMB: China', 'analysis', 0.31, 0.22, 0.10),
    ('AMB: Iran', 'analysis', 0.43, 0.22, 0.10),
    ('AMB: Israel', 'analysis', 0.55, 0.22, 0.10),
    ('AMB: UAE', 'analysis', 0.67, 0.22, 0.10),
    ('AMB: UK', 'analysis', 0.79, 0.22, 0.10),
    ('AMB: Ukraine', 'analysis', 0.91, 0.22, 0.10),
]

EDGES = [
    ('General Montgomery\nCommand', 'Chief of Staff'),
    ('General Montgomery\nCommand', 'QC Agent'),
    ('Chief of Staff', 'SIGINT Analyst'),
    ('Chief of Staff', 'Economic IO'),
    ('Chief of Staff', 'Librarian'),
    ('Chief of Staff', 'Viz Agent'),
    ('Chief of Staff', 'RF: Gulf/Iran'),
    ('Chief of Staff', 'RF: Russia/UKR'),
    ('Chief of Staff', 'RF: UK Defence'),
    ('Chief of Staff', 'RF: Eur Security'),
    ('Chief of Staff', 'RF: Indo-Pacific'),
    ('Chief of Staff', 'AMB: USA'),
    ('Chief of Staff', 'AMB: Russia'),
    ('Chief of Staff', 'AMB: China'),
    ('Chief of Staff', 'AMB: Iran'),
    ('Chief of Staff', 'AMB: Israel'),
    ('Chief of Staff', 'AMB: UAE'),
    ('Chief of Staff', 'AMB: UK'),
    ('Chief of Staff', 'AMB: Ukraine'),
    ('QC Agent', 'Red Team'),
]

NODE_H = 0.065


def render():
    fig, ax = plt.subplots(figsize=(15, 9))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.axis('off')
    ax.set_xlim(0, 1)
    ax.set_ylim(0.10, 1.0)

    node_pos = {}
    for label, tier, x, y, w in NODES:
        colour = TIER_COLOURS.get(tier, '#555555')
        node_pos[label] = (x, y)
        rect = FancyBboxPatch((x - w/2, y - NODE_H/2), w, NODE_H,
                               boxstyle="round,pad=0.008",
                               facecolor=CARD_BG, edgecolor=colour,
                               linewidth=1.8, transform=ax.transData)
        ax.add_patch(rect)
        ax.text(x, y, label, ha='center', va='center',
                fontsize=6.2, color='white', fontweight='bold',
                transform=ax.transData, multialignment='center')

    for src, tgt in EDGES:
        if src in node_pos and tgt in node_pos:
            sx, sy = node_pos[src]
            tx, ty = node_pos[tgt]
            ax.annotate('', xy=(tx, ty + NODE_H/2),
                        xytext=(sx, sy - NODE_H/2),
                        arrowprops=dict(arrowstyle='->', color='#445577',
                                        lw=1.0))

    legend_items = [mpatches.Patch(color=c, label=t.title())
                    for t, c in TIER_COLOURS.items()]
    ax.legend(handles=legend_items, loc='lower right', facecolor=BG,
              edgecolor='#333355', labelcolor='white', fontsize=7.5, ncol=3)

    ax.set_title('Meridian Institute - Agent Architecture', color='white',
                 fontsize=13, fontweight='bold', y=0.97)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=160, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    buf.seek(0)
    img = buf.read()
    plt.close()
    return img


def main():
    img = render()
    today = datetime.now().strftime('%d %b %Y')
    result = send_photo(img, f"Meridian Institute - Agent Architecture | {today}")
    print(f"Sent: {result.get('ok')} | msg_id: {result.get('result', {}).get('message_id')}")


if __name__ == '__main__':
    main()
