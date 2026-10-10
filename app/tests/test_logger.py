import logging
import os
from unittest.mock import patch

from app.logger import SensitiveDataFilter, configure_logging


def test_sensitive_data_filter_redacts_api_key():
    filter_instance = SensitiveDataFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Connecting using API key AIzaSyA1234567890abcdefghijklmnopqrstuv",
        args=(),
        exc_info=None,
    )
    filter_instance.filter(record)
    assert "AIzaSyA1234567890abcdefghijklmnopqrstuv" not in record.msg
    assert "[REDACTED]" in record.msg


def test_sensitive_data_filter_redacts_env_variable():
    with patch.dict(os.environ, {"GEMINI_API_KEY": "secret_gemini_key_value_99999"}):
        filter_instance = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Sending payload with secret_gemini_key_value_99999 to service",
            args=(),
            exc_info=None,
        )
        filter_instance.filter(record)
        assert "secret_gemini_key_value_99999" not in record.msg
        assert "[REDACTED]" in record.msg


def test_sensitive_data_filter_redacts_token_patterns():
    filter_instance = SensitiveDataFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Headers: Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        args=(),
        exc_info=None,
    )
    filter_instance.filter(record)
    assert "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in record.msg
    assert "[REDACTED]" in record.msg


def test_configure_logging_attaches_filter():
    configure_logging()
    root_logger = logging.getLogger()
    assert len(root_logger.handlers) > 0
    handler = root_logger.handlers[0]
    has_filter = any(isinstance(f, SensitiveDataFilter) for f in handler.filters)
    assert has_filter
