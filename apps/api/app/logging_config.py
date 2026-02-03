from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(*, log_format: str = "json", log_level: str = "INFO") -> None:
    logger = logging.getLogger("reframe")
    if getattr(logger, "_reframe_configured", False):
        return

    logger.setLevel(log_level.upper())
    if log_format == "json":
        handler: logging.Handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

    logger.addHandler(handler)
    logger.propagate = False
    setattr(logger, "_reframe_configured", True)

