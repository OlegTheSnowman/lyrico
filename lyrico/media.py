"""What is playing now (from Windows' media controls), and opening Spotify search.

Spotify, browsers and most players report the current song to Windows, so
this needs no account or API key."""

import asyncio
import ctypes
import os
import time
import urllib.parse
import webbrowser
from ctypes import wintypes

PLAYING = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GW_OWNER = 4
SW_MAXIMIZE = 3


class MediaError(Exception):
    def __init__(self, template, **values):
        self.template = template
        self.values = values
        super().__init__(template.format(**values))


async def _sessions(app):
    """Media sessions, best first: playing ones, then the one Windows calls
    current, then the rest. With app, only sessions of that app."""
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
    )

    manager = await Manager.request_async()
    sessions = list(manager.get_sessions())
    current = manager.get_current_session()
    if app:
        wanted = app.casefold()
        sessions = [s for s in sessions if wanted in (s.source_app_user_model_id or "").casefold()]
        if current and current not in sessions:
            current = None
    playing = [s for s in sessions if s.get_playback_info().playback_status == PLAYING]
    return playing + ([current] if current else []) + sessions


async def _read_now_playing(app):
    for session in await _sessions(app):
        props = await session.try_get_media_properties_async()
        if props and props.title:
            return (props.artist or "").strip(), props.title.strip()
    return None


def now_playing(app=None):
    """Return (artist, title) of the song playing now, or None. With app, for
    example "spotify", only that app's player counts. Blocks; call it off the UI thread."""
    try:
        return asyncio.run(_read_now_playing(app))
    except ImportError as e:
        raise MediaError("Lyrico can't read what's playing on this computer.") from e
    except OSError as e:
        raise MediaError("Lyrico can't read what's playing on this computer.") from e


async def _control(action, app):
    # Spotify first; without it, whatever player Windows has.
    sessions = await _sessions(app) or await _sessions(None)
    if not sessions:
        return False
    session = sessions[0]
    method = {
        "next": session.try_skip_next_async,
        "previous": session.try_skip_previous_async,
        "play_pause": session.try_toggle_play_pause_async,
    }[action]
    return bool(await method())


def control(action, app="spotify"):
    """Send "next", "previous" or "play_pause" to the player. Returns False when
    there is no player or it refused. Blocks; call it off the UI thread."""
    try:
        return asyncio.run(_control(action, app))
    except (ImportError, OSError) as e:
        raise MediaError("Lyrico can't control the player on this computer.") from e


def open_spotify_search(query):
    """Open the Spotify app searching for query, or the Spotify web player if the
    app is missing. Returns True when the app was used."""
    try:
        os.startfile("spotify:search:" + urllib.parse.quote(query))
        return True
    except OSError:
        webbrowser.open("https://open.spotify.com/search/" + urllib.parse.quote(query))
        return False


def find_spotify_window():
    """The Spotify app's main window handle, or None."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    found = []

    def is_spotify(pid):
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return False
            return os.path.basename(buffer.value).casefold() == "spotify.exe"
        finally:
            kernel32.CloseHandle(handle)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if is_spotify(pid.value):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else None


def show_spotify(wait=5.0):
    """Maximize Spotify and bring it to the front, waiting up to `wait` seconds
    for its window to appear. Blocks; call it off the UI thread."""
    user32 = ctypes.windll.user32
    deadline = time.time() + wait
    while True:
        hwnd = find_spotify_window()
        if hwnd:
            user32.ShowWindow(hwnd, SW_MAXIMIZE)
            user32.SetForegroundWindow(hwnd)
            return True
        if time.time() > deadline:
            return False
        time.sleep(0.25)
