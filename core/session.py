"""Session lifecycle management."""
import time

from config import AGENT_DISPLAY_NAME, SESSION_SOFT_LIMIT_MINS
from core import memory
from core.inference import run_inference_oneshot


class Session:
    def __init__(self):
        self.session_id: int | None = None
        self.started_at: float | None = None
        self.turn_history: list[dict] = []
        self.cli_session_id: str | None = None
        self.mood: str | None = None

    def start(self) -> int:
        """Begin a new session.

        Looks up the previous CLI session ID so inference can resume
        the same conversation thread across companion restarts.
        """
        self.session_id = memory.start_session()
        self.started_at = time.time()
        self.turn_history = []

        # Continue the same CLI conversation thread
        self.cli_session_id = memory.get_last_cli_session_id()
        return self.session_id

    def set_cli_session_id(self, cli_id: str):
        """Store CLI session ID after first inference call creates it."""
        self.cli_session_id = cli_id
        memory.save_cli_session_id(self.session_id, cli_id)

    def add_turn(self, role: str, content: str, topic_tags: str = None, weight: int = 1):
        """Record a turn in memory and local history."""
        turn_id = memory.write_turn(
            self.session_id, role, content,
            topic_tags=topic_tags, weight=weight,
        )
        self.turn_history.append({
            "role": role,
            "content": content,
            "turn_id": turn_id,
        })
        return turn_id

    def update_mood(self, mood: str):
        self.mood = mood
        memory.update_session_mood(self.session_id, mood)

    def minutes_elapsed(self) -> float:
        if self.started_at is None:
            return 0
        return (time.time() - self.started_at) / 60

    def should_soft_limit(self) -> bool:
        return self.minutes_elapsed() >= SESSION_SOFT_LIMIT_MINS

    def end(self, system_prompt: str):
        """End the session - generate summary, close in DB."""
        if not self.turn_history or len(self.turn_history) < 4:
            memory.end_session(self.session_id)
            return

        turn_text = "\n".join(
            f"{'Will' if t['role'] == 'will' else AGENT_DISPLAY_NAME}: {t['content']}"
            for t in self.turn_history
        )

        summary_prompt = (
            "Summarise this conversation in 2-3 sentences. "
            "Focus on what mattered, not what was said. "
            "Note any new threads, shifts in mood, or observations worth remembering.\n\n"
            f"{turn_text}"
        )

        try:
            summary = run_inference_oneshot(
                [{"role": "user", "content": summary_prompt}],
                system="You are summarising a conversation for memory storage. Be concise and precise.",
            )
        except Exception as e:
            summary = f"[Summary generation failed: {e}]"

        memory.end_session(self.session_id, summary=summary)
        memory.write_summary(self.session_id, summary)
