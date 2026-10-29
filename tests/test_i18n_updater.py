import hashlib
import os
import re

import pytest
from babel.messages.pofile import read_po

from lyrico import app, i18n, updater
from lyrico.sources import SourceError

UK_PO = os.path.join(i18n.LOCALE_DIR, "uk", "LC_MESSAGES", "lyrico.po")


def uk_catalog():
    with open(UK_PO, "rb") as f:
        return read_po(f, locale="uk")


@pytest.fixture(autouse=True)
def english_after():
    yield
    i18n.set_language("en")


def test_english_is_identity():
    i18n.set_language("en")
    assert i18n._("Find") == "Find"


def test_ukrainian_lookup_and_fallback():
    i18n.set_language("uk")
    assert i18n._("Find") == uk_catalog().get("Find").string
    assert i18n._("Find") != "Find"
    assert i18n._("not translated") == "not translated"


def test_unknown_language_falls_back_to_english():
    assert i18n.set_language("xx") == "en"


def test_every_string_is_translated_and_keeps_placeholders():
    for message in uk_catalog():
        if not message.id:
            continue
        ids = message.id if isinstance(message.id, tuple) else (message.id,)
        strings = message.string if isinstance(message.string, tuple) else (message.string,)
        assert all(strings), f"untranslated: {ids[0]}"
        wanted = set(re.findall(r"\{\w+\}", ids[0]))
        for text in strings:
            assert set(re.findall(r"\{\w+\}", text)) == wanted, ids[0]
            assert ids[0].count("\t") == text.count("\t"), ids[0]


def test_ukrainian_plurals():
    i18n.set_language("uk")
    words = {n: i18n.results_count(n).split()[1].rstrip(".") for n in (1, 2, 5, 11, 12, 21, 22, 25, 111)}
    assert words[1] == words[21] == "результат"
    assert words[2] == words[22] == "результати"
    assert words[5] == words[11] == words[12] == words[25] == words[111] == "результатів"


def test_english_plurals():
    assert i18n.results_count(1) == "1 result."
    assert i18n.results_count(3) == "3 results."


def test_error_messages_translate():
    error = SourceError("{host} is busy right now (error {code}). Try again in a moment.",
                        host="lrclib.net", code=503)
    assert "lrclib.net" in str(error)
    i18n.set_language("uk")
    message = app.translate_error(error)
    assert "lrclib.net" in message and "503" in message
    assert message != str(error)


def test_parse_version():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("0.10.0") > updater.parse_version("0.9.9")
    assert updater.parse_version("latest") is None


def release_json(**asset_overrides):
    exe = {"name": "Lyrico.exe", "browser_download_url": "https://x/Lyrico.exe",
           "digest": "sha256:ABC123"}
    exe.update(asset_overrides)
    return {"tag_name": "v0.2.0", "assets": [
        exe, {"name": "Lyrico.exe.sha256", "browser_download_url": "https://x/Lyrico.exe.sha256"}]}


def test_parse_release():
    release = updater.parse_release(release_json())
    assert release.version == (0, 2, 0)
    assert release.exe_url == "https://x/Lyrico.exe"
    assert release.sha256 == "abc123"
    assert release.sha256_url.endswith(".sha256")


def test_newer_release_only_when_newer(monkeypatch):
    monkeypatch.setattr(updater, "fetch_latest", lambda: updater.parse_release(release_json()))
    assert updater.newer_release("0.1.0").tag == "v0.2.0"
    assert updater.newer_release("0.2.0") is None
    assert updater.newer_release("1.0.0") is None


class FakeResponse:
    def __init__(self, data):
        self.data = data
        self.headers = {"Content-Length": str(len(data))}

    def read(self, size=-1):
        if size < 0:
            size = len(self.data)
        chunk, self.data = self.data[:size], self.data[size:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_download_verifies_checksum(tmp_path, monkeypatch):
    payload = b"new exe bytes" * 1000
    good = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(updater, "_open", lambda url, accept=None: FakeResponse(payload))
    dest = str(tmp_path / "Lyrico.new.exe")

    release = updater.parse_release(release_json(digest="sha256:" + good))
    updater.download(release, dest)
    assert open(dest, "rb").read() == payload

    os.remove(dest)
    bad = updater.parse_release(release_json(digest="sha256:" + "0" * 64))
    with pytest.raises(updater.UpdateError):
        updater.download(bad, dest)
    assert not os.path.exists(dest)
    assert not os.path.exists(dest + ".part")


def test_checksum_from_sha256_file(monkeypatch):
    release = updater.parse_release(release_json(digest=None))
    assert release.sha256 == ""
    monkeypatch.setattr(updater, "_open", lambda url, accept=None: FakeResponse(b"DEADBEEF  Lyrico.exe\n"))
    assert updater.expected_checksum(release) == "deadbeef"


def test_no_checksum_refuses():
    release = updater.parse_release({"tag_name": "v0.2.0", "assets": [
        {"name": "Lyrico.exe", "browser_download_url": "https://x/Lyrico.exe"}]})
    with pytest.raises(updater.UpdateError):
        updater.expected_checksum(release)


def test_swap(tmp_path):
    exe = tmp_path / "Lyrico.exe"
    new = tmp_path / "Lyrico.new.exe"
    exe.write_bytes(b"old")
    new.write_bytes(b"new")
    old = updater.swap(str(exe), str(new))
    assert exe.read_bytes() == b"new"
    assert open(old, "rb").read() == b"old"
    assert not new.exists()
