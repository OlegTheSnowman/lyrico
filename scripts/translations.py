"""Manage gettext translations with Babel.

    python scripts/translations.py update    extract strings to lyrico.pot and merge into every .po
    python scripts/translations.py compile   compile every .po to .mo (the build runs this)
    python scripts/translations.py add CODE  start a new language
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALE = os.path.join(ROOT, "lyrico", "locale")
POT = os.path.join(LOCALE, "lyrico.pot")
# Error templates are translated when shown, so their constructors count as markers too.
KEYWORDS = ["-k", "_", "-k", "ngettext:1,2", "-k", "SourceError", "-k", "UpdateError", "-k", "MediaError"]


def pybabel(*args):
    subprocess.run([sys.executable, "-m", "babel.messages.frontend", *args], cwd=ROOT, check=True)


def update():
    pybabel("extract", "-F", "babel.cfg", "--no-default-keywords", *KEYWORDS,
            "--no-location", "--sort-output", "--project", "Lyrico", "-o", POT, ".")
    if any(os.path.isdir(os.path.join(LOCALE, name, "LC_MESSAGES")) for name in os.listdir(LOCALE)):
        pybabel("update", "-D", "lyrico", "-i", POT, "-d", LOCALE, "--no-fuzzy-matching",
                "--width", "100")


def compile_all():
    pybabel("compile", "-D", "lyrico", "-d", LOCALE, "--statistics")


def add(code):
    pybabel("init", "-D", "lyrico", "-i", POT, "-d", LOCALE, "-l", code)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "update":
        update()
    elif command == "compile":
        compile_all()
    elif command == "add" and len(sys.argv) == 3:
        add(sys.argv[2])
    else:
        sys.exit(__doc__)
