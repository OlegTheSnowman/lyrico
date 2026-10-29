# Lyrico

Lyrico is a small Windows app for finding song lyrics fast, made for singing along. Type a song or an artist, press Enter, and read the lyrics in a plain text field. It uses native Windows controls, works fully from the keyboard, and talks to screen readers such as NVDA. The interface is in English and Ukrainian.

Lyrics come from [LRCLIB](https://lrclib.net). If LRCLIB has nothing and you typed "artist - title", Lyrico also tries [lyrics.ovh](https://lyrics.ovh). Neither needs an account or an API key. With Spotify sync on, Lyrico can also read the lyrics the Spotify app is showing.

## Getting started

Download Lyrico.exe from the latest release and run it. Nothing needs installing. Settings go to `%APPDATA%\Lyrico`.

## Searching

The Search by box next to the search field picks what to look for.

- Songs: type a song, an artist, or both, and press Enter. The search field is cleared, focus moves to the results, and the top match's lyrics are shown.
- Artists: type an artist and press Enter for a list of matching artists. Press Enter on one to list their songs. Only songs that have lyrics are listed. They are checked one at a time and appear as they are found, so a big artist takes a few minutes. Artists and their songs come from the [iTunes Search API](https://performance-partners.apple.com/search-api).

## Keys

In the window:

- Alt+S, Alt+B, Alt+R, Alt+L: search field, Search by box, results, lyrics.
- Escape: back to the search field.
- Enter in the results: on a song, go to its lyrics at the first line. On an artist, list their songs.
- Backspace in an artist's songs: back to the artist list.
- Ctrl+C in the results: copy "Artist - Title", or the artist's name.
- Ctrl+Plus and Ctrl+Minus: bigger or smaller lyrics text. The size is remembered.

For the music that is playing:

- Ctrl+P: lyrics for the song playing now, in Spotify, a browser, or any player that shows up in the Windows media controls.
- Alt+Right, Alt+Left: next and previous song.
- Alt+Down: play or pause.
- Ctrl+Shift+P: Spotify sync on or off.
- Ctrl+S: find the selected song or artist in Spotify.

The player keys go to Spotify when it is open, and otherwise to whatever player Windows lists as current.

## Spotify

The Spotify group at the bottom of the window comes right after the lyrics when you press Tab.

The Spotify sync checkbox makes Lyrico follow Spotify. Whenever Spotify moves to another song, Lyrico says the song's name and loads its lyrics. If you are in the results or the lyrics, focus moves to the first line of the new lyrics. If you are typing in the search field, focus stays where it is. Sync is off until you turn it on, and Lyrico remembers your choice.

With sync on, Lyrico first reads the lyrics from Spotify's own lyrics view, the same way a screen reader reads a window. If that view is closed, Lyrico opens it. If Spotify has no lyrics for the song, Lyrico uses LRCLIB. When Spotify's lyrics arrive late, Lyrico shows LRCLIB's first and swaps to Spotify's when they appear. The results list says "lyrics from Spotify" when they came from Spotify.

Spotify only fills in its lyrics view quickly while its window is visible. With Spotify in front, lyrics usually appear in well under a second. With it hidden behind other windows, they can take many seconds.

The Find in Spotify button opens Spotify searching for the selected song or artist, maximized and in front. Without the Spotify app installed, the Spotify web player opens instead.

## Lyrics and copyright

Song lyrics belong to their writers and publishers. Lyrico doesn't host or ship any lyrics. It looks them up on public lyrics services, the same as opening a lyrics website.

Lyrico never saves lyrics. They are only shown while you read them. From Spotify, Lyrico reads only what the app already shows on screen. It never contacts Spotify's servers or looks into the app's data.

## Languages and updates

The language is under Options, Language. On the first start Lyrico follows the Windows display language.

When it starts, Lyrico checks GitHub for a newer release and asks before installing it. Help, Check for updates does the same on demand. A download is checked against its published checksum before it replaces anything.

If something goes wrong, `%APPDATA%\Lyrico\lyrico.log` records what Lyrico did: lookups, sync and errors. It never contains lyrics.

## For developers

Running from source needs Python 3.10 or newer:

```
pip install -r requirements.txt -r requirements-dev.txt
python scripts/translations.py compile
python -m lyrico
```

Run the tests with `python -m pytest`.

Translations are standard gettext catalogs in `lyrico/locale/<language>/LC_MESSAGES/lyrico.po`, and any .po editor such as Poedit can open them.

- `python scripts/translations.py update` collects new strings from the code into every catalog.
- `python scripts/translations.py add de` starts a new language. Add it to `LANGUAGES` in `lyrico/i18n.py` too.
- `python scripts/translations.py compile` builds the .mo files. The tests and the build do this for you.

Releases are built on your own computer, so they use no GitHub Actions minutes.

- `build.bat` runs the tests and builds `dist/Lyrico.exe` with its checksum.
- `python scripts/release.py 0.2.0` sets the version, commits, tags `v0.2.0` and builds. Nothing is pushed yet, so you can try the exe first.
- `git push --follow-tags` publishes it. The pre-push hook runs the tests and checks that the exe was built from the tag. Once the push lands, it uploads Lyrico.exe and its checksum as a GitHub release with gh. Its log is in `.git/lyrico-release.log`.

The hook lives in `.githooks`. After cloning, turn it on once with `git config core.hooksPath .githooks`.
