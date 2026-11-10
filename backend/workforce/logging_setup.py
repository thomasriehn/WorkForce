"""Strukturierte Logs (JSON je Zeile) für Web, Worker und Scheduler."""
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from .config import get_settings

_STD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        for k, v in record.__dict__.items():
            if k not in _STD and not k.startswith("_"):
                data[k] = v if isinstance(v, (str, int, float, bool, type(None), list, dict)) else str(v)
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def setup_logging(component: str = "app") -> None:
    s = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if s.log_json else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(s.log_level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger(component).info("gestartet", extra={"component": component})
