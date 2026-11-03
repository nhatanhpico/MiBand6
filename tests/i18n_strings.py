"""Thu thập mọi chuỗi giao diện cần bản dịch tiếng Anh (dùng cho kiểm thử và khi thêm chuỗi mới)."""

from __future__ import annotations

import ast
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "miband6"
STATIC = PKG / "web" / "static"
SWIFT = ROOT / "macos" / "Sources"
ATTRS = ("placeholder", "aria-label", "title", "data-empty")
SKIP_TAGS = {"script", "style", "pre", "code", "textarea", "svg"}
VOID = {"meta", "link", "input", "br", "img", "hr", "source", "use", "circle", "rect", "path", "stop"}


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack: list[tuple[str, dict]] = []
        self.out: set[str] = set()

    def _skipping(self) -> bool:
        return any(t in SKIP_TAGS or a.get("id") == "logView" for t, a in self.stack)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for k in ATTRS:
            if a.get(k) and not (tag == "svg" and k == "title"):
                self.out.add(a[k])
        if "data-i18n-value" in a and a.get("value"):
            self.out.add(a["value"])
        if tag not in VOID:
            self.stack.append((tag, a))

    def handle_startendtag(self, tag, attrs):
        a = dict(attrs)
        for k in ATTRS:
            if a.get(k):
                self.out.add(a[k])

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        text = re.sub(r"\s+", " ", data.strip())
        if text and not self._skipping() and any(t == "body" for t, _ in self.stack):
            self.out.add(text)


def html_strings() -> set[str]:
    c = _Collector()
    c.feed((STATIC / "index.html").read_text("utf-8"))
    # bỏ các chuỗi không phải chữ (số, ký hiệu, tên riêng không cần dịch)
    return {s for s in c.out if re.search(r"[A-Za-zÀ-ỹ]", s) and not re.fullmatch(r"0x[0-9a-f]+", s) and s not in {"VI", "EN", "Mi Band", "Mi Band 6", "—", "km", "kcal", "Firmware", "Serial", "Auth key"}}


def js_strings() -> set[str]:
    src = (STATIC / "app.js").read_text("utf-8")
    return {m.encode().decode("unicode_escape").encode("latin-1").decode("utf-8") if "\\u" in m else m
            for m in re.findall(r'\bt\("((?:[^"\\]|\\.)*)"', src)}


def swift_strings() -> set[str]:
    """t("…") trong ứng dụng macOS (macos/Sources/*.swift): menu, thông báo."""
    out: set[str] = set()
    for path in SWIFT.glob("*.swift"):
        out |= {m.replace('\\"', '"') for m in re.findall(r'\bt\("((?:[^"\\]|\\.)*)"', path.read_text("utf-8"))}
    return out


def py_strings() -> set[str]:
    out: set[str] = set()
    for path in PKG.rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr" \
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                out.add(node.args[0].value)
    return out


def label_strings() -> set[str]:
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from miband6 import protocol as P

    return set(P.MENU_LABELS.values()) | set(P.NOTIFICATION_ICONS) | set(P.DEVICE_EVENTS.values())


def all_strings() -> dict[str, set[str]]:
    return {"html": html_strings(), "js": js_strings(), "py": py_strings(), "labels": label_strings(),
            "swift": swift_strings()}


if __name__ == "__main__":
    import json
    import sys

    have = {}
    p = STATIC / "i18n" / "en.json"
    if p.exists():
        have = json.loads(p.read_text("utf-8"))
    for group, items in all_strings().items():
        missing = sorted(s for s in items if s not in have)
        print(f"== {group}: {len(items)} chuỗi, thiếu {len(missing)}", file=sys.stderr)
        for s in missing:
            print(json.dumps(s, ensure_ascii=False))
