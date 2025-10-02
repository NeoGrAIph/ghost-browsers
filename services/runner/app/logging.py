"""Logging helpers ensuring consistent structured fields across the runner."""

from __future__ import annotations

import logging

__all__ = ["configure_logging"]


_CONFIGURED = False


def configure_logging() -> None:
    """Initialise logging so that common context fields are always present.

    The runner enriches log records with ``session_id``, ``workstation_id`` and
    ``fingerprint_id`` metadata.  When a handler emits a record without these
    fields the standard library would normally raise ``KeyError`` if the
    formatter references them.  This helper installs a custom log record factory
    that guarantees the attributes exist with a ``"-"`` placeholder and updates
    the root logger's handlers to use a consistent format.

    Example:
        >>> configure_logging()
        >>> logger = logging.getLogger("runner.test")
        >>> logger.info("hello", extra={"session_id": "s-1"})
        hello  # doctest: +SKIP
    """

    global _CONFIGURED
    if _CONFIGURED:
        return

    format_string = (
        "%(asctime)s %(levelname)s %(name)s %(message)s "
        "session_id=%(session_id)s workstation_id=%(workstation_id)s "
        "fingerprint_id=%(fingerprint_id)s"
    )

    class RunnerFormatter(logging.Formatter):
        """Formatter that backfills missing context identifiers."""

        def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
            for field in ("session_id", "workstation_id", "fingerprint_id"):
                if not hasattr(record, field):
                    setattr(record, field, "-")
            return super().format(record)

    formatter = RunnerFormatter(format_string)

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=logging.INFO)
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)

    _CONFIGURED = True

