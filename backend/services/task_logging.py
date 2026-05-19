from __future__ import annotations

import logging
import traceback
from collections import deque
from datetime import datetime
from typing import Any, Callable

from loguru import logger as loguru_logger


class _ThreadLogHandler(logging.Handler):
    def __init__(self, owner: "TaskLogCapture"):
        super().__init__(level=logging.DEBUG)
        self.owner = owner

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self.owner.thread_id:
            return
        self.owner.append(
            level=record.levelname,
            message=record.getMessage(),
            source=record.name,
            created=record.created,
        )


class TaskLogCapture:
    """Capture loguru + stdlib logs for the current worker thread."""

    def __init__(self, max_entries: int = 400, on_append: Callable[[list[dict[str, Any]]], None] | None = None):
        self.max_entries = max_entries
        self.entries: deque[dict[str, Any]] = deque(maxlen=max_entries)
        self.thread_id: int | None = None
        self._handler: _ThreadLogHandler | None = None
        self._loguru_sink_id: int | None = None
        self.on_append = on_append

    def __enter__(self) -> "TaskLogCapture":
        import threading

        self.thread_id = threading.get_ident()
        self._handler = _ThreadLogHandler(self)
        root_logger = logging.getLogger()
        root_logger.addHandler(self._handler)

        self._loguru_sink_id = loguru_logger.add(
            self._write_loguru,
            level="DEBUG",
            enqueue=False,
            backtrace=False,
            diagnose=False,
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        root_logger = logging.getLogger()
        if self._handler is not None:
            root_logger.removeHandler(self._handler)
            self._handler = None
        if self._loguru_sink_id is not None:
            loguru_logger.remove(self._loguru_sink_id)
            self._loguru_sink_id = None

    def _write_loguru(self, message) -> None:
        record = message.record
        if self.thread_id is None or record["thread"].id != self.thread_id:
            return
        self.append(
            level=record["level"].name,
            message=record["message"],
            source=record["name"] or "loguru",
            created=record["time"].timestamp(),
        )

    def append(self, level: str, message: str, source: str | None = None, created: float | None = None) -> None:
        ts = datetime.fromtimestamp(created or datetime.now().timestamp()).strftime("%Y-%m-%d %H:%M:%S")
        self.entries.append({
            "timestamp": ts,
            "level": str(level or "INFO"),
            "source": str(source or "runtime"),
            "message": str(message or ""),
        })
        if self.on_append is not None:
            try:
                self.on_append(self.snapshot())
            except Exception:
                # Log capture should never break the worker itself.
                pass

    def capture_exception(self, exc: Exception, source: str = "runtime") -> None:
        self.append(
            level="ERROR",
            source=source,
            message="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip(),
        )

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self.entries)
