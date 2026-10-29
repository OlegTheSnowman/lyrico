"""Self update from the latest GitHub release.

A release is expected to carry Lyrico.exe and Lyrico.exe.sha256. The new exe
is downloaded next to the running one, checked against the checksum, then
swapped in: Windows lets a running exe be renamed, so the old one becomes
Lyrico.old.exe and is deleted on the next start."""

import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__

REPO = "OlegTheSnowman/lyrico"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
EXE_NAME = "Lyrico.exe"
USER_AGENT = f"Lyrico/{__version__}"
TIMEOUT = 15


class UpdateError(Exception):
    """Same shape as sources.SourceError: an English template plus values."""

    def __init__(self, template, **values):
        self.template = template
        self.values = values
        super().__init__(template.format(**values))


@dataclass
class Release:
    tag: str
    version: tuple
    exe_url: str
    sha256: str
    sha256_url: str


def parse_version(text):
    try:
        return tuple(int(part) for part in text.strip().lstrip("vV").split("."))
    except (AttributeError, ValueError):
        return None


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def old_exe_path(exe_path):
    base, ext = os.path.splitext(exe_path)
    return base + ".old" + ext


def _open(url, accept="application/octet-stream"):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        return urllib.request.urlopen(request, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise UpdateError("GitHub answered with error {code}. Try again later.", code=e.code) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError("Can't reach GitHub. Check the internet connection.") from e


def parse_release(data):
    """Turn the GitHub API release JSON into a Release, or None if unusable."""
    version = parse_version(data.get("tag_name", ""))
    if version is None:
        return None
    exe_url = sha256 = sha256_url = ""
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name == EXE_NAME:
            exe_url = asset.get("browser_download_url", "")
            digest = asset.get("digest") or ""
            if digest.startswith("sha256:"):
                sha256 = digest.split(":", 1)[1].lower()
        elif name == EXE_NAME + ".sha256":
            sha256_url = asset.get("browser_download_url", "")
    return Release(data["tag_name"], version, exe_url, sha256, sha256_url)


def fetch_latest():
    response = _open(LATEST_URL, accept="application/vnd.github+json")
    if response is None:
        return None
    with response:
        try:
            data = json.load(response)
        except ValueError as e:
            raise UpdateError("GitHub answered with error {code}. Try again later.", code="JSON") from e
    return parse_release(data)


def newer_release(current=__version__):
    release = fetch_latest()
    if release and release.version > parse_version(current):
        return release
    return None


def expected_checksum(release):
    if release.sha256:
        return release.sha256
    if release.sha256_url:
        response = _open(release.sha256_url)
        if response is not None:
            with response:
                text = response.read().decode("ascii", "replace").split()
            if text:
                return text[0].lower()
    raise UpdateError("This release has no checksum, so it can't be checked safely.")


def download(release, dest_path, progress=None):
    """Download and verify the release exe into dest_path."""
    if not release.exe_url:
        raise UpdateError("This release has no Lyrico.exe.")
    expected = expected_checksum(release)
    part_path = dest_path + ".part"
    digest = hashlib.sha256()
    response = _open(release.exe_url)
    if response is None:
        raise UpdateError("This release has no Lyrico.exe.")
    try:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with response, open(part_path, "wb") as out:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except PermissionError as e:
        raise UpdateError(
            "Lyrico can't replace its own file in {folder}. Move Lyrico.exe to a folder "
            "you can write to, such as Documents.", folder=os.path.dirname(dest_path)) from e
    except OSError as e:
        _remove(part_path)
        raise UpdateError("Can't reach GitHub. Check the internet connection.") from e
    if digest.hexdigest() != expected:
        _remove(part_path)
        raise UpdateError("The download is damaged (checksum mismatch).")
    os.replace(part_path, dest_path)
    return dest_path


def swap(exe_path, new_path):
    """Put new_path in place of exe_path, keeping the old exe beside it."""
    old_path = old_exe_path(exe_path)
    try:
        _remove(old_path)
        os.replace(exe_path, old_path)
        try:
            os.replace(new_path, exe_path)
        except OSError:
            os.replace(old_path, exe_path)
            raise
    except OSError as e:
        raise UpdateError(
            "Lyrico can't replace its own file in {folder}. Move Lyrico.exe to a folder "
            "you can write to, such as Documents.", folder=os.path.dirname(exe_path)) from e
    return old_path


def restart(exe_path):
    # Without this a one-file PyInstaller exe started from another one would
    # reuse the parent's unpacked files, which are deleted when it exits.
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    subprocess.Popen([exe_path], env=env, close_fds=True)


def cleanup_old():
    if is_frozen():
        _remove(old_exe_path(sys.executable))


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
