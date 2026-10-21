"""Live events to the browsers: every open WebSocket gets its own queue."""
import asyncio
import time


class Hub:
    def __init__(self):
        self.queues: set[asyncio.Queue] = set()
        self.recent_notifications: list[dict] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self.queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.queues.discard(q)

    def publish(self, event: dict) -> None:
        for q in list(self.queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # a stalled browser: drop it rather than grow without bound
                self.queues.discard(q)

    def notify(self, server: str | None, kind: str, text: str) -> None:
        event = {"type": "notify", "server": server, "kind": kind, "text": text, "t": time.time()}
        self.recent_notifications = (self.recent_notifications + [event])[-50:]
        self.publish(event)


hub = Hub()
