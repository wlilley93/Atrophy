#!/bin/bash
# One-time setup: create venv for viz_agent at ~/.atrophy/venv
VENV="$HOME/.atrophy/venv"
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/python3" -m pip install --upgrade pip --quiet
"$VENV/bin/python3" -m pip install matplotlib networkx Pillow requests --quiet
echo "venv ready at $VENV"
