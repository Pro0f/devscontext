"""Logging configuration for DevsContext.

This module provides structured logging setup for the entire application.
All modules should use `logging.getLogger(__name__)` to get their logger.

Usage:
    from devscontext.logging import setup_logging, get_logger

    # At application startup
    setup_logging()

    # In each module
    logger = get_logger(__name__)
    logger.info("Operation completed", extra={"duration_ms": 150, "source": "jira"})
"""

import logging
import sys
from typing import Any

from devscontext.constants import LOG_DATE_FORMAT, LOG_FORMAT


class StructuredFormatter(logging.Formatter):
    """A formatter that outputs structured log messages.

    Includes extra fields in the log output for better observability.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record with structured fields.

        Args:
            record: The log record to format.

        Returns:
            Formatted log string.
        """
        # Get the base formatted message
        base_message = super().format(record)

        # Extract extra fields (exclude standard LogRecord attributes)
        standard_attrs = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "exc_info",
            "exc_text",
            "thread",
            "threadName",
            "taskName",
            "message",
        }

        extra_fields: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                extra_fields[key] = value

        # Append extra fields if present
        if extra_fields:
            fields_str = " | ".join(f"{k}={v}" for k, v in extra_fields.items())
            return f"{base_message} | {fields_str}"

        return base_message


def setup_logging(
    level: int = logging.INFO,
    *,
    include_timestamp: bool = True,
) -> None:
    """Configure logging for the application.

    Sets up a structured formatter with consistent output format.
    Should be called once at application startup.

    Args:
        level: The logging level (default: INFO).
        include_timestamp: Whether to include timestamps in output.
    """
    # Create formatter
    if include_timestamp:
        formatter = StructuredFormatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    else:
        formatter = StructuredFormatter("%(levelname)-8s | %(name)s | %(message)s")

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add stderr handler
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Set devscontext loggers to the specified level
    logging.getLogger("devscontext").setLevel(level)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger for the given module.

    This is a convenience wrapper around logging.getLogger that
    ensures consistent naming.

    Args:
        name: The module name (typically __name__).

    Returns:
        A configured Logger instance.
    """
    return logging.getLogger(name)


class LogContext:
    """Context manager for adding structured fields to log messages.

    Usage:
        with LogContext(logger, adapter="jira", ticket_id="PROJ-123"):
            logger.info("Fetching ticket")
            # The log will include: adapter=jira | ticket_id=PROJ-123
    """

    def __init__(self, logger: logging.Logger, **fields: Any) -> None:
        """Initialize the log context.

        Args:
            logger: The logger to use.
            **fields: Extra fields to include in all log messages.
        """
        self.logger = logger
        self.fields = fields
        self._old_factory: logging.Callable[..., logging.LogRecord] | None = None

    def __enter__(self) -> "LogContext":
        """Enter the context and set up the log record factory."""
        old_factory = logging.getLogRecordFactory()
        self._old_factory = old_factory
        fields = self.fields

        def record_factory(
            *args: Any,
            **kwargs: Any,
        ) -> logging.LogRecord:
            record = old_factory(*args, **kwargs)
            for key, value in fields.items():
                setattr(record, key, value)
            return record

        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, *args: Any) -> None:
        """Exit the context and restore the original log record factory."""
        if self._old_factory is not None:
            logging.setLogRecordFactory(self._old_factory)
