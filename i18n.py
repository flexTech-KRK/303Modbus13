"""Simple UI internationalization (Polish / English)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCALES_DIR = ROOT / "locales"
SETTINGS_PATH = ROOT / "settings.json"


class I18n:
    SUPPORTED = ("pl", "en")

    def __init__(self) -> None:
        self._catalog: dict[str, dict[str, str]] = {}
        self.lang = "pl"
        self._load_catalogs()
        self._load_settings()

    def _load_catalogs(self) -> None:
        for code in self.SUPPORTED:
            path = LOCALES_DIR / f"{code}.json"
            with path.open(encoding="utf-8") as f:
                self._catalog[code] = json.load(f)

    def _load_settings(self) -> None:
        if not SETTINGS_PATH.exists():
            return
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            lang = data.get("language", "pl")
            if lang in self.SUPPORTED:
                self.lang = lang
        except (json.JSONDecodeError, OSError):
            pass

    def save_settings(self) -> None:
        try:
            SETTINGS_PATH.write_text(
                json.dumps({"language": self.lang}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def set_language(self, lang: str) -> None:
        if lang not in self.SUPPORTED:
            return
        self.lang = lang
        self.save_settings()

    def t(self, key: str, **kwargs) -> str:
        text = self._catalog.get(self.lang, {}).get(key)
        if text is None:
            text = self._catalog.get("en", {}).get(key, key)
        if kwargs:
            return text.format(**kwargs)
        return text


_i18n = I18n()


def get_i18n() -> I18n:
    return _i18n


def t(key: str, **kwargs) -> str:
    return _i18n.t(key, **kwargs)
