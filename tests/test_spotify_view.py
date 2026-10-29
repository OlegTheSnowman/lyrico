from lyrico.spotify_view import MIN_LINES, Node, pick_lines


def line(text, style="line"):
    return Node("other", style=style, children=[Node("text", text)])


def placeholder_lines(count, prefix="placeholder line"):
    return [line(f"{prefix} {i}") for i in range(count)]


def tree(*lyrics_nodes, sidebar=3):
    sidebar_nodes = [line(f"Playlist {i}", style="nav") for i in range(sidebar)]
    return Node("other", children=[
        Node("other", style="sidebar", children=sidebar_nodes),
        Node("other", style="lyrics", children=list(lyrics_nodes)),
    ])


def test_picks_the_container_with_most_lines():
    assert pick_lines(tree(*placeholder_lines(10))) == [f"placeholder line {i}" for i in range(10)]


def test_drops_a_differently_styled_last_line():
    nodes = placeholder_lines(9) + [line("Credits footer", style="footer")]
    assert pick_lines(tree(*nodes))[-1] == "placeholder line 8"


def test_too_few_lines_means_no_lyrics():
    assert pick_lines(tree(*placeholder_lines(MIN_LINES - 1), sidebar=2)) is None


def test_ignores_long_texts_and_wrappers_with_several_children():
    long_text = Node("other", children=[Node("text", "x" * 500)])
    busy = Node("other", children=[Node("text", "a"), Node("text", "b")])
    result = pick_lines(tree(long_text, busy, *placeholder_lines(MIN_LINES)))
    assert result == [f"placeholder line {i}" for i in range(MIN_LINES)]


def test_bare_text_children_count_as_lines():
    root = Node("other", children=[Node("text", f"bare line {i}") for i in range(MIN_LINES)])
    assert len(pick_lines(root)) == MIN_LINES


def test_side_panel_is_skipped():
    panel = Node("other", name="Now playing view", children=[
        Node("other", children=placeholder_lines(20, "panel line"))])
    root = Node("other", children=[panel, Node("other", children=placeholder_lines(MIN_LINES))])
    assert pick_lines(root)[0] == "placeholder line 0"
    assert pick_lines(Node("other", children=[panel])) is None


def test_credits_lists_are_rejected():
    credits = []
    for i in range(4):
        credits += [line(f"Person {i}"), line("Composer"), line("\u2022"), line("Lyricist")]
    assert pick_lines(Node("other", children=[Node("other", children=credits)])) is None


def test_same_lyrics_tolerates_one_line_shift():
    from lyrico.spotify_view import same_lyrics
    old = [f"old line {i}" for i in range(12)]
    assert same_lyrics(old[:-1], old)
    assert not same_lyrics([f"new line {i}" for i in range(12)], old)
    assert not same_lyrics(old, None)


def test_same_view():
    from lyrico.spotify_view import same_view
    old = [f"old line {i}" for i in range(12)]
    assert same_view(None, None)
    assert same_view(old[:-1], old)
    assert not same_view(None, old)
    assert not same_view(old, None)


def fake_view(reads):
    from lyrico import spotify_view
    view = object.__new__(spotify_view.SpotifyView)  # no UI Automation needed
    view.read = lambda open_view=True: next(reads)
    return view


def test_wait_for_change_skips_the_old_songs_lines(monkeypatch):
    from lyrico import spotify_view
    old = [f"old line {i}" for i in range(12)]
    new = [f"new line {i}" for i in range(10)]
    monkeypatch.setattr(spotify_view.time, "sleep", lambda s: None)
    view = fake_view(iter([old, old[:-1], new]))
    assert view.wait_for_change(old) == (new, True)


def test_wait_for_change_waits_through_an_empty_view(monkeypatch):
    from lyrico import spotify_view
    old = [f"old line {i}" for i in range(12)]
    new = [f"new line {i}" for i in range(10)]
    monkeypatch.setattr(spotify_view.time, "sleep", lambda s: None)
    assert fake_view(iter([old, None, None, new])).wait_for_change(old) == (new, True)


def test_wait_for_change_ends_empty_when_spotify_has_none(monkeypatch):
    from lyrico import spotify_view
    old = [f"old line {i}" for i in range(12)]
    clock = iter(range(0, 100))
    monkeypatch.setattr(spotify_view.time, "sleep", lambda s: None)
    monkeypatch.setattr(spotify_view.time, "time", lambda: next(clock))
    reads = iter([old, None, None, None, None, None, None, None, None, None])
    assert fake_view(reads).wait_for_change(old, wait=5) == (None, True)


def test_wait_for_change_gives_up_when_nothing_changes(monkeypatch):
    from lyrico import spotify_view
    old = [f"old line {i}" for i in range(12)]
    clock = iter(range(0, 100))
    monkeypatch.setattr(spotify_view.time, "sleep", lambda s: None)
    monkeypatch.setattr(spotify_view.time, "time", lambda: next(clock))
    view = object.__new__(spotify_view.SpotifyView)
    view.read = lambda open_view=True: old
    assert view.wait_for_change(old, wait=5) == (old, False)
