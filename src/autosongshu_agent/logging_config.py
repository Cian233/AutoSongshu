"""Global logging configuration for AutoSongshu.

Provides structured logging with request tracing, configurable levels,
and both console + file output.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_context = threading.local()


class RequestTraceFilter(logging.Filter):
    """Injects session_id and request_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.session_id = getattr(_context, "session_id", "-")
        record.request_id = getattr(_context, "request_id", "-")
        return True


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for machine parsing."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "session_id": getattr(record, "session_id", "-"),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable console log formatter with colors."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[1;31m", # Bold Red
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        reset = self.RESET if color else ""
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        sid = getattr(record, "session_id", "-")
        if sid and sid != "-":
            sid = f"[{sid[:8]}] "
        else:
            sid = ""
        msg = record.getMessage()
        name = record.name.split(".")[-1] if "." in record.name else record.name
        line = f"{color}{record.levelname:<8}{reset} {ts} {sid}{name}: {msg}"
        if record.exc_info and record.exc_info[1]:
            line += "\n" + self.formatException(record.exc_info)
        return line


def setup_logging(
    level: str | None = None,
    log_dir: Path | str | None = None,
    json_logs: bool = False,
) -> None:
    """Configure global logging for AutoSongshu.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to AUTOSONGSHU_LOG_LEVEL env var or INFO.
        log_dir: Directory for log files. If None, logs only go to console.
        json_logs: If True, use JSON format for console output (for production).
    """
    # Determine log level
    log_level = (level or os.environ.get("AUTOSONGSHU_LOG_LEVEL", "INFO")).upper()
    numeric_level = getattr(logging, log_level, logging.INFO)

    # Root logger
    root_logger = logging.getLogger("autosongshu")
    root_logger.setLevel(numeric_level)

    # Clear existing handlers to avoid duplicates on reconfigure
    root_logger.handlers.clear()

    # Add trace filter
    trace_filter = RequestTraceFilter()

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(numeric_level)
    console_handler.addFilter(trace_filter)
    if json_logs or os.environ.get("AUTOSONGSHU_JSON_LOGS", "").lower() in ("1", "true"):
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(ConsoleFormatter())
    root_logger.addHandler(console_handler)

    # File handler (if log_dir provided)
    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path / "autosongshu.log",
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.addFilter(trace_filter)
        file_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    for noisy in ["httpx", "httpcore", "urllib3", "asyncio", "watchdog"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Log startup
    root_logger.info(
        "Logging initialized: level=%s, json=%s, log_dir=%s",
        log_level,
        json_logs,
        str(log_dir) if log_dir else "none",
    )


def set_trace_context(session_id: str | None = None, request_id: str | None = None) -> None:
    """Set the current request trace context for log correlation."""
    if session_id is not None:
        _context.session_id = session_id
    if request_id is not None:
        _context.request_id = request_id


def clear_trace_context() -> None:
    """Clear the current request trace context."""
    _context.session_id = "-"
    _context.request_id = "-"


def get_logger(name: str) -> logging.Logger:
    """Get a logger under the autosongshu namespace."""
    return logging.getLogger(f"autosongshu.{name}")


__all__ = [
    "setup_logging",
    "set_trace_context",
    "clear_trace_context",
    "get_logger",
    "RequestTraceFilter",
    "JSONFormatter",
    "ConsoleFormatter",
]
