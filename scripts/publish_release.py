"""Started in the background by the pre-push hook. Waits until the tag is on
the remote, then creates the GitHub release with gh and uploads the exe."""

import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, ".git", "lyrico-release.log")
WAIT_SECONDS = 300


def log(message):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")


def run(*args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True)


def tag_on_remote(remote, tag):
    result = run("git", "ls-remote", "--tags", remote, f"refs/tags/{tag}")
    return result.returncode == 0 and tag in result.stdout


def release_notes(tag):
    previous = run("git", "describe", "--tags", "--abbrev=0", f"{tag}^")
    span = f"{previous.stdout.strip()}..{tag}" if previous.returncode == 0 else tag
    subjects = run("git", "log", "--format=%s", span).stdout.splitlines()
    lines = [f"- {s}" for s in subjects if not s.startswith("chore(release)")]
    return "Changes:\n\n" + ("\n".join(lines) or "- Maintenance release.") + "\n"


def main():
    tag, staging, remote = sys.argv[1], sys.argv[2], sys.argv[3]
    log(f"{tag}: waiting for the push to reach {remote}")
    deadline = time.time() + WAIT_SECONDS
    while not tag_on_remote(remote, tag):
        if time.time() > deadline:
            log(f"{tag}: tag never appeared on {remote}; release not created")
            return
        time.sleep(3)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(release_notes(tag))
        notes = f.name
    files = [os.path.join(staging, "Lyrico.exe"), os.path.join(staging, "Lyrico.exe.sha256")]
    result = run("gh", "release", "create", tag, *files, "--verify-tag",
                 "--title", f"Lyrico {tag[1:]}", "--notes-file", notes)
    os.remove(notes)
    if result.returncode == 0:
        log(f"{tag}: published {result.stdout.strip()}")
    else:
        log(f"{tag}: gh release create failed: {result.stderr.strip()}")


if __name__ == "__main__":
    main()
