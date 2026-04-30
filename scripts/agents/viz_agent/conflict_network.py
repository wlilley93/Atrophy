#!/usr/bin/env python3
"""
Conflict actor network diagram - PNG delivered to Telegram.
Run: ~/.atrophy/venv/bin/python3 conflict_network.py [conflict_name]
Default: Sudan
"""
import sys
import os
import io
import sqlite3
from datetime import datetime

sys.path.insert(0, os.path.expanduser('~/.atrophy/venv/lib/python3.14/site-packages'))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from send_photo import send_photo

DB_PATH = os.path.expanduser('~/.atrophy/agents/general_montgomery/data/intelligence.db')

ENTITY_COLOURS = {
    'state': '#3498db',
    'non-state': '#e74c3c',
    'external': '#f39c12',
    'multilateral': '#2ecc71',
    'person': '#9b59b6',
}

REL_COLOURS = {
    'backs': '#2ecc71',
    'opposes': '#e74c3c',
    'supplies': '#f39c12',
    'allied': '#3498db',
    'hostile': '#c0392b',
    'supports': '#27ae60',
    'funds': '#f1c40f',
}


def load_graph(conflict_name):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT id FROM conflicts WHERE name LIKE ?", (f'%{conflict_name}%',))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None, None
    conflict_id = row[0]

    cur.execute("""
        SELECT e.name, e.type
        FROM conflict_actors ca
        JOIN entities e ON e.id = ca.entity_id
        WHERE ca.conflict_id = ?
    """, (conflict_id,))
    actors = cur.fetchall()

    actor_names = [a[0] for a in actors]
    if actor_names:
        placeholders = ','.join('?' * len(actor_names))
        cur.execute(f"""
            SELECT e1.name, e2.name, r.type, r.notes
            FROM relationships r
            JOIN entities e1 ON e1.id = r.from_id
            JOIN entities e2 ON e2.id = r.to_id
            WHERE (r.conflict_id = ? OR r.conflict_id IS NULL)
            AND (e1.name IN ({placeholders}) OR e2.name IN ({placeholders}))
        """, [conflict_id] + actor_names + actor_names)
        rels = cur.fetchall()
    else:
        rels = []

    conn.close()
    return actors, rels


def render(conflict_name, actors, rels):
    G = nx.DiGraph()
    for name, etype in actors:
        G.add_node(name, entity_type=etype)

    for src, tgt, rel_type, desc in (rels or []):
        for n, etype in [(src, 'external'), (tgt, 'external')]:
            if not G.has_node(n):
                G.add_node(n, entity_type=etype)
        G.add_edge(src, tgt, rel=rel_type or '')

    node_colours = [
        ENTITY_COLOURS.get(G.nodes[n].get('entity_type', 'external'), '#888888')
        for n in G.nodes()
    ]

    fig, ax = plt.subplots(figsize=(12, 8))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#16213e')
    ax.axis('off')

    pos = nx.spring_layout(G, seed=42, k=2.5)
    edge_colours = [REL_COLOURS.get(G.edges[e].get('rel', ''), '#555577') for e in G.edges()]

    nx.draw_networkx_nodes(G, pos, ax=ax, node_color=node_colours,
                           node_size=1800, alpha=0.9)
    nx.draw_networkx_labels(G, pos, ax=ax, font_size=8,
                            font_color='white', font_weight='bold')
    nx.draw_networkx_edges(G, pos, ax=ax, edge_color=edge_colours,
                           width=2, arrows=True, arrowsize=18,
                           connectionstyle='arc3,rad=0.08',
                           arrowstyle='-|>',
                           min_source_margin=28, min_target_margin=28)

    edge_labels = {(s, t): G.edges[s, t].get('rel', '') for s, t in G.edges()
                   if G.edges[s, t].get('rel')}
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, ax=ax,
                                  font_size=7, font_color='#dddddd',
                                  bbox=dict(boxstyle='round,pad=0.2',
                                            facecolor='#1a1a2e', alpha=0.7))

    legend_patches = [mpatches.Patch(color=c, label=l.title())
                      for l, c in ENTITY_COLOURS.items()]
    ax.legend(handles=legend_patches, loc='lower left', facecolor='#1a1a2e',
              edgecolor='#444466', labelcolor='white', fontsize=8)

    ax.set_title(f'{conflict_name} - Actor Network', color='white',
                 fontsize=13, fontweight='bold', pad=10)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    buf.seek(0)
    img = buf.read()
    plt.close()
    return img


def main():
    from send_photo import log
    conflict = sys.argv[1] if len(sys.argv) > 1 else 'Sudan'
    log.info('conflict_network: generating for %s', conflict)
    actors, rels = load_graph(conflict)
    if actors is None:
        log.warning('conflict_network: no conflict matching "%s" in DB', conflict)
        return
    log.info('conflict_network: %d actors, %d relationships', len(actors), len(rels or []))
    img = render(conflict, actors, rels)
    today = datetime.now().strftime('%d %b %Y')
    result = send_photo(img, f"{conflict} Actor Network | {today}")
    log.info('conflict_network: done, msg_id=%s', result.get('result', {}).get('message_id'))


if __name__ == '__main__':
    main()
