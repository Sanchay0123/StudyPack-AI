"""Logging setup with secret redaction."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from config.settings import get_settings

_SECRET_PATTERNS = [
    re.compile(r"(AIza[0-9A-Za-z_\-]{20,})"),  # Google API keys
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)([^\s&\"']+)"),
    re.compile(r"(?i)(key=)([^\s&\"']+)"),
]


class RedactSecretsFilter(logging.Filter):
    """Masks anything resembling an API key before it reaches a log sink."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def redact(text: str) -> str:
    settings = get_settings()
    if settings.gemini_api_key:
        text = text.replace(settings.gemini_api_key, "***REDACTED***")
    for pattern in _SECRET_PATTERNS:
        if pattern.groups == 1:
            text = pattern.sub("***REDACTED***", text)
        else:
            text = pattern.sub(lambda m: m.group(1) + "***REDACTED***", text)
    return text


_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    settings = get_settings()
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger("studypack")
    root.setLevel(settings.log_level)
    file_handler = RotatingFileHandler(settings.logs_dir / "studypack.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.addFilter(RedactSecretsFilter())
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(RedactSecretsFilter())
    root.addHandler(file_handler)
    root.addHandler(console)
    root.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"studypack.{name}")
