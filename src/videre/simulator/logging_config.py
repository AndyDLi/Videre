"""
JSON structured logging with any extra fields added to the log record.
"""

import json
import logging

_RESERVED = set(logging.makeLogRecord({}).__dict__)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"level": record.levelname, "logger": record.name, "message": record.getMessage()}
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                data[key] = value
        return json.dumps(data, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
