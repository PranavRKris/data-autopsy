"""Background scheduler: wakes every few seconds and runs the projects whose schedule is due."""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("autopsy.service")


class Scheduler:
    def __init__(self, service, tick_seconds: float = 5.0):
        self.service = service
        self.tick_seconds = tick_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_tick: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if not self.running:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="autopsy-scheduler", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.wait(self.tick_seconds):
            try:
                self.last_tick = self.service.now()
                self.service.run_due()
            except Exception:
                log.exception("scheduler tick failed")
