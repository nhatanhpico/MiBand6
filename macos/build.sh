#!/bin/bash
# Đóng gói ứng dụng macOS "Mi Band 6.app" vào thư mục dist/.
#
#   ./macos/build.sh          ứng dụng độc lập: chép Python 3.12 và thư viện vào trong .app
#                             (kéo vào /Applications hoặc chép sang máy Mac khác cùng loại chip đều chạy được)
#   ./macos/build.sh --dev    dùng thẳng mã nguồn và .venv của dự án: sửa code xong chỉ cần mở lại ứng dụng
#
# Cần Xcode Command Line Tools (swiftc, iconutil, codesign) và uv.
# MIBAND6_SIGN_IDENTITY=<tên chứng chỉ> để ký bằng chứng chỉ của bạn thay vì ký ad-hoc.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/macos"
MODE="bundle"
for arg in "$@"; do
  case "$arg" in
    --dev) MODE="dev" ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Tham số không hợp lệ: $arg (xem --help)" >&2; exit 2 ;;
  esac
done

APP="$ROOT/dist/Mi Band 6.app"
CONTENTS="$APP/Contents"
RES="$CONTENTS/Resources"
WORK="$SRC/build"
ARCH="$(uname -m)"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
PYVER="$(cat "$ROOT/.python-version" 2>/dev/null || echo 3.12)"

command -v uv >/dev/null || { echo "Chưa cài uv: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2; exit 1; }
xcrun --find swiftc >/dev/null 2>&1 || { echo "Chưa có swiftc. Cài Xcode Command Line Tools: xcode-select --install" >&2; exit 1; }

echo "==> Dọn bản cũ"
rm -rf "$APP" "$WORK"
mkdir -p "$CONTENTS/MacOS" "$RES" "$WORK"

echo "==> Biên dịch phần Swift ($ARCH)"
xcrun swiftc -swift-version 5 -O -target "$ARCH-apple-macos12.0" \
  -framework AppKit -framework WebKit -framework ServiceManagement -framework UserNotifications \
  "$SRC"/Sources/*.swift -o "$CONTENTS/MacOS/MiBand6"

echo "==> Info.plist và biểu tượng"
sed "s/__VERSION__/$VERSION/g" "$SRC/Info.plist" > "$CONTENTS/Info.plist"
printf 'APPL????' > "$CONTENTS/PkgInfo"
cp -R "$SRC/Resources/." "$RES/"
xcrun swift "$SRC/make_icon.swift" "$WORK/AppIcon.iconset"
iconutil -c icns "$WORK/AppIcon.iconset" -o "$RES/AppIcon.icns"

if [ "$MODE" = dev ]; then
  echo "==> Chế độ --dev: server chạy từ mã nguồn trong $ROOT"
  (cd "$ROOT" && uv sync --quiet)
  cat > "$RES/run-server" <<EOF
#!/bin/sh
# Tạo bởi macos/build.sh --dev: chạy server bằng .venv và mã nguồn của dự án.
cd "$ROOT" || exit 1
export PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
exec "$ROOT/.venv/bin/python" -m miband6.web.server "\$@"
EOF
else
  echo "==> Chép Python $PYVER vào ứng dụng"
  PY="$(uv python find --managed-python "$PYVER" 2>/dev/null || true)"
  if [ -z "$PY" ]; then
    uv python install "$PYVER"
    PY="$(uv python find --managed-python "$PYVER")"
  fi
  PYHOME="$(cd "$(dirname "$(realpath "$PY")")/.." && pwd)"
  PYLIB="lib/python$PYVER"
  # bỏ những phần server không dùng (Tk, IDLE, pip, tệp header) cho ứng dụng gọn hơn
  rsync -a \
    --exclude "/include/" --exclude "/share/" --exclude "/lib/pkgconfig/" \
    --exclude "/lib/tcl*" --exclude "/lib/tk*" --exclude "/lib/itcl*" --exclude "/lib/thread*" \
    --exclude "/lib/libtcl*" --exclude "/$PYLIB/site-packages/" \
    --exclude "/$PYLIB/idlelib/" --exclude "/$PYLIB/tkinter/" --exclude "/$PYLIB/turtledemo/" \
    --exclude "/$PYLIB/ensurepip/" --exclude "/$PYLIB/lib-dynload/_tkinter*" \
    --exclude "/bin/idle*" --exclude "/bin/pip*" --exclude "/bin/2to3*" --exclude "/bin/pydoc*" \
    "$PYHOME/" "$RES/python/"
  mkdir -p "$RES/python/$PYLIB/site-packages"
  "$RES/python/bin/python3" -m compileall -q -j 0 "$RES/python/$PYLIB" >/dev/null || true

  echo "==> Cài miband6 và thư viện vào ứng dụng"
  uv pip install --quiet --python "$RES/python/bin/python3" --target "$RES/site-packages" \
    --compile-bytecode "$ROOT"
  rm -rf "$RES/site-packages/PyObjCTest"   # bộ kiểm thử của pyobjc, 16 MB, không cần khi chạy

  cat > "$RES/run-server" <<'EOF'
#!/bin/sh
# Tạo bởi macos/build.sh: chạy server bằng Python đóng gói sẵn trong ứng dụng.
# Không ghi .pyc vào trong .app (làm hỏng chữ ký của ứng dụng).
HERE="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$HERE/site-packages" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
# auth key trong tệp .env của dự án (nếu có), giống khi chạy uv run miband6-web
ENV_FILE="__ENV_FILE__"
if [ -f "$ENV_FILE" ]; then set -- "$@" --env "$ENV_FILE"; fi
exec "$HERE/python/bin/python3" -m miband6.web.server "$@"
EOF
  ESCAPED_ENV="$(printf '%s' "$ROOT/.env" | sed 's/[&|\\]/\\&/g')"
  sed -i '' "s|__ENV_FILE__|$ESCAPED_ENV|" "$RES/run-server"
fi
chmod +x "$RES/run-server"

echo "==> Ký ứng dụng"
IDENTITY="${MIBAND6_SIGN_IDENTITY:--}"
codesign --force --deep --sign "$IDENTITY" "$APP"
rm -rf "$WORK"

SIZE="$(du -sh "$APP" | cut -f1)"
echo
echo "Xong: $APP ($SIZE, chế độ $MODE)"
echo "Mở thử:          open \"$APP\""
echo "Cài vào máy:     ditto \"$APP\" \"/Applications/Mi Band 6.app\""
