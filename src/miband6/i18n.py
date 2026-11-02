"""Đa ngôn ngữ (tiếng Việt / tiếng Anh).

Chuỗi gốc viết bằng tiếng Việt ngay trong mã; bản tiếng Anh nằm trong
web/static/i18n/en.json (dùng chung cho server và giao diện web).

    tr("Đã lưu hồ sơ vào vòng tay.")
    tr("Lỗi khi đọc: {e}", e=err)
"""

from __future__ import annotations

import json
from pathlib import Path

CATALOG_PATH = Path(__file__).parent / "web" / "static" / "i18n" / "en.json"
LANGS = ("vi", "en")

_lang = "vi"
_catalog: dict[str, str] | None = None


def set_lang(lang: str) -> str:
    global _lang
    _lang = lang if lang in LANGS else "vi"
    return _lang


def get_lang() -> str:
    return _lang


def catalog() -> dict[str, str]:
    global _catalog
    if _catalog is None:
        try:
            _catalog = json.loads(CATALOG_PATH.read_text("utf-8"))
        except (OSError, ValueError):
            _catalog = {}
    return _catalog


def tr(source: str, **values) -> str:
    text = catalog().get(source, source) if _lang == "en" else source
    if values:
        try:
            return text.format(**values)
        except (KeyError, IndexError, ValueError):
            return source.format(**values)
    return text
