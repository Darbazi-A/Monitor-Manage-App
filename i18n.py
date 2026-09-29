"""
The interface's language: English, or Georgian.

Every piece of interface text goes through tr(). The language is chosen once,
at start-up (Screens & Setup → Language), before any window is built; the
Georgian words live in i18n_ka.py, keyed by the English text. Anything not
translated simply stays English. Leading and trailing spaces - the gap
between an icon and its label - are kept as they are.

What the operator types - step names, file names, presets, names on screen -
is never translated.
"""
from __future__ import annotations

LANGUAGES = (("en", "English"), ("ka", "ქართული"))
_language = "en"
_table: dict = {}


def set_language(code: str) -> None:
    global _language, _table
    _language = code if code in dict(LANGUAGES) else "en"
    if _language == "ka":
        from i18n_ka import KA
        _table = KA
    else:
        _table = {}


def language() -> str:
    return _language


def tr(text: str) -> str:
    if not _table or not text:
        return text
    core = text.strip()
    if not core:
        return text
    translated = _table.get(core)
    if translated is None:
        return text
    start = text.index(core[0])
    return text[:start] + translated + text[start + len(core):]


def caps(text: str) -> str:
    """Capitals for a caption - in English only: Georgian's Mtavruli reads as shouting and runs wide."""
    return text.upper() if text.isascii() else text


class Labels(dict):
    """A dict of interface words - the stage's screen names - that answers in the chosen language."""

    def __getitem__(self, key):
        return tr(super().__getitem__(key))

    def get(self, key, default=None):
        return tr(super().get(key, default)) if key in self else default
