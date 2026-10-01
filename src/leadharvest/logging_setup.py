"""Rich console logging plus one JSON-lines file per run. Secrets are redacted."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

LOGGER_NAME = "leadharvest"
console = Console()

_SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret)[\"']?\s*[:=]\s*[\"']?)[^\s\"'&]+"),
    re.compile(r"(?i)(key=)[A-Za-z0-9_\-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1) + "[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


class JsonLinesFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "data", None)
        if isinstance(extra, dict):
            entry.update(extra)
        if record.exc_info:
            entry["traceback"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False, default=str)


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(LOGGER_NAME if not name else f"{LOGGER_NAME}.{name}")


def setup_console_logging(verbose: bool = False) -> None:
    root = logging.getLogger(LOGGER_NAME)
    if any(isinstance(h, RichHandler) for h in root.handlers):
        return
    handler = RichHandler(console=console, show_path=False, markup=False, rich_tracebacks=False)
    handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    handler.addFilter(RedactFilter())
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    root.propagate = False


def attach_run_log(log_dir: Path, run_id: str) -> logging.Handler:
    """Add a JSON-lines file handler for one run; remove it with detach_run_log."""
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_dir / f"run-{run_id}.jsonl", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(JsonLinesFormatter())
    handler.addFilter(RedactFilter())
    root = logging.getLogger(LOGGER_NAME)
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    return handler


def detach_run_log(handler: logging.Handler) -> None:
    logging.getLogger(LOGGER_NAME).removeHandler(handler)
    handler.close()
