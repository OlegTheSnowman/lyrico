"""Short spoken announcements through the running screen reader (NVDA, JAWS
and others) using accessible_output2. Silent when no screen reader is running
or the package is missing."""

import threading

from .log import log

_output = None
_tried = False
_lock = threading.Lock()


def _get_output():
    global _output, _tried
    with _lock:
        if not _tried:
            _tried = True
            try:
                from accessible_output2.outputs.auto import Auto
                _output = Auto()
            except Exception:
                log.exception("speech: accessible_output2 unavailable, announcements are off")
                _output = None
        return _output


def speak(text, interrupt=True):
    """Say text through the screen reader. Call it on the UI thread."""
    output = _get_output()
    if output is None or not text:
        return
    try:
        output.speak(text, interrupt=interrupt)
    except Exception:
        log.exception("speech: speaking failed")
