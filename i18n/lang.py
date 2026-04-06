"""
i18n/lang.py - Internationalization helper.

Usage:
    from i18n.lang import tr, set_language, load_from_settings

    load_from_settings()          # call once at startup
    label = tr("pal.open_file")   # returns localized string
"""

from __future__ import annotations

from PyQt6.QtCore import QSettings

from i18n.strings_fr import STRINGS_FR
from i18n.strings_en import STRINGS_EN

_LANGS: dict[str, dict[str, str]] = {
    "fr": STRINGS_FR,
    "en": STRINGS_EN,
}

_current_lang: str = "fr"
_current_strings: dict[str, str] = STRINGS_FR


def set_language(lang: str) -> None:
    """Set the active language ('fr' or 'en'). Falls back to 'fr'."""
    global _current_lang, _current_strings
    _current_lang = lang if lang in _LANGS else "fr"
    _current_strings = _LANGS[_current_lang]


def current_language() -> str:
    """Return the current language code."""
    return _current_lang


def available_languages() -> list[str]:
    """Return list of available language codes."""
    return list(_LANGS.keys())


def load_from_settings() -> None:
    """Read language from QSettings and activate it."""
    settings = QSettings("NGPCraft", "Engine")
    lang = settings.value("language", "fr", type=str)
    set_language(lang)


def save_to_settings(lang: str) -> None:
    """Persist language choice to QSettings."""
    settings = QSettings("NGPCraft", "Engine")
    settings.setValue("language", lang)


def tr(key: str, **kwargs: object) -> str:
    """
    Return localized string for key, with optional str.format() substitutions.

    Falls back to English, then to the key itself if not found.
    """
    s = _current_strings.get(key) or STRINGS_EN.get(key) or key
    if kwargs:
        try:
            s = s.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return s
