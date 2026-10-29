"""Lyrics lookup: LRCLIB first, lyrics.ovh as a fallback."""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

USER_AGENT = "Lyrico/0.1 (personal lyrics viewer; https://github.com/OlegTheSnowman/lyrico)"
TIMEOUT = 8

LRCLIB_SEARCH = "https://lrclib.net/api/search?q={}"
LYRICS_OVH = "https://api.lyrics.ovh/v1/{}/{}"

INSTRUMENTAL = "Instrumental, no lyrics."

_TIMESTAMP = re.compile(r"\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]")
_SEPARATOR = re.compile(r"\s+[-\u2013\u2014]\s+|\s*[-\u2013\u2014]\s*$")


class SourceError(Exception):
    """A network or server problem, as opposed to simply finding nothing.

    The English template is kept apart from its values so the window can
    show a translated message."""

    retry_after = 0.0

    def __init__(self, template, **values):
        self.template = template
        self.values = values
        super().__init__(template.format(**values))


@dataclass
class Track:
    artist: str
    title: str
    album: str
    duration: float
    lyrics: str
    source: str

    def label(self):
        text = f"{self.artist} - {self.title}"
        if self.duration:
            seconds = int(round(self.duration))
            text += f" ({seconds // 60}:{seconds % 60:02d})"
        return text


def strip_timestamps(synced):
    lines = []
    for line in synced.splitlines():
        lines.append(_TIMESTAMP.sub("", line).strip())
    return "\n".join(lines).strip()


RETRY_DELAYS = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0)


def _get_json(url, delays=RETRY_DELAYS):
    """Fetch JSON, retrying a few times: LRCLIB often answers 503 to a query
    it has not cached yet, then succeeds a moment later. When the server
    says how long to wait (Retry-After), that wait is used instead."""
    for delay in delays + (None,):
        try:
            return _fetch_json(url)
        except SourceError as e:
            if delay is None:
                raise
            time.sleep(max(delay, e.retry_after or 0))


def _fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        host = urllib.parse.urlsplit(url).hostname
        error = SourceError("{host} is busy right now (error {code}). Try again in a moment.",
                            host=host, code=e.code)
        try:
            error.retry_after = min(float(e.headers.get("Retry-After") or 0), 10)
        except ValueError:
            pass
        raise error from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SourceError("Can't reach the lyrics server. Check the internet connection.") from e
    except ValueError as e:
        raise SourceError("The lyrics server sent a bad response. Try again in a moment.") from e


def parse_lrclib(items):
    tracks = []
    seen = set()
    for item in items or []:
        if item.get("instrumental"):
            lyrics = INSTRUMENTAL
        else:
            lyrics = (item.get("plainLyrics") or "").strip()
            if not lyrics and item.get("syncedLyrics"):
                lyrics = strip_timestamps(item["syncedLyrics"])
        if not lyrics:
            continue
        track = Track(
            artist=(item.get("artistName") or "").strip(),
            title=(item.get("trackName") or "").strip(),
            album=(item.get("albumName") or "").strip(),
            duration=item.get("duration") or 0,
            lyrics=lyrics,
            source="LRCLIB",
        )
        key = (track.artist.lower(), track.title.lower(), track.lyrics)
        if key in seen:
            continue
        seen.add(key)
        tracks.append(track)
    return tracks


def split_artist_title(query):
    """Split "artist - title" into its parts, or return None."""
    parts = _SEPARATOR.split(query, maxsplit=1)
    if len(parts) != 2:
        return None
    artist, title = parts[0].strip(), parts[1].strip()
    if not artist or not title:
        return None
    return artist, title


def search_lrclib(query):
    return parse_lrclib(_get_json(LRCLIB_SEARCH.format(urllib.parse.quote(query))))


def search_lyrics_ovh(artist, title):
    url = LYRICS_OVH.format(urllib.parse.quote(artist), urllib.parse.quote(title))
    data = _get_json(url)
    lyrics = ((data or {}).get("lyrics") or "").replace("\r\n", "\n").strip()
    if not lyrics:
        return []
    return [Track(artist, title, "", 0, lyrics, "lyrics.ovh")]


def artist_first(tracks, artist):
    """Put tracks by the given artist before the rest, keeping order."""
    wanted = artist.casefold()

    def matches(track):
        name = track.artist.casefold()
        return wanted in name or (name and name in wanted)

    return [t for t in tracks if matches(t)] + [t for t in tracks if not matches(t)]


def search(query):
    """Return a list of Track for the query. Raises SourceError only when
    every source failed with a network or server error."""
    query = query.strip()
    if not query:
        return []
    error = None
    try:
        tracks = search_lrclib(query)
        if tracks:
            return tracks
    except SourceError as e:
        error = e
    pair = split_artist_title(query)
    if pair:
        artist, title = pair
        try:
            tracks = search_lrclib(title)
            if tracks:
                return artist_first(tracks, artist)
        except SourceError as e:
            error = error or e
        try:
            tracks = search_lyrics_ovh(artist, title)
            if tracks:
                return tracks
        except SourceError as e:
            error = error or e
    if error:
        raise error
    return []


# Artists and their songs come from the iTunes Search API (free, no key).
# Lyrics are then looked up per song on LRCLIB, so only songs with lyrics are shown.

ITUNES_SEARCH = "https://itunes.apple.com/search?"
ITUNES_LOOKUP = "https://itunes.apple.com/lookup?"
# Patient but polite per-song checks: LRCLIB answers 503 or 429 with a
# Retry-After when busy, and _get_json waits at least that long.
SONG_CHECK_DELAYS = (1.0, 1.0, 2.0, 3.0)


@dataclass
class Artist:
    name: str
    artist_id: int
    genre: str

    def label(self):
        return f"{self.name} ({self.genre})" if self.genre else self.name


@dataclass
class Song:
    artist: str
    title: str
    album: str
    duration: float


def search_artists(query, limit=15):
    url = ITUNES_SEARCH + urllib.parse.urlencode(
        {"term": query, "entity": "musicArtist", "limit": limit})
    data = _get_json(url) or {}
    artists = []
    seen = set()
    for item in data.get("results", []):
        if item.get("artistId") in seen or not item.get("artistName"):
            continue
        seen.add(item["artistId"])
        artists.append(Artist(item["artistName"], item["artistId"], item.get("primaryGenreName", "")))
    return artists


def artist_songs(artist_id):
    """Every distinct song iTunes lists for the artist, oldest catalogue order kept."""
    url = ITUNES_LOOKUP + urllib.parse.urlencode({"id": artist_id, "entity": "song", "limit": 200})
    data = _get_json(url) or {}
    songs = []
    seen = set()
    for item in data.get("results", []):
        if item.get("wrapperType") != "track" or not item.get("trackName"):
            continue
        key = item["trackName"].casefold().strip()
        if key in seen:
            continue
        seen.add(key)
        songs.append(Song(item.get("artistName", ""), item["trackName"],
                          item.get("collectionName", ""), (item.get("trackTimeMillis") or 0) / 1000))
    return songs


def find_lyrics(artist, title):
    """Best LRCLIB match for one song by one artist, or None if it has no lyrics."""
    url = "https://lrclib.net/api/search?" + urllib.parse.urlencode(
        {"artist_name": artist, "track_name": title})
    tracks = parse_lrclib(_get_json(url, delays=SONG_CHECK_DELAYS))
    wanted = artist.casefold()
    for track in tracks:
        name = track.artist.casefold()
        if wanted in name or name in wanted:
            return track
    return None
