"""Lyrico main window."""

import json
import os
import sys
import threading
import time

import wx

from . import __version__, i18n, media, sources, speech, updater
from .i18n import _, ngettext
from .spotify_view import same_lyrics, same_view
from .log import log, setup as setup_log

APP_NAME = "Lyrico"
DEFAULT_FONT_SIZE = 14
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 48
# Pause between per-song lyrics checks when browsing an artist, to be gentle with LRCLIB.
CHECK_PAUSE = 0.25
# How often Spotify sync looks at what is playing, in seconds. One look at the
# Windows media controls takes a few milliseconds, so this can be short.
SYNC_INTERVAL = 0.3
# Source name for lyrics read from Spotify's own lyrics view.
SPOTIFY_SOURCE = "Spotify"
# After Alt+Right or Alt+Left, wait this long for the player to switch before saying the song.
SKIP_ANNOUNCE_DELAY = 1.2
LATE_LYRICS_SECONDS = 20
LATE_CHECK_EVERY = 1.0

MODES = ("songs", "artists")


def data_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def settings_path():
    return os.path.join(data_dir(), "settings.json")


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    path = settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


def translate_error(error):
    """Translate an error built from an English template (sources, updater, media)."""
    template = getattr(error, "template", None)
    if template is None:
        return str(error)
    return _(template).format(**error.values)


class SyncState:
    def __init__(self):
        self.shown_song = None
        self.lines = None  # last lines read from Spotify, and their song
        self.lines_song = None
        self.pending_key = None  # song still watched for late Spotify lyrics
        self.pending_view = None
        self.pending_until = 0
        self.pending_checked = 0
        self.pending_seen = None
        self.changed_at = 0


def song_key(playing):
    """Compare songs reported by the media controls loosely (case and spaces)."""
    artist, title = playing
    return (artist or "").casefold().strip(), (title or "").casefold().strip()


def mode_names():
    return [_("Songs"), _("Artists")]


class MainFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title=APP_NAME, size=(1000, 720))
        self.settings = load_settings()
        setup_log(data_dir())
        log.info("Lyrico %s started", __version__)
        i18n.set_language(self.settings.get("language") or i18n.system_language())
        self.items = []  # Track or Artist objects shown in the results list
        self.view = "songs"  # songs, artists or artist_songs
        self.artist_items = []  # the artist list, kept for Backspace
        self.artist_index = 0
        self.search_id = 0
        self.updating = False
        self.shown_track = None
        self.sync_on = False
        self.sync_stop = None  # threading.Event that ends the Spotify sync thread
        self.sync_search_id = None

        panel = self.panel = wx.Panel(self)

        self.search_label = wx.StaticText(panel)
        self.search_box = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.mode_label = wx.StaticText(panel)
        self.mode = wx.Choice(panel, choices=mode_names())
        self.mode.SetSelection(0)
        self.search_button = wx.Button(panel)

        self.results_label = wx.StaticText(panel)
        # WANTS_CHARS: without it the panel's keyboard navigation swallows Enter
        # before the list sees it. Tab is then passed on by hand, see on_results_key.
        self.results = wx.ListBox(panel, style=wx.LB_SINGLE | wx.WANTS_CHARS)

        self.lyrics_label = wx.StaticText(panel)
        self.lyrics = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_NOHIDESEL
        )

        # Spotify controls come last in the tab order: after the lyrics, then Tab wraps to the search.
        self.spotify_group = wx.StaticBoxSizer(wx.HORIZONTAL, panel)
        group_box = self.spotify_group.GetStaticBox()
        self.sync_box = wx.CheckBox(group_box)
        self.spotify_button = wx.Button(group_box)

        self.status = self.CreateStatusBar()

        base_font = panel.GetFont()
        base_font.SetPointSize(base_font.GetPointSize() + 2)
        for control in (self.search_label, self.search_box, self.mode_label, self.mode,
                        self.search_button, self.results_label, self.results, self.lyrics_label,
                        group_box, self.sync_box, self.spotify_button):
            control.SetFont(base_font)
        self.apply_font_size(self.settings.get("font_size", DEFAULT_FONT_SIZE), save=False)

        top = wx.BoxSizer(wx.HORIZONTAL)
        top.Add(self.search_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        top.Add(self.search_box, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        top.Add(self.mode_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        top.Add(self.mode, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        top.Add(self.search_button, 0, wx.ALIGN_CENTER_VERTICAL)

        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(self.results_label, 0, wx.BOTTOM, 4)
        left.Add(self.results, 1, wx.EXPAND)

        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(self.lyrics_label, 0, wx.BOTTOM, 4)
        right.Add(self.lyrics, 1, wx.EXPAND)

        body = wx.BoxSizer(wx.HORIZONTAL)
        body.Add(left, 1, wx.EXPAND | wx.RIGHT, 12)
        body.Add(right, 2, wx.EXPAND)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(top, 0, wx.EXPAND | wx.ALL, 12)
        outer.Add(body, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.spotify_group.Add(self.sync_box, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 8)
        self.spotify_group.Add(self.spotify_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 8)
        outer.Add(self.spotify_group, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        panel.SetSizer(outer)

        self.search_box.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self.search_button.Bind(wx.EVT_BUTTON, self.on_search)
        self.results.Bind(wx.EVT_LISTBOX, self.on_select)
        self.results.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.activate_item())
        self.results.Bind(wx.EVT_KEY_DOWN, self.on_results_key)
        self.sync_box.Bind(wx.EVT_CHECKBOX, lambda e: self.set_sync(self.sync_box.GetValue()))
        self.spotify_button.Bind(wx.EVT_BUTTON, lambda e: self.find_in_spotify())

        self.ids = ids = {name: wx.NewIdRef() for name in
                          ("search", "mode", "results", "lyrics", "back", "bigger", "smaller",
                           "playing", "spotify", "sync", "next", "previous", "play_pause",
                           "updates", "about")}
        self.language_ids = {code: wx.NewIdRef() for code in i18n.LANGUAGES}
        handlers = {
            "search": self.focus_search,
            "mode": self.mode.SetFocus,
            "results": self.results.SetFocus,
            "lyrics": self.focus_lyrics,
            "back": self.focus_search,
            "bigger": lambda: self.change_font(2),
            "smaller": lambda: self.change_font(-2),
            "playing": self.lyrics_for_now_playing,
            "spotify": self.find_in_spotify,
            "sync": self.toggle_sync,
            "next": lambda: self.control_player("next"),
            "previous": lambda: self.control_player("previous"),
            "play_pause": lambda: self.control_player("play_pause"),
            "updates": lambda: self.check_updates(silent=False),
            "about": self.on_about,
        }
        for name, handler in handlers.items():
            self.Bind(wx.EVT_MENU, lambda e, h=handler: h(), id=ids[name])
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), id=wx.ID_EXIT)
        for code, lang_id in self.language_ids.items():
            self.Bind(wx.EVT_MENU, lambda e, c=code: self.set_language(c), id=lang_id)
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_ALT, ord("S"), ids["search"]),
            (wx.ACCEL_ALT, ord("B"), ids["mode"]),
            (wx.ACCEL_ALT, ord("R"), ids["results"]),
            (wx.ACCEL_ALT, ord("L"), ids["lyrics"]),
            (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, ids["back"]),
            (wx.ACCEL_CTRL, ord("="), ids["bigger"]),
            (wx.ACCEL_CTRL, wx.WXK_NUMPAD_ADD, ids["bigger"]),
            (wx.ACCEL_CTRL, ord("-"), ids["smaller"]),
            (wx.ACCEL_CTRL, wx.WXK_NUMPAD_SUBTRACT, ids["smaller"]),
            (wx.ACCEL_CTRL, ord("P"), ids["playing"]),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("P"), ids["sync"]),
            (wx.ACCEL_ALT, wx.WXK_RIGHT, ids["next"]),
            (wx.ACCEL_ALT, wx.WXK_LEFT, ids["previous"]),
            (wx.ACCEL_ALT, wx.WXK_DOWN, ids["play_pause"]),
            (wx.ACCEL_CTRL, ord("S"), ids["spotify"]),
        ]))

        self.relabel()
        self.status.SetStatusText(_("Type a song and press Enter."))
        self.SetMinSize(wx.Size(700, 400))
        self.Centre()
        self.search_box.SetFocus()
        self.Bind(wx.EVT_CLOSE, self.on_close)

        if self.settings.get("spotify_sync"):
            self.set_sync(True)

        if updater.is_frozen():
            updater.cleanup_old()
            wx.CallLater(1500, self.check_updates, True)

    # Menus and language

    def make_menu_bar(self):
        ids = self.ids
        file_menu = wx.Menu()
        file_menu.Append(wx.ID_EXIT, _("E&xit"))

        view_menu = wx.Menu()
        view_menu.Append(ids["bigger"], _("&Bigger text\tCtrl+="))
        view_menu.Append(ids["smaller"], _("&Smaller text\tCtrl+-"))

        music_menu = wx.Menu()
        music_menu.Append(ids["playing"], _("Lyrics for what's &playing\tCtrl+P"))
        music_menu.AppendSeparator()
        music_menu.Append(ids["previous"], _("P&revious song\tAlt+Left"))
        music_menu.Append(ids["next"], _("&Next song\tAlt+Right"))
        music_menu.Append(ids["play_pause"], _("Play or p&ause\tAlt+Down"))

        language_menu = wx.Menu()
        for code, name in i18n.LANGUAGES.items():
            item = language_menu.AppendRadioItem(self.language_ids[code], name)
            item.Check(code == i18n.current_language())
        options_menu = wx.Menu()
        options_menu.AppendSubMenu(language_menu, _("&Language"))

        help_menu = wx.Menu()
        help_menu.Append(ids["updates"], _("&Check for updates"))
        help_menu.Append(ids["about"], _("&About Lyrico"))

        bar = wx.MenuBar()
        bar.Append(file_menu, _("&File"))
        bar.Append(view_menu, _("&View"))
        bar.Append(music_menu, _("&Music"))
        bar.Append(options_menu, _("&Options"))
        bar.Append(help_menu, _("&Help"))
        return bar

    def relabel(self):
        self.search_label.SetLabel(_("&Search:"))
        self.search_box.SetHint(_("Song, artist or both"))
        self.mode_label.SetLabel(_("Search &by:"))
        selection = self.mode.GetSelection()
        self.mode.Set(mode_names())
        self.mode.SetSelection(max(selection, 0))
        self.search_button.SetLabel(_("Find"))
        self.results_label.SetLabel(_("&Results:"))
        self.lyrics_label.SetLabel(_("&Lyrics:"))
        self.spotify_group.GetStaticBox().SetLabel(_("Spotify"))
        self.sync_box.SetLabel(_("Spotify sync (Ctrl+Shift+P)"))
        self.spotify_button.SetLabel(_("Find in Spotify (Ctrl+S)"))
        old_bar = self.GetMenuBar()
        self.SetMenuBar(self.make_menu_bar())
        if old_bar:
            old_bar.Destroy()
        self.panel.Layout()

    def set_language(self, code):
        if code == i18n.current_language():
            return
        i18n.set_language(code)
        self.settings["language"] = code
        save_settings(self.settings)
        self.relabel()
        self.status.SetStatusText(_("Language changed to {name}.").format(name=i18n.LANGUAGES[code]))

    # Focus and text

    def focus_search(self):
        self.search_box.SetFocus()
        self.search_box.SelectAll()

    def focus_lyrics(self):
        self.lyrics.SetFocus()
        self.lyrics.SetInsertionPoint(0)

    def apply_font_size(self, size, save=True):
        size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(size)))
        font = wx.Font(size, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL,
                       wx.FONTWEIGHT_NORMAL, faceName="Segoe UI")
        self.lyrics.SetFont(font)
        # A rich edit keeps the old font on existing text, so reapply it.
        attr = wx.TextAttr()
        attr.SetFont(font)
        self.lyrics.SetStyle(0, self.lyrics.GetLastPosition(), attr)
        self.lyrics.SetDefaultStyle(attr)
        self.settings["font_size"] = size
        if save:
            save_settings(self.settings)
        return size

    def change_font(self, delta):
        size = self.apply_font_size(self.settings.get("font_size", DEFAULT_FONT_SIZE) + delta)
        self.status.SetStatusText(_("Lyrics text size {size}.").format(size=size))

    def show_text(self, text):
        self.lyrics.SetValue(text)
        self.lyrics.SetInsertionPoint(0)
        self.lyrics.ShowPosition(0)

    def show_message(self, message, focus_search=True):
        """Show a message in both the lyrics field and the status bar."""
        self.shown_track = None
        self.show_text(message)
        self.status.SetStatusText(message)
        if focus_search:
            self.focus_search()

    # Searching

    def current_mode(self):
        return MODES[max(self.mode.GetSelection(), 0)]

    def set_mode(self, mode):
        self.mode.SetSelection(MODES.index(mode))

    def new_search(self):
        """Start a new search; any search still running is ignored from now on."""
        self.search_id += 1
        self.shown_track = None
        self.items = []
        self.results.Clear()
        self.SetTitle(APP_NAME)
        return self.search_id

    def on_search(self, event=None):
        mode = self.current_mode()
        query = self.search_box.GetValue().strip()
        if not query:
            self.focus_search()
            return
        if mode == "artists":
            self.start_artist_search(query)
        else:
            self.start_song_search(query)

    def start_song_search(self, query):
        search_id = self.new_search()
        self.show_text(_("Searching..."))
        self.status.SetStatusText(_("Searching for {query}...").format(query=query))
        threading.Thread(target=self.run_song_search, args=(search_id, query), daemon=True).start()
        return search_id

    def run_song_search(self, search_id, query):
        try:
            tracks, error = sources.search(query), None
        except sources.SourceError as e:
            tracks, error = [], e
        wx.CallAfter(self.on_song_results, search_id, query, tracks, error)

    def on_song_results(self, search_id, query, tracks, error):
        if search_id != self.search_id or not self:
            return
        from_sync = search_id == self.sync_search_id
        if not tracks:
            if error:
                message = translate_error(error)
            else:
                message = _("No lyrics found for {query}.").format(query=query)
            self.show_message(message, focus_search=not from_sync)
            if from_sync:
                self.announce(message, interrupt=False)
            return
        self.set_items(tracks, "songs")
        self.status.SetStatusText(i18n.results_count(len(tracks)))
        if from_sync:
            self.announce(_("Lyrics from LRCLIB."), interrupt=False)
            self.sync_focus()
            return
        self.search_box.Clear()
        self.results.SetFocus()

    def start_artist_search(self, query):
        search_id = self.new_search()
        self.show_text(_("Searching..."))
        self.status.SetStatusText(_("Searching for {query}...").format(query=query))
        threading.Thread(target=self.run_artist_search, args=(search_id, query), daemon=True).start()

    def run_artist_search(self, search_id, query):
        try:
            artists, error = sources.search_artists(query), None
        except sources.SourceError as e:
            artists, error = [], e
        wx.CallAfter(self.on_artist_results, search_id, query, artists, error)

    def on_artist_results(self, search_id, query, artists, error):
        if search_id != self.search_id or not self:
            return
        if error:
            self.show_message(translate_error(error))
            return
        if not artists:
            self.show_message(_("No artists found for {query}.").format(query=query))
            return
        self.artist_items = artists
        self.artist_index = 0
        self.set_items(artists, "artists")
        self.status.SetStatusText(
            ngettext("{count} artist.", "{count} artists.", len(artists)).format(count=len(artists)))
        self.search_box.Clear()
        self.results.SetFocus()

    # An artist's songs, checked one by one so only songs with lyrics are listed

    def open_artist(self, artist):
        self.artist_index = max(self.results.GetSelection(), 0)
        search_id = self.new_search()
        self.view = "artist_songs"
        message = _("Looking for songs with lyrics by {artist}...").format(artist=artist.name)
        self.show_text(message)
        self.status.SetStatusText(message)
        self.results.SetFocus()
        threading.Thread(target=self.run_artist_songs, args=(search_id, artist), daemon=True).start()

    def run_artist_songs(self, search_id, artist):
        try:
            songs = sources.artist_songs(artist.artist_id)
        except sources.SourceError as e:
            wx.CallAfter(self.on_artist_songs_failed, search_id, e)
            return
        unchecked = 0
        for number, song in enumerate(songs, 1):
            if search_id != self.search_id:
                return
            try:
                track = sources.find_lyrics(song.artist, song.title)
            except sources.SourceError:
                track = None
                unchecked += 1
            time.sleep(CHECK_PAUSE)
            if track:
                wx.CallAfter(self.add_artist_song, search_id, track)
            wx.CallAfter(self.on_artist_progress, search_id, artist, number, len(songs))
        wx.CallAfter(self.on_artist_songs_done, search_id, artist, unchecked)

    def add_artist_song(self, search_id, track):
        if search_id != self.search_id or not self:
            return
        if any(t.artist.casefold() == track.artist.casefold() and t.title.casefold() == track.title.casefold()
               for t in self.items):
            return
        self.items.append(track)
        self.results.Append(track.label())
        if len(self.items) == 1:
            self.results.SetSelection(0)
            self.show_item(0)

    def on_artist_progress(self, search_id, artist, checked, total):
        if search_id != self.search_id or not self:
            return
        self.status.SetStatusText(
            _("{artist}: {found} songs with lyrics, checked {checked} of {total}.").format(
                artist=artist.name, found=len(self.items), checked=checked, total=total))

    def on_artist_songs_done(self, search_id, artist, unchecked):
        if search_id != self.search_id or not self:
            return
        if not self.items:
            message = _("No songs with lyrics found for {artist}.").format(artist=artist.name)
        else:
            message = ngettext("{count} song with lyrics by {artist}.",
                               "{count} songs with lyrics by {artist}.",
                               len(self.items)).format(count=len(self.items), artist=artist.name)
        if unchecked:
            message += " " + ngettext(
                "{count} song could not be checked because LRCLIB is busy.",
                "{count} songs could not be checked because LRCLIB is busy.",
                unchecked).format(count=unchecked)
        if not self.items:
            self.show_message(message, focus_search=False)
        self.status.SetStatusText(message)

    def on_artist_songs_failed(self, search_id, error):
        if search_id == self.search_id and self:
            self.show_message(translate_error(error), focus_search=False)

    def back_to_artists(self):
        if self.view != "artist_songs" or not self.artist_items:
            return False
        self.new_search()
        self.set_items(self.artist_items, "artists", select=self.artist_index)
        self.status.SetStatusText(
            ngettext("{count} artist.", "{count} artists.", len(self.artist_items)).format(
                count=len(self.artist_items)))
        return True

    # The results list

    def set_items(self, items, view, select=0):
        self.items = list(items)
        self.view = view
        self.results.Set([self.item_label(item) for item in self.items])
        if self.items:
            select = min(select, len(self.items) - 1)
            self.results.SetSelection(select)
            self.show_item(select)

    def item_label(self, item):
        label = item.label()
        if getattr(item, "source", None) == SPOTIFY_SOURCE:
            label += " - " + _("lyrics from Spotify")
        return label

    def selected_item(self):
        index = self.results.GetSelection()
        return self.items[index] if 0 <= index < len(self.items) else None

    def show_item(self, index):
        if not 0 <= index < len(self.items):
            return
        item = self.items[index]
        if isinstance(item, sources.Artist):
            self.shown_track = None
            self.show_text(_("Press Enter to see songs by {artist}.").format(artist=item.name))
            self.SetTitle(f"{item.name} - {APP_NAME}")
            return
        if item.lyrics == sources.INSTRUMENTAL:
            self.show_text(_("Instrumental, no lyrics."))
        else:
            self.show_text(item.lyrics)
        self.SetTitle(f"{item.artist} - {item.title} - {APP_NAME}")
        self.shown_track = item

    def on_select(self, event):
        self.show_item(self.results.GetSelection())

    def activate_item(self):
        item = self.selected_item()
        if isinstance(item, sources.Artist):
            self.open_artist(item)
        elif item is not None:
            self.focus_lyrics()

    def copy_item(self):
        item = self.selected_item()
        if item is None:
            return
        text = item.name if isinstance(item, sources.Artist) else f"{item.artist} - {item.title}"
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(text))
            finally:
                wx.TheClipboard.Close()
            self.status.SetStatusText(_("Copied {text}.").format(text=text))

    def on_results_key(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_TAB and not event.ControlDown():
            flags = wx.NavigationKeyEvent.IsBackward if event.ShiftDown() else wx.NavigationKeyEvent.IsForward
            self.results.Navigate(flags)
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.activate_item()
        elif key == wx.WXK_BACK and not event.HasAnyModifiers():
            if not self.back_to_artists():
                event.Skip()
        elif key == ord("C") and event.GetModifiers() == wx.MOD_CONTROL:
            self.copy_item()
        else:
            event.Skip()

    # Music: what's playing and Spotify

    def lyrics_for_now_playing(self):
        self.status.SetStatusText(_("Checking what's playing..."))
        threading.Thread(target=self.run_now_playing, daemon=True).start()

    def run_now_playing(self):
        try:
            playing, error = media.now_playing(), None
        except media.MediaError as e:
            playing, error = None, e
        wx.CallAfter(self.on_now_playing, playing, error)

    def on_now_playing(self, playing, error):
        if not self:
            return
        if error:
            self.show_message(translate_error(error))
            return
        if not playing:
            self.show_message(_("Nothing is playing right now."))
            return
        artist, title = playing
        self.set_mode("songs")
        self.start_song_search(f"{artist} - {title}" if artist else title)

    def toggle_sync(self):
        """Ctrl+Shift+P. Says the new state, since focus does not move to the checkbox."""
        self.set_sync(not self.sync_on)
        self.announce(_("Spotify sync on.") if self.sync_on else _("Spotify sync off."))

    def set_sync(self, on):
        if on == self.sync_on:
            return
        self.sync_on = on
        self.settings["spotify_sync"] = on
        save_settings(self.settings)
        self.sync_box.SetValue(on)
        if on:
            self.sync_stop = threading.Event()
            threading.Thread(target=self.run_sync, args=(self.sync_stop,), daemon=True).start()
            self.status.SetStatusText(_("Spotify sync is on. Lyrics follow the song playing in Spotify."))
        else:
            if self.sync_stop:
                self.sync_stop.set()
            self.sync_search_id = None
            self.status.SetStatusText(_("Spotify sync is off."))

    def run_sync(self, stop):
        """Poll Spotify and report each new song to the window, until stop is set."""
        last = ()  # differs from None, so "nothing playing" is reported at the start too
        view = None
        try:
            from .spotify_view import SpotifyView
            view = SpotifyView()  # UI Automation, created on this thread
            log.info("sync: Spotify lyrics reader ready")
        except Exception:  # comtypes or UI Automation missing: LRCLIB only
            log.exception("sync: Spotify lyrics reader unavailable, using LRCLIB only")
            view = None
        state = SyncState()
        while not stop.is_set():
            try:
                playing = media.now_playing("spotify")
            except media.MediaError:
                playing = None
            if playing != last:
                last = playing
                self.sync_change(stop, view, playing, state)
            elif playing and view and state.pending_key == song_key(playing):
                self.check_late_lyrics(stop, view, playing, state)
            stop.wait(SYNC_INTERVAL)

    def check_late_lyrics(self, stop, view, playing, state):
        """Switch to Spotify's lyrics if they show up after Lyrico gave up waiting."""
        now = time.time()
        if now > state.pending_until:
            state.pending_key = None
            return
        if now - state.pending_checked < LATE_CHECK_EVERY:
            return
        state.pending_checked = now
        try:
            lines = view.read(open_view=False)
        except Exception:
            return
        seen = "empty" if not lines else "old" if same_view(lines, state.pending_view) else "new"
        if seen != state.pending_seen:
            state.pending_seen = seen
            log.info("sync: waiting for late lyrics, view is %s (%s lines) %.1fs after the change",
                     seen, len(lines) if lines else 0, now - state.changed_at)
        if lines and not same_view(lines, state.pending_view):
            state.pending_key = None
            state.lines, state.lines_song = lines, song_key(playing)
            log.info("sync: late lyrics from Spotify view for %s - %s, lines=%s, %.1fs after the change",
                     playing[0], playing[1], len(lines), now - state.changed_at)
            wx.CallAfter(self.on_sync_song, stop, playing, lines, True)

    def sync_change(self, stop, view, playing, state):
        """Handle one change reported by the media controls (on the sync thread)."""
        if not playing:  # often just a blip between songs: keep the lyrics shown
            log.info("sync: nothing playing")
            wx.CallAfter(self.on_sync_song, stop, None, None)
            return
        key = song_key(playing)
        if key == state.shown_song:
            log.info("sync: same song again after a blip, keeping its lyrics: %s - %s", *playing)
            return
        first = state.shown_song is None
        state.shown_song = key
        state.pending_key = None
        wx.CallAfter(self.announce_playing, stop, playing)
        lines = None
        reason = "no Spotify reader"
        started = time.time()
        if view:
            try:
                # Whatever the view shows right now still belongs to the song before.
                snapshot = view.read()
                if snapshot and first:
                    lines, reason = snapshot, "first song since sync started"
                elif snapshot and state.lines_song == key and same_lyrics(snapshot, state.lines):
                    lines, reason = snapshot, "this song's lyrics are still shown"
                else:
                    lines, changed = view.wait_for_change(snapshot)
                    if not (changed and lines):
                        reason = "no new lyrics in Spotify view yet"
                        state.pending_key, state.pending_view = key, lines if changed else snapshot
                        state.pending_until, state.pending_checked = time.time() + LATE_LYRICS_SECONDS, 0
                        state.pending_seen = None
                        lines = None
                    else:
                        reason = "read"
            except Exception:  # Spotify closed or changed mid-read
                log.exception("sync: reading Spotify's lyrics view failed")
                reason, lines = "read failed", None
            if lines:
                state.lines, state.lines_song = lines, key
        log.info("sync: now %s - %s, lines from Spotify view=%s (%s) after %.1fs",
                 playing[0], playing[1], len(lines) if lines else 0, reason, time.time() - started)
        state.changed_at = started
        wx.CallAfter(self.on_sync_song, stop, playing, lines)

    def on_sync_song(self, stop, playing, spotify_lines=None, late=False):
        if stop.is_set() or not self:
            return
        if not playing:
            self.status.SetStatusText(_("Spotify sync: waiting for Spotify to play a song."))
            return
        artist, title = playing
        if spotify_lines:
            track = sources.Track(artist, title, "", 0, "\n".join(spotify_lines), SPOTIFY_SOURCE)
            self.new_search()
            self.set_mode("songs")
            self.set_items([track], "songs")
            self.status.SetStatusText(_("Lyrics from Spotify: {song}.").format(song=track.label()))
            if late:
                self.announce(_("Spotify lyrics arrived."))
            else:
                self.announce(_("Lyrics from Spotify."), interrupt=False)
            self.sync_focus()
            return
        self.set_mode("songs")
        self.sync_search_id = self.start_song_search(f"{artist} - {title}" if artist else title)

    def announce(self, text, interrupt=True):
        if self and self.IsActive() and not self.IsIconized():
            speech.speak(text, interrupt=interrupt)

    def announce_playing(self, stop, playing):
        """Say the new song as soon as Spotify changes it, before its lyrics load."""
        if stop.is_set() or not self or not playing:
            return
        artist, title = playing
        self.announce(_("Now playing: {song}.").format(song=f"{artist} - {title}" if artist else title))

    def sync_focus(self):
        """After sync loads a song, move to its lyrics so NVDA reads them, unless
        the user is busy in the search field or the Search by box."""
        focus = wx.Window.FindFocus()
        if focus in (self.search_box, self.mode, self.search_button):
            return
        self.focus_lyrics()

    def control_player(self, action):
        threading.Thread(target=self.run_control, args=(action,), daemon=True).start()

    def run_control(self, action):
        try:
            done, error = media.control(action), None
        except media.MediaError as e:
            done, error = False, e
        wx.CallAfter(self.on_control_done, done, error)
        # With sync on, the sync thread says the new song. Without it, say it here.
        if done and action in ("next", "previous") and not self.sync_on:
            time.sleep(SKIP_ANNOUNCE_DELAY)
            try:
                playing = media.now_playing("spotify") or media.now_playing()
            except media.MediaError:
                playing = None
            if playing:
                artist, title = playing
                song = f"{artist} - {title}" if artist else title
                wx.CallAfter(self.announce, _("Now playing: {song}.").format(song=song))

    def on_control_done(self, done, error):
        if not self:
            return
        if error:
            self.status.SetStatusText(translate_error(error))
        elif not done:
            self.status.SetStatusText(_("No player to control right now."))

    def find_in_spotify(self):
        item = self.selected_item()
        if isinstance(item, sources.Artist):
            query = item.name
        elif item is not None:
            query = f"{item.artist} {item.title}"
        else:
            query = self.search_box.GetValue().strip()
        if not query:
            self.status.SetStatusText(_("Find a song first, then open it in Spotify."))
            return
        self.status.SetStatusText(_("Opening Spotify search for {query}.").format(query=query))
        if media.open_spotify_search(query):
            threading.Thread(target=media.show_spotify, daemon=True).start()

    # About and updates

    def on_about(self):
        text = _("Lyrico {version}\n\nFind song lyrics fast.\n"
                 "Lyrics come from LRCLIB and lyrics.ovh, artists and their songs from iTunes.")
        wx.MessageBox(text.format(version=__version__), _("About Lyrico"), wx.OK | wx.ICON_INFORMATION, self)

    def check_updates(self, silent):
        if self.updating:
            return
        if not updater.is_frozen():
            if not silent:
                wx.MessageBox(_("Updates work only in Lyrico.exe, not when running from source."),
                              _("Update"), wx.OK | wx.ICON_INFORMATION, self)
            return
        if not silent:
            self.status.SetStatusText(_("Checking for updates..."))
        threading.Thread(target=self.run_check, args=(silent,), daemon=True).start()

    def run_check(self, silent):
        try:
            release, error = updater.newer_release(), None
        except updater.UpdateError as e:
            release, error = None, e
        wx.CallAfter(self.on_check_done, release, error, silent)

    def on_check_done(self, release, error, silent):
        if not self:
            return
        if error:
            if not silent:
                message = _("Update check failed: {error}").format(error=translate_error(error))
                self.status.SetStatusText("")
                wx.MessageBox(message, _("Update"), wx.OK | wx.ICON_ERROR, self)
            return
        if release is None:
            if not silent:
                self.status.SetStatusText("")
                wx.MessageBox(_("You have the latest version, {current}.").format(current=__version__),
                              _("No updates"), wx.OK | wx.ICON_INFORMATION, self)
            return
        new = release.tag.lstrip("vV")
        if silent and self.settings.get("skipped_version") == release.tag:
            self.status.SetStatusText(
                _("Lyrico {new} is available. Use Help, Check for updates to install it.").format(new=new))
            return
        question = _("Lyrico {new} is available. You have {current}.\n\n"
                     "Download and install it now? Lyrico will restart.").format(new=new, current=__version__)
        answer = wx.MessageBox(question, _("Update available"), wx.YES_NO | wx.ICON_QUESTION, self)
        if answer != wx.YES:
            self.settings["skipped_version"] = release.tag
            save_settings(self.settings)
            return
        self.updating = True
        self.status.SetStatusText(_("Downloading update..."))
        threading.Thread(target=self.run_download, args=(release,), daemon=True).start()

    def run_download(self, release):
        exe = sys.executable
        new_path = os.path.join(os.path.dirname(exe), "Lyrico.new.exe")
        try:
            updater.download(release, new_path)
            error = None
        except updater.UpdateError as e:
            error = e
        wx.CallAfter(self.on_downloaded, exe, new_path, error)

    def on_downloaded(self, exe, new_path, error):
        if not error:
            try:
                updater.swap(exe, new_path)
                updater.restart(exe)
                self.Close()
                return
            except (updater.UpdateError, OSError) as e:
                error = e
        self.updating = False
        message = _("Update failed: {error}").format(error=translate_error(error))
        self.status.SetStatusText(message)
        wx.MessageBox(message, _("Update"), wx.OK | wx.ICON_ERROR, self)

    def on_close(self, event):
        self.search_id += 1  # stops artist checks still running
        if self.sync_stop:
            self.sync_stop.set()
        event.Skip()


def main():
    app = wx.App()
    frame = MainFrame()
    frame.Show()
    app.MainLoop()
