"""Read the lyrics Spotify is showing in its own lyrics view, the way a screen
reader does, through Windows UI Automation.

This is an accessibility helper: it only reads what the Spotify app already
shows on screen. The text is displayed in Lyrico and never saved.

Spotify's class names are generated and change between versions, so nothing
here depends on them. The lyrics are found by shape instead: the element with
the most children that each hold one short line of text."""

import time
from dataclasses import dataclass, field

LYRICS_BUTTON_NAMES = ("Lyrics",)
# The side panel also holds short lists of lines, such as the song's credits;
# lyrics are never in it, so it is skipped.
SKIPPED_PANELS = ("Now playing view",)
# Credits put a lone bullet between roles; lyrics lines never consist of one.
CREDITS_MARK = "•"
MIN_LINES = 8
MAX_LINE_LENGTH = 150
CHANGE_WAIT = 1.0  # seconds to wait for a new song's lyrics before using LRCLIB
TOGGLE_ON = 1


@dataclass
class Node:
    """A plain copy of one UI Automation element, so the line-picking rule can be tested."""
    kind: str  # "text" or "other"
    name: str = ""
    style: str = ""
    children: list = field(default_factory=list)


def line_of(node):
    """The line a node shows, if it is a short text or wraps exactly one."""
    if node.kind == "text":
        text = node.name
    elif len(node.children) == 1 and node.children[0].kind == "text":
        text = node.children[0].name
    else:
        return None
    text = text.strip()
    return text if 0 < len(text) <= MAX_LINE_LENGTH else None


def pick_lines(root):
    """The lyrics lines in a tree: the node with the most line children.
    The side panel and lists with credits bullets are skipped, and a last line
    styled unlike the others (Spotify's credit line) is dropped."""
    best = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.kind != "text" and node.name in SKIPPED_PANELS:
            continue
        lines = [(child.style, text) for child in node.children if (text := line_of(child))]
        if len(lines) > len(best) and not any(text == CREDITS_MARK for _, text in lines):
            best = lines
        stack.extend(node.children)
    if len(best) > 1:
        styles = [style for style, _ in best]
        usual = max(set(styles), key=styles.count)
        if best[-1][0] != usual:
            best = best[:-1]
    texts = [text for _, text in best]
    return texts if len(texts) >= MIN_LINES else None


def same_lyrics(lines, other, threshold=0.6):
    """True when two line lists are mostly the same lines, so the same song."""
    if not lines or not other:
        return False
    a, b = set(lines), set(other)
    return len(a & b) / max(len(a), len(b)) >= threshold


def same_view(lines, other):
    """Same view content: both without lyrics, or mostly the same lines."""
    if not lines or not other:
        return not lines and not other
    return same_lyrics(lines, other)


class SpotifyView:
    """UI Automation access to the Spotify window. Create and use it on one thread."""

    def __init__(self):
        import comtypes
        import comtypes.client

        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except OSError:
            pass  # importing comtypes already set COM up on this thread; either mode works
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA

        self.UIA = UIA
        self.COMError = comtypes.COMError
        self.uia = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
        self.walker = self.uia.ControlViewWalker

    def _root(self):
        from .media import find_spotify_window

        hwnd = find_spotify_window()
        return self.uia.ElementFromHandle(hwnd) if hwnd else None

    def _lyrics_button(self, root):
        for name in LYRICS_BUTTON_NAMES:
            condition = self.uia.CreatePropertyCondition(self.UIA.UIA_NamePropertyId, name)
            button = root.FindFirst(self.UIA.TreeScope_Descendants, condition)
            if button:
                return button
        return None

    def _toggle(self, button):
        pattern = button.GetCurrentPattern(self.UIA.UIA_TogglePatternId)
        return pattern.QueryInterface(self.UIA.IUIAutomationTogglePattern) if pattern else None

    def _copy(self, element, depth=0):
        try:
            kind = "text" if element.CurrentControlType == self.UIA.UIA_TextControlTypeId else "other"
            node = Node(kind, element.CurrentName or "", element.CurrentClassName or "")
        except self.COMError:  # the element vanished while Spotify redraws
            return Node("other")
        if depth < 40:
            try:
                child = self.walker.GetFirstChildElement(element)
                while child:
                    node.children.append(self._copy(child, depth + 1))
                    child = self.walker.GetNextSiblingElement(child)
            except self.COMError:
                pass
        return node

    def read(self, open_view=True):
        """Lines Spotify shows in its lyrics view, or None. Opens the view
        when it is closed and open_view is set; never closes it."""
        try:
            return self._read(open_view)
        except self.COMError:
            time.sleep(0.1)
            try:
                return self._read(open_view)
            except self.COMError:
                return None

    def _read(self, open_view):
        root = self._root()
        if root is None:
            return None
        button = self._lyrics_button(root)
        if button is None:
            return None
        toggle = self._toggle(button)
        if toggle is None:
            return None
        if toggle.CurrentToggleState != TOGGLE_ON:
            if not open_view:
                return None
            toggle.Toggle()
            time.sleep(1.0)
            root = self._root()
            if root is None:
                return None
        return pick_lines(self._copy(root))

    def wait_for_change(self, before, wait=None):
        """Read until the view shows lyrics other than `before`, or `wait`
        seconds pass. An empty view, Spotify loading, is not an answer yet.
        Returns (lines, changed)."""
        deadline = time.time() + (CHANGE_WAIT if wait is None else wait)
        while True:
            lines = self.read()
            if lines and not same_lyrics(lines, before):
                return lines, True
            if time.time() > deadline:
                return lines, not same_view(lines, before)
            time.sleep(0.1)
