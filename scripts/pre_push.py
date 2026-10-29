"""Git pre-push hook: run the tests, and when a version tag is pushed, make
sure dist/Lyrico.exe was built from it, then publish the GitHub release in
the background once the push has landed. No GitHub Actions minutes used."""

import json
import os
import shutil
import subprocess
import sys

from build import DIST, EXE, ROOT, build, git, read_version, run_tests, tree_is_clean

ZERO = "0" * 40


def pushed_version_tags():
    tags = []
    for line in sys.stdin.read().splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0].startswith("refs/tags/v") and parts[1] != ZERO:
            tags.append(parts[0][len("refs/tags/"):])
    return tags


def build_info():
    try:
        with open(os.path.join(DIST, "build.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def ensure_build(tag):
    commit = git("rev-list", "-n", "1", tag)
    version = tag[1:]
    info = build_info()
    if info.get("commit") == commit and info.get("version") == version and info.get("clean"):
        return
    if git("rev-parse", "HEAD") != commit or not tree_is_clean() or read_version() != version:
        sys.exit(f"dist/Lyrico.exe was not built from {tag}. Check out {tag} with a clean tree "
                 f"and run python scripts/build.py, then push again.")
    build()


def stage(tag):
    """Copy the release files aside so a later build can't change them mid-upload."""
    staging = os.path.join(ROOT, ".git", "release-staging", tag)
    os.makedirs(staging, exist_ok=True)
    for name in ("Lyrico.exe", "Lyrico.exe.sha256"):
        shutil.copy2(os.path.join(DIST, name), staging)
    return staging


def start_publisher(tag, staging, remote):
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    script = os.path.join(ROOT, "scripts", "publish_release.py")
    subprocess.Popen([sys.executable, script, tag, staging, remote], cwd=ROOT,
                     creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    remote = sys.argv[1] if len(sys.argv) > 1 else "origin"
    tags = pushed_version_tags()
    run_tests()
    for tag in tags:
        ensure_build(tag)
        start_publisher(tag, stage(tag), remote)
        print(f"Release {tag} will be published once the push finishes. "
              f"Log: .git/lyrico-release.log")
    if not os.path.exists(EXE) and tags:
        sys.exit("dist/Lyrico.exe is missing.")


if __name__ == "__main__":
    main()
