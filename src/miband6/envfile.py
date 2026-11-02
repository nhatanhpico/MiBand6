"""Đọc tệp .env (dòng KEY=VALUE) vào biến môi trường.

Biến dùng được:
    MIBAND6_AUTH_KEY   auth key 32 ký tự hex (bắt buộc nếu muốn dùng .env)
    MIBAND6_ADDRESS    mã thiết bị Bluetooth của vòng tay (không bắt buộc)
    MIBAND6_PROTOCOL   auto | classic | 2021 (không bắt buộc)

Biến đã có sẵn trong môi trường không bị ghi đè.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_KEY = "MIBAND6_AUTH_KEY"
ENV_ADDRESS = "MIBAND6_ADDRESS"
ENV_PROTOCOL = "MIBAND6_PROTOCOL"


def parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, sep, value = line.partition("=")
        if not sep or not key.strip():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        out[key.strip()] = value
    return out


def load_env(path: str | os.PathLike | None = None) -> Path | None:
    """Nạp tệp .env đầu tiên tìm thấy (đường dẫn chỉ định, thư mục hiện tại, rồi thư mục dự án)."""
    candidates = [Path(path).expanduser()] if path else [Path.cwd() / ".env", PROJECT_ROOT / ".env"]
    for p in candidates:
        if p.is_file():
            for k, v in parse_env(p.read_text("utf-8")).items():
                os.environ.setdefault(k, v)
            return p
    return None


def env_settings() -> tuple[str | None, str | None, str | None]:
    """(auth key, địa chỉ, giao thức) từ biến môi trường; chuỗi rỗng coi như không có."""
    get = lambda k: (os.environ.get(k) or "").strip() or None  # noqa: E731
    return get(ENV_KEY), get(ENV_ADDRESS), get(ENV_PROTOCOL)


def write_env_value(path: Path, key: str, value: str) -> None:
    """Thêm hoặc thay một dòng KEY=VALUE trong tệp .env, giữ nguyên các dòng khác."""
    lines = path.read_text("utf-8").splitlines() if path.is_file() else []
    new = f"{key}={value}"
    for i, line in enumerate(lines):
        if line.strip().removeprefix("export ").split("=", 1)[0].strip() == key:
            lines[i] = new
            break
    else:
        lines.append(new)
    path.write_text("\n".join(lines) + "\n", "utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
