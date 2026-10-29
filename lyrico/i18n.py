"""Interface language through gettext.

Translations live in lyrico/locale/<code>/LC_MESSAGES/lyrico.po and are
compiled to .mo files by scripts/translations.py (the build does this)."""

import ctypes
import gettext
import os

DOMAIN = "lyrico"
LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locale")

# Each language is listed under its own name.
LANGUAGES = {"en": "English", "uk": "Українська"}

_current = "en"
_translation = gettext.NullTranslations()


def system_language():
    """Ukrainian if Windows is set to Ukrainian, otherwise English."""
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return "en"
    return "uk" if lang_id & 0x3FF == 0x22 else "en"


def set_language(code):
    global _current, _translation
    _current = code if code in LANGUAGES else "en"
    _translation = gettext.translation(DOMAIN, LOCALE_DIR, languages=[_current], fallback=True)
    return _current


def current_language():
    return _current


def _(text):
    return _translation.gettext(text)


def ngettext(singular, plural, count):
    return _translation.ngettext(singular, plural, count)


def results_count(count):
    return ngettext("{count} result.", "{count} results.", count).format(count=count)
