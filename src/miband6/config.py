"""Lưu cấu hình của ứng dụng (auth key theo từng vòng tay, hồ sơ người dùng, cài đặt gần nhất)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def config_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "MiBand6Manager"
    d.mkdir(parents=True, exist_ok=True)
    return d


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or (config_dir() / "config.json")
        self.data: dict = {"devices": {}, "last_device": None, "profile": {}, "settings": {}}
        try:
            self.data.update(json.loads(self.path.read_text("utf-8")))
        except (OSError, ValueError):
            pass
        # Bản cũ chia bố cục thành "màn hình chính" và "Thêm"; Mi Band 6 chỉ có một danh sách.
        s = self.data.setdefault("settings", {})
        if "display_main" in s or "display_more" in s:
            s["display_items"] = list(s.pop("display_main", None) or []) + list(s.pop("display_more", None) or [])

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
        try:
            os.chmod(tmp, 0o600)  # chứa auth key: chỉ người dùng hiện tại được đọc
        except OSError:
            pass
        tmp.replace(self.path)

    def device(self, address: str) -> dict:
        return self.data["devices"].setdefault(address, {})

    def remember_device(self, address: str, name: str, key_hex: str, protocol: str | None) -> None:
        d = self.device(address)
        d.update({"name": name, "auth_key": key_hex})
        if protocol:
            d["protocol"] = protocol
        self.data["last_device"] = address
        self.save()

    def forget_device(self, address: str) -> None:
        self.data["devices"].pop(address, None)
        if self.data.get("last_device") == address:
            self.data["last_device"] = None
        self.save()
