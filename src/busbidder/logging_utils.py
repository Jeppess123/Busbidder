"""Log file setup and the log_call decorator."""

import logging
import time
from functools import wraps

from .exceptions import BusBidderError

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging(log_path, level=logging.DEBUG):
    """Send log records to a file. The file is rewritten on every run."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("busbidder")
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)
    return root


def log_call(level=logging.DEBUG):
    """Log entry, duration and domain failures of the decorated function."""

    def decorator(function):
        logger = logging.getLogger(function.__module__)

        @wraps(function)
        def wrapper(*args, **kwargs):
            logger.log(level, "start %s", function.__qualname__)
            started = time.perf_counter()
            try:
                result = function(*args, **kwargs)
            except BusBidderError as error:
                # log it and let the caller handle it
                logger.warning("%s failed: %s", function.__qualname__, error)
                raise
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.log(level, "done  %s in %.1f ms", function.__qualname__, elapsed_ms)
            return result

        return wrapper

    return decorator
