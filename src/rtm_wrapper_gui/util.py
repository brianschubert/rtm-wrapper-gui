"""
Misc utilities.
"""
import argparse
import logging.config


def setup_debug_root_logging(level: int = logging.NOTSET) -> None:
    """
    Configure the root logger with a basic debugging configuration.

    All records at the given level or above will be written to stdout.

    This function should be called once near the start of an application entry point,
    BEFORE any calls to ``logging.getLogger`` are made.

    Disables any existing loggers.
    """
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": True,
            "formatters": {
                "console": {
                    "format": "[{asctime},{msecs:06.2f}] {levelname:7s} ({threadName}:{name}) {funcName}:{lineno} {message}",
                    "style": "{",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                    "validate": True,
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "console",
                    "level": "NOTSET",  # Capture everything.
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"handlers": ["console"], "level": level},
        }
    )


def log_level(raw_arg: str) -> int:
    """
    Validate that the given CLI argument is a valid log level.

    Accepts both integer levels and level names.

    References
    ==========

    1. https://docs.python.org/3/library/logging.html#logging.getLevelName

    >>> log_level("10")
    10
    >>> log_level("INFO")
    20
    >>> log_level("FOO")
    Traceback (most recent call last):
    ...
    argparse.ArgumentTypeError: unable to interpret log level: FOO
    """
    try:
        # Even though standard log levels are limited to {0, ..., 50}, we don't
        # validate the value of the integer. Log levels like -1 or 1000 are permitted.
        return int(raw_arg)
    except (TypeError, ValueError):
        pass

    # Attempt to lookup log level from string.
    resolved_level = logging.getLevelName(raw_arg)
    if isinstance(resolved_level, int):
        # A log level was found for the given level name.
        return resolved_level

    raise argparse.ArgumentTypeError(f"unable to interpret log level: {raw_arg}")
