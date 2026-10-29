"""A small log in %APPDATA%\\Lyrico\\lyrico.log for diagnosing sync and lookups.
It records what happened (sources, counts, errors), never lyric text."""

import logging
import logging.handlers
import os

log = logging.getLogger("lyrico")


def setup(directory):
    if log.handlers:
        return
    try:
        os.makedirs(directory, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(directory, "lyrico.log"), maxBytes=200_000, backupCount=1, encoding="utf-8")
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
