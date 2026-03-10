"""Idle loop controller.

Manages the three pre-rendered idle states:
  - idle_loop: neutral, at rest (default)
  - idle_thinking: slight downward gaze, processing
  - idle_listening: forward attention, receiving input

These are pre-rendered mp4 files that loop seamlessly.
The display layer calls into this module to get the current
idle video path and to switch states.
"""
from enum import Enum
from pathlib import Path

from config import IDLE_LOOP, IDLE_THINKING, IDLE_LISTENING


class IdleState(Enum):
    REST = "rest"
    THINKING = "thinking"
    LISTENING = "listening"


class IdleController:
    def __init__(self):
        self._state = IdleState.REST
        self._paths = {
            IdleState.REST: IDLE_LOOP,
            IdleState.THINKING: IDLE_THINKING,
            IdleState.LISTENING: IDLE_LISTENING,
        }

    @property
    def state(self) -> IdleState:
        return self._state

    @property
    def current_video(self) -> Path:
        return self._paths[self._state]

    def set_state(self, state: IdleState):
        self._state = state

    def rest(self):
        self._state = IdleState.REST

    def thinking(self):
        self._state = IdleState.THINKING

    def listening(self):
        self._state = IdleState.LISTENING

    def has_all_loops(self) -> bool:
        return all(p.exists() for p in self._paths.values())

    def missing_loops(self) -> list[str]:
        return [s.value for s, p in self._paths.items() if not p.exists()]
