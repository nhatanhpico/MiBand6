#!/bin/bash
# Nhấp đúp để chạy server Quản lý Mi Band 6 và mở giao diện trong trình duyệt (macOS).
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.homebrew/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "Chưa cài uv. Cài bằng lệnh:"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  read -r -p "Nhấn Enter để đóng…"
  exit 1
fi
uv run miband6-web "$@"
