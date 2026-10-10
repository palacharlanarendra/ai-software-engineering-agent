import logging
import os
import re
from typing import Any

# Patterns to redact from logs
SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z-_]{35}"),  # Google API key pattern
    re.compile(r"(?i)(api[_-]?key|secret|token|password|bearer|authorization)[:=\s]+(['\"]?)([^\s'\"]+)\2"),
]

MAX_LOG_SNIPPET_LENGTH = 300


class SensitiveDataFilter(logging.Filter):
    """
    Log filter that masks API keys, secrets, and truncates large code snippets
    to prevent sensitive data leaks or log pollution.
    """

    def __init__(self, name: str = ""):
        super().__init__(name)

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.sanitize_message(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self.sanitize_arg(v) for k, v in record.args.items()}
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(self.sanitize_arg(a) for a in record.args)

        return True

    @classmethod
    def sanitize_message(cls, text: str) -> str:
        """Mask secrets and truncate oversized source content."""
        if not text:
            return text

        sanitized = text

        # 1. Mask exact known env secrets if present
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key and len(gemini_key) > 6 and gemini_key in sanitized:
            sanitized = sanitized.replace(gemini_key, f"{gemini_key[:4]}...[REDACTED]")

        # 2. Mask regex patterns
        for pattern in SECRET_PATTERNS:
            def replacer(match):
                full = match.group(0)
                if match.groups() and len(match.groups()) >= 3:
                    prefix = match.group(1)
                    return f"{prefix}=[REDACTED]"
                return f"{full[:4]}...[REDACTED]"

            sanitized = pattern.sub(replacer, sanitized)

        return sanitized

    @classmethod
    def sanitize_arg(cls, arg: Any) -> Any:
        if isinstance(arg, str):
            return cls.sanitize_message(arg)
        return arg


def configure_logging(level: int = logging.INFO) -> None:
    """Initialize structured and secure logging configuration."""
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid adding duplicate handlers on reload
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        handler.addFilter(SensitiveDataFilter())
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)
            # Ensure our filter is attached
            if not any(isinstance(f, SensitiveDataFilter) for f in handler.filters):
                handler.addFilter(SensitiveDataFilter())
