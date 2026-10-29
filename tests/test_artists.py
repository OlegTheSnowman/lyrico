from lyrico import sources


def test_search_artists(monkeypatch):
    data = {"results": [
        {"artistName": "Test Band", "artistId": 1, "primaryGenreName": "Pop"},
        {"artistName": "Test Band", "artistId": 1, "primaryGenreName": "Pop"},
        {"artistName": "Other", "artistId": 2},
    ]}
    monkeypatch.setattr(sources, "_get_json", lambda url, delays=None: data)
    artists = sources.search_artists("test")
    assert [a.artist_id for a in artists] == [1, 2]
    assert artists[0].label() == "Test Band (Pop)"
    assert artists[1].label() == "Other"


def test_artist_songs_skips_duplicates_and_non_tracks(monkeypatch):
    data = {"results": [
        {"wrapperType": "artist", "artistName": "Test Band"},
        {"wrapperType": "track", "artistName": "Test Band", "trackName": "One",
         "collectionName": "Single", "trackTimeMillis": 180000},
        {"wrapperType": "track", "artistName": "Test Band", "trackName": "one", "collectionName": "Album"},
        {"wrapperType": "track", "artistName": "Test Band", "trackName": "Two"},
    ]}
    monkeypatch.setattr(sources, "_get_json", lambda url, delays=None: data)
    songs = sources.artist_songs(1)
    assert [s.title for s in songs] == ["One", "Two"]
    assert songs[0].duration == 180


def test_find_lyrics_requires_matching_artist(monkeypatch):
    items = [
        {"artistName": "Someone Else", "trackName": "One", "plainLyrics": "wrong"},
        {"artistName": "Test Band feat. Guest", "trackName": "One", "plainLyrics": "right"},
    ]
    monkeypatch.setattr(sources, "_get_json", lambda url, delays=None: items)
    assert sources.find_lyrics("Test Band", "One").lyrics == "right"
    monkeypatch.setattr(sources, "_get_json", lambda url, delays=None: items[:1])
    assert sources.find_lyrics("Test Band", "One") is None


def test_retry_after_is_honoured(monkeypatch):
    waits = []
    calls = []

    def busy(url):
        calls.append(url)
        if len(calls) < 2:
            error = sources.SourceError("{host} is busy right now (error {code}). Try again in a moment.",
                                        host="lrclib.net", code=503)
            error.retry_after = 3.0
            raise error
        return []

    monkeypatch.setattr(sources, "_fetch_json", busy)
    monkeypatch.setattr(sources.time, "sleep", waits.append)
    assert sources._get_json("http://x", delays=(1.0,)) == []
    assert waits == [3.0]
