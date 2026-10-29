from lyrico import sources
from lyrico.sources import INSTRUMENTAL, SourceError


def item(**overrides):
    base = {
        "trackName": "Test Song",
        "artistName": "Test Band",
        "albumName": "Test Album",
        "duration": 225.0,
        "instrumental": False,
        "plainLyrics": "first line\nsecond line",
        "syncedLyrics": None,
    }
    base.update(overrides)
    return base


def test_parse_plain_lyrics():
    tracks = sources.parse_lrclib([item()])
    assert len(tracks) == 1
    track = tracks[0]
    assert track.artist == "Test Band"
    assert track.title == "Test Song"
    assert track.lyrics == "first line\nsecond line"
    assert track.label() == "Test Band - Test Song (3:45)"


def test_synced_only_lyrics_lose_timestamps():
    synced = "[00:01.20] first line\n[00:05.00]second line\n[01:02.345] third"
    tracks = sources.parse_lrclib([item(plainLyrics="", syncedLyrics=synced)])
    assert tracks[0].lyrics == "first line\nsecond line\nthird"


def test_instrumental():
    tracks = sources.parse_lrclib([item(instrumental=True, plainLyrics=None)])
    assert tracks[0].lyrics == INSTRUMENTAL


def test_tracks_without_lyrics_are_skipped():
    assert sources.parse_lrclib([item(plainLyrics=None, syncedLyrics=None)]) == []
    assert sources.parse_lrclib([]) == []
    assert sources.parse_lrclib(None) == []


def test_duplicates_are_removed():
    tracks = sources.parse_lrclib([item(), item(albumName="Other"), item(plainLyrics="different")])
    assert len(tracks) == 2


def test_label_without_duration():
    tracks = sources.parse_lrclib([item(duration=None)])
    assert tracks[0].label() == "Test Band - Test Song"


def test_split_artist_title():
    assert sources.split_artist_title("Test Band - Test Song") == ("Test Band", "Test Song")
    assert sources.split_artist_title("Test Band \u2013 Test Song") == ("Test Band", "Test Song")
    assert sources.split_artist_title("AC-DC song") is None
    assert sources.split_artist_title("just words") is None


def test_fallback_used_when_lrclib_finds_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(sources, "search_lrclib", lambda q: [])

    def fake_ovh(artist, title):
        calls.append((artist, title))
        return [sources.Track(artist, title, "", 0, "words", "lyrics.ovh")]

    monkeypatch.setattr(sources, "search_lyrics_ovh", fake_ovh)
    tracks = sources.search("Test Band - Test Song")
    assert calls == [("Test Band", "Test Song")]
    assert tracks[0].source == "lyrics.ovh"


def test_no_fallback_without_separator(monkeypatch):
    monkeypatch.setattr(sources, "search_lrclib", lambda q: [])
    monkeypatch.setattr(sources, "search_lyrics_ovh", lambda a, t: 1 / 0)
    assert sources.search("test song") == []


def test_network_error_raised_when_all_sources_fail(monkeypatch):
    def fail(*args):
        raise SourceError("Network error")

    monkeypatch.setattr(sources, "search_lrclib", fail)
    monkeypatch.setattr(sources, "search_lyrics_ovh", fail)
    try:
        sources.search("Test Band - Test Song")
    except SourceError as e:
        assert str(e) == "Network error"
    else:
        raise AssertionError("expected SourceError")


def test_empty_query():
    assert sources.search("   ") == []


def test_title_only_search_when_full_query_fails(monkeypatch):
    queries = []

    def fake_lrclib(query):
        queries.append(query)
        if query == "Test Song":
            return [
                sources.Track("Cover Band", "Test Song", "", 0, "a", "LRCLIB"),
                sources.Track("Test Band", "Test Song", "", 0, "b", "LRCLIB"),
            ]
        raise SourceError("Server error 503")

    monkeypatch.setattr(sources, "search_lrclib", fake_lrclib)
    monkeypatch.setattr(sources, "search_lyrics_ovh", lambda a, t: 1 / 0)
    tracks = sources.search("test band - Test Song")
    assert queries == ["test band - Test Song", "Test Song"]
    assert [t.artist for t in tracks] == ["Test Band", "Cover Band"]


def test_get_json_retries_server_errors(monkeypatch):
    calls = []

    def flaky(url):
        calls.append(url)
        if len(calls) < 3:
            raise SourceError("Server error 503")
        return [{"ok": True}]

    monkeypatch.setattr(sources, "_fetch_json", flaky)
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    assert sources._get_json("http://x") == [{"ok": True}]
    assert len(calls) == 3


def test_get_json_gives_up_after_retries(monkeypatch):
    calls = []

    def broken(url):
        calls.append(url)
        raise SourceError("Server error 503")

    monkeypatch.setattr(sources, "_fetch_json", broken)
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    try:
        sources._get_json("http://x")
    except SourceError:
        pass
    else:
        raise AssertionError("expected SourceError")
    assert len(calls) == len(sources.RETRY_DELAYS) + 1
