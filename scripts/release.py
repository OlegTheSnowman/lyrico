"""Prepare a release locally: set the version, commit, tag and build.

Usage: python scripts/release.py 0.2.0

Nothing is pushed. Try dist/Lyrico.exe, then run
    git push --follow-tags
and the pre-push hook uploads the exe as a GitHub release."""

import os
import re
import sys

from build import ROOT, build, git, read_version, tree_is_clean


def set_version(version):
    path = os.path.join(ROOT, "lyrico", "__init__.py")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', text)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        sys.exit("Usage: python scripts/release.py X.Y.Z")
    version = sys.argv[1]
    tag = f"v{version}"
    if not tree_is_clean():
        sys.exit("Commit or stash your changes first.")
    if git("tag", "--list", tag):
        sys.exit(f"Tag {tag} already exists.")
    if read_version() != version:
        set_version(version)
        git("commit", "-am", f"chore(release): {tag}")
    git("tag", "-a", tag, "-m", f"Lyrico {version}")
    build()
    print(f"Tagged {tag}. Try dist/Lyrico.exe, then publish with: git push --follow-tags")


if __name__ == "__main__":
    main()
