"""
livekit_poc/events.py

Realtime transcript/events for the Agni agent.

The agent subprocess publishes small JSON events on the LiveKit room's
data channel (topic "agni.events"). The browser already joins the same
room, so it receives them with no new API and no change to existing APIs.

Emitting never blocks or breaks the voice pipeline: every failure is
swallowed (and logged once) so audio keeps working.

Event shape:
    {"v": 1, "seq": 12, "ts": 1760000000.123, "type": "user_final",
     "text": "hello"}

Event types:
    user_partial     live partial transcript while the caller speaks
    user_final       completed caller utterance (one turn)
    assistant_text   full text of the AI reply (sent when the LLM finishes)
    assistant_done   AI finished speaking (playback complete)
    interrupted      caller barged in, AI reply cancelled
    session_ended    agent is shutting down
"""

from __future__ import annotations

import asyncio
import json
import time

EVENTS_TOPIC = "agni.events"
EVENT_VERSION = 1


class EventEmitter:
    def __init__(self, room, topic: str = EVENTS_TOPIC) -> None:
        self._room = room
        self._topic = topic
        self._seq = 0
        self._warned = False
        self._tasks: set[asyncio.Task] = set()

    def emit(self, event_type: str, **fields) -> None:
        """Fire-and-forget. Safe to call from any async code in the agent."""
        self._seq += 1
        payload = {
            "v": EVENT_VERSION,
            "seq": self._seq,
            "ts": time.time(),
            "type": event_type,
            **fields,
        }
        try:
            task = asyncio.get_running_loop().create_task(self._publish(payload))
        except RuntimeError:
            return  # no running loop; nothing to do
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _publish(self, payload: dict) -> None:
        try:
            participant = self._room.local_participant
            await participant.publish_data(
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                reliable=True,
                topic=self._topic,
            )
        except Exception as exc:  # never break the voice pipeline
            if not self._warned:
                self._warned = True
                print(f"[EVENTS] publish failed (further errors hidden): {exc!r}")

    async def flush(self, timeout: float = 2.0) -> None:
        """Wait briefly for in-flight events (call before disconnecting)."""
        if self._tasks:
            await asyncio.wait(list(self._tasks), timeout=timeout)
