"""Run the tests and build dist/Lyrico.exe with its checksum, all locally.

Also writes dist/build.json with the version and commit, so the pre-push
hook can tell whether the exe matches the tag being pushed."""

import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
EXE = os.path.join(DIST, "Lyrico.exe")


def read_version():
    with open(os.path.join(ROOT, "lyrico", "__init__.py"), encoding="utf-8") as f:
        return re.search(r'__version__ = "([^"]+)"', f.read()).group(1)


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def tree_is_clean():
    return git("status", "--porcelain", "--untracked-files=no") == ""


def run_tests():
    subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, check=True)


def build():
    run_tests()  # compiles the translations first, see tests/conftest.py
    data = []
    locale = os.path.join("lyrico", "locale")
    for code in os.listdir(os.path.join(ROOT, locale)):
        mo = os.path.join(locale, code, "LC_MESSAGES", "lyrico.mo")
        if os.path.exists(os.path.join(ROOT, mo)):
            data += ["--add-data", f"{mo}{os.pathsep}{os.path.dirname(mo)}"]
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
                    "--name", "Lyrico", "--collect-all", "winrt", "--collect-submodules", "comtypes", "--collect-all", "accessible_output2", *data, "run.py"], cwd=ROOT, check=True)
    digest = hashlib.sha256()
    with open(EXE, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    with open(EXE + ".sha256", "w", encoding="ascii", newline="\n") as f:
        f.write(f"{digest.hexdigest()}  Lyrico.exe\n")
    info = {"version": read_version(), "commit": git("rev-parse", "HEAD"), "clean": tree_is_clean()}
    with open(os.path.join(DIST, "build.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    print(f"Built Lyrico {info['version']} from {info['commit'][:7]}"
          f"{'' if info['clean'] else ' (with uncommitted changes)'}.")
    return info


if __name__ == "__main__":
    build()
