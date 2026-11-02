"""Giao diện desktop quản lý Mi Smart Band 6."""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QDate, QPointF, QRectF, QSize, Qt, QTime, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import protocol as P
from ..config import Store
from ..device import PROTOCOL_2021, PROTOCOL_AUTO, PROTOCOL_CLASSIC, MiBand6, scan
from .worker import BleWorker

# ---------------------------------------------------------------- thiết kế

PAPER = "#EEF0EC"
SURFACE = "#FFFFFF"
INK = "#1E2420"
MUTED = "#66706A"
LINE = "#D3D8D2"
ACCENT = "#4F6B33"
ACCENT_SOFT = "#E1E8D6"
DANGER = "#B3402F"
BAND_BODY = "#202422"
SCREEN_HR = "#FF5363"
SCREEN_STEPS = "#FFB224"
SCREEN_BATTERY = "#3DD68C"

GUIDE_URL = "https://gadgetbridge.org/basics/pairing/huami-xiaomi-server/"
HUAMI_TOKEN_URL = "https://codeberg.org/argrento/huami-token"

WEEKDAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]


def number_font_family() -> str:
    families = set(QFontDatabase.families())
    for fam in ("DIN Alternate", "DIN Condensed", "Avenir Next Condensed", "Avenir Next", "Bahnschrift"):
        if fam in families:
            return fam
    return QApplication.font().family()


def demo_store_path() -> Path:
    return Path(tempfile.gettempdir()) / "miband6-demo-config.json"


def fmt_int(n: int | None) -> str:
    return "—" if n is None else f"{n:,}".replace(",", ".")


def qtime(t: QTime) -> dt.time:
    return dt.time(t.hour(), t.minute())


def to_qtime(s: str, default: str) -> QTime:
    t = QTime.fromString(s or default, "HH:mm")
    return t if t.isValid() else QTime.fromString(default, "HH:mm")


STYLE_TEMPLATE = """
QMainWindow, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {PAPER}; }}
QWidget {{ color: {INK}; font-size: 13px; }}
QFrame#sidebar {{ background: {SURFACE}; border-right: 1px solid {LINE}; }}
QLabel#appName {{ font-size: 15px; font-weight: 600; }}
QLabel#deviceLine {{ color: {MUTED}; }}
QListWidget#nav {{ background: transparent; border: none; outline: 0; font-size: 14px; }}
QListWidget#nav::item {{ padding: 8px 12px; border-radius: 8px; margin: 1px 10px; }}
QListWidget#nav::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT}; font-weight: 600; }}
QListWidget#nav::item:hover:!selected {{ background: {PAPER}; }}
QLabel#pageTitle {{ font-size: 24px; font-weight: 600; }}
QLabel#pageHelp, QLabel#help {{ color: {MUTED}; }}
QFrame#section {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px; }}
QLabel#sectionTitle {{ font-size: 15px; font-weight: 600; }}
QLabel#bigNumber {{ font-size: 44px; font-weight: 700; }}
QLabel#midNumber {{ font-size: 26px; font-weight: 700; }}
QLabel#unit {{ color: {MUTED}; font-size: 13px; }}
QLabel#status {{ color: {MUTED}; }}
QLabel#statusError {{ color: {DANGER}; }}
QPushButton {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {MUTED}; }}
QPushButton:disabled {{ color: #A7AEA9; border-color: #E2E6E1; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton#primary:hover {{ background: #435C2B; }}
QPushButton#primary:disabled {{ background: #B8C4AC; border-color: #B8C4AC; color: #F4F6F1; }}
QPushButton#danger {{ color: {DANGER}; }}
QPushButton:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton#link {{ border: none; background: transparent; color: {ACCENT}; padding: 0; text-decoration: underline; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit, QPlainTextEdit {{
    background: {SURFACE}; border: 1px solid {LINE}; border-radius: 7px; padding: 5px 8px; min-height: 20px;
    selection-background-color: {ACCENT_SOFT}; selection-color: {INK};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus, QDateEdit:focus {{ border-color: {ACCENT}; }}
QToolButton#day {{ border: 1px solid {LINE}; border-radius: 14px; min-width: 28px; min-height: 28px; background: {SURFACE}; color: {MUTED}; }}
QToolButton#day:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: 600; }}
QToolButton#day:disabled {{ color: #C3C9C4; }}
QTableWidget, QListWidget#items {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 8px; gridline-color: {PAPER}; }}
QTableWidget::item:selected, QListWidget#items::item:selected {{ background: {ACCENT_SOFT}; color: {INK}; }}
QHeaderView::section {{ background: {SURFACE}; color: {MUTED}; border: none; border-bottom: 1px solid {LINE}; padding: 6px; }}
QProgressBar {{ background: {PAPER}; border: none; border-radius: 4px; max-height: 8px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QStatusBar {{ background: {SURFACE}; color: {MUTED}; border-top: 1px solid {LINE}; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }}
QComboBox::down-arrow {{ image: url({arrows}/down.png); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {LINE}; selection-background-color: {ACCENT_SOFT}; selection-color: {INK}; outline: 0; }}
QAbstractSpinBox {{ padding-right: 24px; }}
QAbstractSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 22px; border: none; background: transparent; }}
QAbstractSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border: none; background: transparent; }}
QAbstractSpinBox::up-arrow {{ image: url({arrows}/up.png); width: 9px; height: 9px; }}
QAbstractSpinBox::down-arrow {{ image: url({arrows}/down.png); width: 9px; height: 9px; }}
QListWidget#items::item {{ padding: 5px 6px; }}
QDateEdit::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }}
QDateEdit::down-arrow {{ image: url({arrows}/down.png); width: 10px; height: 10px; }}
"""


def make_arrow_icons() -> str:
    d = Path(tempfile.gettempdir()) / "miband6-ui"
    d.mkdir(exist_ok=True)
    for name, up in (("down", False), ("up", True)):
        pm = QPixmap(24, 24)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(MUTED), 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if up:
            p.drawPolyline([QPointF(5, 15), QPointF(12, 8), QPointF(19, 15)])
        else:
            p.drawPolyline([QPointF(5, 9), QPointF(12, 16), QPointF(19, 9)])
        p.end()
        pm.save(str(d / f"{name}.png"))
    return d.as_posix()


def build_style() -> str:
    vals = dict(PAPER=PAPER, SURFACE=SURFACE, INK=INK, MUTED=MUTED, LINE=LINE, ACCENT=ACCENT,
                ACCENT_SOFT=ACCENT_SOFT, DANGER=DANGER, arrows=make_arrow_icons())
    return STYLE_TEMPLATE.format(**vals)


# ---------------------------------------------------------------- vòng tay vẽ tay


class BandPreview(QWidget):
    """Bản vẽ màn hình Mi Band 6, hiển thị dữ liệu trực tiếp từ vòng tay."""

    def __init__(self, num_family: str):
        super().__init__()
        self.num_family = num_family
        self.connected = False
        self.busy = False
        self.hr: int | None = None
        self.steps: int | None = None
        self.goal = 8000
        self.battery: int | None = None
        self.charging = False
        self.setFixedSize(QSize(204, 300))
        t = QTimer(self)
        t.timeout.connect(self.update)
        t.start(1000)

    def sizeHint(self):
        return QSize(204, 300)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = 116, 272
        x = (self.width() - w) / 2
        y = (self.height() - h) / 2
        body = QRectF(x, y, w, h)
        path = QPainterPath()
        path.addRoundedRect(body, w / 2, w / 2)
        p.fillPath(path, QColor(BAND_BODY))
        screen = body.adjusted(7, 7, -7, -7)
        sp = QPainterPath()
        sp.addRoundedRect(screen, screen.width() / 2, screen.width() / 2)
        p.fillPath(sp, QColor("#000000"))
        p.setClipPath(sp)

        cx = screen.center().x()
        num = QFont(self.num_family)
        num.setBold(True)

        def text(y0, s, size, color, bold=True, family=None):
            f = QFont(family or self.num_family) if family is not False else QFont()
            f.setPixelSize(size)
            f.setBold(bold)
            p.setFont(f)
            p.setPen(QColor(color))
            p.drawText(QRectF(screen.left(), y0, screen.width(), size + 8), Qt.AlignHCenter | Qt.AlignVCenter, s)

        top = screen.top()
        now = dt.datetime.now()
        if not self.connected:
            text(top + 30, now.strftime("%H:%M"), 34, "#343A37")
            text(top + 110, "Đang kết nối…" if self.busy else "Chưa kết nối", 12, "#7C847F", False, False)
            p.end()
            return

        text(top + 30, now.strftime("%H:%M"), 34, "#FFFFFF")
        text(top + 72, f"{WEEKDAYS[now.weekday()]}  {now:%d/%m}", 12, "#9AA39E", False, False)
        # nhịp tim
        text(top + 96, f"♥ {self.hr}" if self.hr else "♥ --", 18, SCREEN_HR)
        # bước chân + vòng tiến độ
        ring = QRectF(cx - 27, top + 130, 54, 54)
        p.setPen(QPen(QColor("#2A2E2B"), 5, Qt.SolidLine, Qt.RoundCap))
        p.drawEllipse(ring)
        if self.steps is not None and self.goal:
            frac = min(1.0, self.steps / self.goal)
            p.setPen(QPen(QColor(SCREEN_STEPS), 5, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(ring, 90 * 16, int(-frac * 360 * 16))
        f = QFont(self.num_family)
        f.setPixelSize(13 if (self.steps or 0) < 10000 else 11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(SCREEN_STEPS))
        p.drawText(ring, Qt.AlignCenter, fmt_int(self.steps) if self.steps is not None else "--")
        # pin
        if self.battery is not None:
            bw = 40
            bx = cx - bw / 2
            by = top + 222
            p.setPen(QPen(QColor("#5C635F"), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(bx, by, bw, 12), 3, 3)
            p.fillRect(QRectF(bx + bw + 1, by + 3.5, 2, 5), QColor("#5C635F"))
            fill = max(0.0, min(1.0, self.battery / 100)) * (bw - 4)
            color = SCREEN_BATTERY if self.battery > 20 else SCREEN_HR
            p.fillRect(QRectF(bx + 2, by + 2, fill, 8), QColor(color))
            text(by - 24, f"{self.battery}%{' ⚡' if self.charging else ''}", 11, "#9AA39E", False, False)
        p.end()


# ---------------------------------------------------------------- dựng khối


class Section(QFrame):
    def __init__(self, title: str, help_text: str | None = None):
        super().__init__()
        self.setObjectName("section")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(22, 18, 22, 18)
        self.lay.setSpacing(12)
        t = QLabel(title)
        t.setObjectName("sectionTitle")
        self.lay.addWidget(t)
        if help_text:
            h = QLabel(help_text)
            h.setObjectName("help")
            h.setWordWrap(True)
            self.lay.addWidget(h)
        self.footer = QHBoxLayout()
        self.footer.setSpacing(8)

    def form(self) -> QFormLayout:
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        f.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        f.setHorizontalSpacing(18)
        f.setVerticalSpacing(10)
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.lay.addLayout(f)
        return f

    def add_footer(self, *buttons: QWidget, stretch_first=True) -> None:
        if stretch_first:
            self.footer.addStretch(1)
        for b in buttons:
            self.footer.addWidget(b)
        self.lay.addLayout(self.footer)


def make_page(title: str, help_text: str | None = None, extra: QWidget | None = None):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    inner = QWidget()
    inner.setObjectName("page")
    outer = QHBoxLayout(inner)
    outer.setContentsMargins(0, 0, 0, 0)
    col = QWidget()
    col.setMaximumWidth(780)
    lay = QVBoxLayout(col)
    lay.setContentsMargins(36, 30, 36, 36)
    lay.setSpacing(16)
    head = QHBoxLayout()
    t = QLabel(title)
    t.setObjectName("pageTitle")
    head.addWidget(t)
    head.addStretch(1)
    if extra:
        head.addWidget(extra)
    lay.addLayout(head)
    if help_text:
        h = QLabel(help_text)
        h.setObjectName("pageHelp")
        h.setWordWrap(True)
        lay.addWidget(h)
    outer.addWidget(col, 1)
    outer.addStretch(0)
    scroll.setWidget(inner)
    return scroll, lay


def time_edit(value: str, default: str) -> QTimeEdit:
    e = QTimeEdit()
    e.setDisplayFormat("HH:mm")
    e.setTime(to_qtime(value, default))
    return e


def row(*widgets, stretch=True) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(8)
    for w in widgets:
        if isinstance(w, str):
            lab = QLabel(w)
            lab.setObjectName("help")
            h.addWidget(lab)
        else:
            h.addWidget(w)
    if stretch:
        h.addStretch(1)
    return h


def combo(items: list[tuple[str, object]], current=None) -> QComboBox:
    c = QComboBox()
    for label, data in items:
        c.addItem(label, data)
    if current is not None:
        i = c.findData(current)
        if i >= 0:
            c.setCurrentIndex(i)
    return c


def button(text: str, kind: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    b.setCursor(Qt.PointingHandCursor)
    return b


# ---------------------------------------------------------------- cửa sổ chính


class MainWindow(QMainWindow):
    def __init__(self, demo: bool = False):
        super().__init__()
        self.demo = demo
        self.setWindowTitle("Quản lý Mi Band 6" + (" (xem thử, không dùng Bluetooth)" if demo else ""))
        self.resize(1120, 820)
        self.setMinimumSize(980, 640)
        self.store = Store(demo_store_path() if demo else None)
        self.settings = self.store.data.setdefault("settings", {})
        self.profile = self.store.data.setdefault("profile", {})
        self.worker = BleWorker()
        self.worker.event.connect(self._on_band_event)
        self.worker.log.connect(self._log)
        self.band: MiBand6 | None = None
        self.scan_results: list = []
        self.needs_connection: list[QWidget] = []
        self.num_family = number_font_family()
        self._find_phone_timer: QTimer | None = None
        self._find_phone_box: QMessageBox | None = None

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        pages = [
            ("Kết nối", self._page_connect()),
            ("Tổng quan", self._page_overview()),
            ("Hồ sơ và mục tiêu", self._page_profile()),
            ("Màn hình", self._page_display()),
            ("Sức khỏe", self._page_health()),
            ("Báo thức", self._page_alarms()),
            ("Thông báo và tìm", self._page_tools()),
            ("Nhật ký", self._page_log()),
        ]
        for name, widget in pages:
            QListWidgetItem(name, self.nav)
            self.stack.addWidget(widget)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self._set_connected(False)
        self.statusBar().showMessage("Sẵn sàng. Bấm Quét để tìm vòng tay.")

    # ------------------------------------------------------------ sidebar

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(236)
        v = QVBoxLayout(side)
        v.setContentsMargins(0, 22, 0, 16)
        v.setSpacing(6)
        name = QLabel("Mi Band 6")
        name.setObjectName("appName")
        name.setAlignment(Qt.AlignHCenter)
        v.addWidget(name)
        self.preview = BandPreview(number_font_family())
        self.preview.goal = int(self.profile.get("goal", 8000))
        v.addWidget(self.preview, 0, Qt.AlignHCenter)
        self.device_line = QLabel("Chưa kết nối")
        self.device_line.setObjectName("deviceLine")
        self.device_line.setAlignment(Qt.AlignHCenter)
        self.device_line.setWordWrap(True)
        v.addWidget(self.device_line)
        v.addSpacing(12)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFocusPolicy(Qt.StrongFocus)
        v.addWidget(self.nav, 1)
        return side

    # ------------------------------------------------------------ trang: kết nối

    def _page_connect(self) -> QWidget:
        page, lay = make_page(
            "Kết nối vòng tay",
            "Vòng tay chỉ giữ một kết nối tại một thời điểm. Hãy tắt Bluetooth trên điện thoại "
            "(hoặc thoát hẳn Mi Fitness / Zepp Life) trước khi kết nối từ máy tính.",
        )
        s1 = Section("1. Tìm vòng tay")
        self.btn_scan = button("Quét", "primary")
        self.btn_scan.clicked.connect(self._scan)
        self.chk_all = QCheckBox("Hiện mọi thiết bị Bluetooth")
        s1.lay.addLayout(row(self.btn_scan, self.chk_all))
        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["Tên", "Mã thiết bị", "Tín hiệu"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl.setMinimumHeight(120)
        self.tbl.setMaximumHeight(170)
        self.tbl.itemSelectionChanged.connect(self._on_pick_device)
        s1.lay.addWidget(self.tbl)
        lay.addWidget(s1)

        s2 = Section(
            "2. Nhập auth key",
            "Mã bí mật 32 ký tự được tạo khi bạn ghép đôi vòng tay bằng Mi Fitness hoặc Zepp Life. "
            "Ứng dụng lưu mã này trên máy, chỉ tài khoản của bạn đọc được.",
        )
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("Ví dụ: 0x8f2b1c0a77d94e3fa5c1b2e3d4f50617")
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setMinimumWidth(380)
        show = button("Hiện")
        show.setCheckable(True)
        show.toggled.connect(lambda on: (self.key_edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                                         show.setText("Ẩn" if on else "Hiện")))
        s2.lay.addLayout(row(self.key_edit, show))
        howto = button("Cách lấy auth key", "link")
        howto.clicked.connect(self._show_key_help)
        s2.lay.addLayout(row(howto))
        lay.addWidget(s2)

        s3 = Section("3. Kết nối")
        f = s3.form()
        self.cmb_proto = combo(
            [
                ("Tự động (thử kiểu cũ, rồi kiểu mới)", PROTOCOL_AUTO),
                ("Kiểu cũ", PROTOCOL_CLASSIC),
                ("Kiểu mới (firmware cập nhật sau 2022)", PROTOCOL_2021),
            ]
        )
        f.addRow("Kiểu xác thực", self.cmb_proto)
        self.lbl_addr = QLabel("Chưa chọn vòng tay")
        self.lbl_addr.setObjectName("help")
        self.lbl_addr.setTextInteractionFlags(Qt.TextSelectableByMouse)
        f.addRow("Vòng tay", self.lbl_addr)
        self.btn_connect = button("Kết nối", "primary")
        self.btn_connect.clicked.connect(self._connect)
        self.btn_disconnect = button("Ngắt kết nối")
        self.btn_disconnect.clicked.connect(self._disconnect)
        self.lbl_conn = QLabel("")
        self.lbl_conn.setObjectName("status")
        self.lbl_conn.setWordWrap(True)
        s3.lay.addWidget(self.lbl_conn)
        s3.add_footer(self.btn_disconnect, self.btn_connect)
        lay.addWidget(s3)
        lay.addStretch(1)

        # điền lại vòng tay đã dùng lần trước (hoặc từ tệp .env)
        from ..envfile import env_settings, load_env

        load_env()
        env_key, env_address, _ = env_settings()
        self.selected_address: str | None = self.store.data.get("last_device") or env_address
        self.selected_device = None
        if self.selected_address:
            d = self.store.device(self.selected_address)
            self.key_edit.setText(d.get("auth_key", ""))
            self.lbl_addr.setText(f"{d.get('name', 'Mi Smart Band 6')}  ·  {self.selected_address}")
            i = self.cmb_proto.findData(d.get("protocol", PROTOCOL_AUTO))
            if i >= 0:
                self.cmb_proto.setCurrentIndex(i)
        if env_key and not self.key_edit.text():
            self.key_edit.setText(env_key)
        return page

    # ------------------------------------------------------------ trang: tổng quan

    def _page_overview(self) -> QWidget:
        refresh = button("Đọc lại")
        refresh.clicked.connect(self._refresh)
        self.needs_connection.append(refresh)
        page, lay = make_page("Tổng quan", None, refresh)

        act = Section("Hôm nay")
        num = QFont(self.num_family)
        self.lbl_steps = QLabel("—")
        self.lbl_steps.setObjectName("bigNumber")
        self.lbl_steps.setFont(num)
        self.lbl_goal = QLabel("bước")
        self.lbl_goal.setObjectName("unit")
        h = QHBoxLayout()
        h.setSpacing(8)
        h.addWidget(self.lbl_steps, 0, Qt.AlignBottom)
        h.addWidget(self.lbl_goal, 0, Qt.AlignBottom)
        h.addStretch(1)
        act.lay.addLayout(h)
        self.bar_goal = QProgressBar()
        self.bar_goal.setTextVisible(False)
        act.lay.addWidget(self.bar_goal)
        g = QGridLayout()
        g.setHorizontalSpacing(40)
        self.lbl_dist = QLabel("—")
        self.lbl_cal = QLabel("—")
        for i, (lab, w, unit) in enumerate([("Quãng đường", self.lbl_dist, "km"), ("Năng lượng", self.lbl_cal, "kcal")]):
            w.setObjectName("midNumber")
            w.setFont(num)
            cap = QLabel(lab)
            cap.setObjectName("unit")
            g.addWidget(cap, 0, i)
            hh = QHBoxLayout()
            hh.setSpacing(5)
            hh.addWidget(w)
            u = QLabel(unit)
            u.setObjectName("unit")
            hh.addWidget(u, 0, Qt.AlignBottom)
            hh.addStretch(1)
            g.addLayout(hh, 1, i)
        g.setColumnStretch(2, 1)
        act.lay.addLayout(g)
        lay.addWidget(act)

        pair = QHBoxLayout()
        pair.setSpacing(16)
        bat = Section("Pin")
        self.lbl_bat = QLabel("—")
        self.lbl_bat.setObjectName("midNumber")
        self.lbl_bat.setFont(num)
        self.lbl_bat_note = QLabel("")
        self.lbl_bat_note.setObjectName("help")
        self.lbl_bat_note.setWordWrap(True)
        bat.lay.addWidget(self.lbl_bat)
        bat.lay.addWidget(self.lbl_bat_note)
        bat.lay.addStretch(1)
        pair.addWidget(bat, 1)

        hr = Section("Nhịp tim")
        self.lbl_hr = QLabel("—")
        self.lbl_hr.setObjectName("midNumber")
        self.lbl_hr.setFont(num)
        self.lbl_hr_note = QLabel("Đeo vòng sát cổ tay rồi bấm Đo ngay.")
        self.lbl_hr_note.setObjectName("help")
        self.lbl_hr_note.setWordWrap(True)
        hr.lay.addWidget(self.lbl_hr)
        hr.lay.addWidget(self.lbl_hr_note)
        self.btn_hr = button("Đo ngay", "primary")
        self.btn_hr.clicked.connect(self._measure_hr)
        self.btn_hr_live = button("Theo dõi liên tục")
        self.btn_hr_live.setCheckable(True)
        self.btn_hr_live.toggled.connect(self._toggle_hr_live)
        self.needs_connection += [self.btn_hr, self.btn_hr_live]
        hr.add_footer(self.btn_hr_live, self.btn_hr, stretch_first=False)
        pair.addWidget(hr, 1)
        lay.addLayout(pair)

        info = Section("Thiết bị")
        f = info.form()
        self.info_labels = {}
        for key, label in [
            ("name", "Tên"),
            ("firmware", "Firmware"),
            ("hardware", "Phần cứng"),
            ("serial", "Số serial"),
            ("protocol", "Kiểu xác thực"),
            ("band_time", "Giờ trên vòng tay"),
        ]:
            w = QLabel("—")
            w.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.info_labels[key] = w
            f.addRow(label, w)
        sync = button("Đồng bộ giờ với máy tính")
        sync.clicked.connect(self._sync_time)
        self.needs_connection.append(sync)
        info.add_footer(sync)
        lay.addWidget(info)
        lay.addStretch(1)
        self._update_goal_label()
        return page

    # ------------------------------------------------------------ trang: hồ sơ

    def _page_profile(self) -> QWidget:
        page, lay = make_page("Hồ sơ và mục tiêu", "Vòng tay dùng các số đo này để tính quãng đường và năng lượng tiêu hao.")
        pr = self.profile
        s = Section("Hồ sơ cơ thể")
        f = s.form()
        self.p_alias = QLineEdit(pr.get("alias", ""))
        self.p_alias.setPlaceholderText("Tên hiển thị")
        self.p_alias.setMinimumWidth(240)
        self.p_birth = QDateEdit()
        self.p_birth.setDisplayFormat("dd/MM/yyyy")
        self.p_birth.setCalendarPopup(True)
        self.p_birth.setDate(QDate.fromString(pr.get("birth", "2000-01-01"), "yyyy-MM-dd"))
        self.p_gender = combo([("Nam", P.GENDER_MALE), ("Nữ", P.GENDER_FEMALE), ("Khác", P.GENDER_OTHER)], pr.get("gender", P.GENDER_MALE))
        self.p_height = QSpinBox()
        self.p_height.setRange(100, 230)
        self.p_height.setSuffix(" cm")
        self.p_height.setValue(int(pr.get("height", 170)))
        self.p_weight = QDoubleSpinBox()
        self.p_weight.setRange(20, 250)
        self.p_weight.setDecimals(1)
        self.p_weight.setSuffix(" kg")
        self.p_weight.setValue(float(pr.get("weight", 60)))
        f.addRow("Tên", self.p_alias)
        f.addRow("Ngày sinh", self.p_birth)
        f.addRow("Giới tính", self.p_gender)
        f.addRow("Chiều cao", self.p_height)
        f.addRow("Cân nặng", self.p_weight)
        b = button("Lưu vào vòng tay", "primary")
        b.clicked.connect(self._apply_profile)
        self.needs_connection.append(b)
        s.add_footer(b)
        lay.addWidget(s)

        g = Section("Mục tiêu hằng ngày")
        f = g.form()
        self.p_goal = QSpinBox()
        self.p_goal.setRange(1000, 60000)
        self.p_goal.setSingleStep(500)
        self.p_goal.setSuffix(" bước")
        self.p_goal.setValue(int(pr.get("goal", 8000)))
        self.p_goal_notify = QCheckBox("Rung khi đạt mục tiêu")
        self.p_goal_notify.setChecked(bool(pr.get("goal_notify", True)))
        f.addRow("Bước chân", self.p_goal)
        f.addRow("", self.p_goal_notify)
        b = button("Lưu vào vòng tay", "primary")
        b.clicked.connect(self._apply_goal)
        self.needs_connection.append(b)
        g.add_footer(b)
        lay.addWidget(g)

        w = Section("Tay đeo", "Chọn đúng tay giúp vòng nhận diện cử chỉ nâng tay chính xác hơn.")
        self.p_left = QRadioButton("Tay trái")
        self.p_right = QRadioButton("Tay phải")
        grp = QButtonGroup(w)
        grp.addButton(self.p_left)
        grp.addButton(self.p_right)
        (self.p_left if pr.get("wear_left", True) else self.p_right).setChecked(True)
        w.lay.addLayout(row(self.p_left, self.p_right))
        b = button("Lưu vào vòng tay", "primary")
        b.clicked.connect(self._apply_wear)
        self.needs_connection.append(b)
        w.add_footer(b)
        lay.addWidget(w)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------ trang: màn hình

    def _page_display(self) -> QWidget:
        page, lay = make_page("Màn hình")
        st = self.settings

        s = Section("Ngôn ngữ và định dạng")
        f = s.form()
        self.d_lang = combo([(v, k) for k, v in P.LANGUAGES.items()], st.get("language", "vi_VN"))
        self.d_24h = combo([("24 giờ", True), ("12 giờ", False)], st.get("time_24h", True))
        self.d_date = combo([(x, x) for x in P.DATE_FORMATS], st.get("date_format", "dd/MM/yyyy"))
        self.d_metric = combo([("Kilômét", True), ("Dặm", False)], st.get("metric", True))
        f.addRow("Ngôn ngữ", self.d_lang)
        f.addRow("Kiểu giờ", self.d_24h)
        f.addRow("Kiểu ngày", self.d_date)
        f.addRow("Khoảng cách", self.d_metric)
        b = button("Lưu vào vòng tay", "primary")
        b.clicked.connect(self._apply_formats)
        self.needs_connection.append(b)
        s.add_footer(b)
        lay.addWidget(s)

        s = Section("Nâng tay để sáng màn hình")
        f = s.form()
        self.d_lift = combo([("Tắt", P.LIFT_OFF), ("Luôn bật", P.LIFT_ON), ("Theo khung giờ", P.LIFT_SCHEDULED)], st.get("lift", P.LIFT_ON))
        self.d_lift_from = time_edit(st.get("lift_from"), "07:00")
        self.d_lift_to = time_edit(st.get("lift_to"), "23:00")
        self.d_lift_sens = combo([("Bình thường", False), ("Nhạy hơn", True)], st.get("lift_sensitive", False))
        f.addRow("Chế độ", self.d_lift)
        f.addRow("Khung giờ", row(self.d_lift_from, "đến", self.d_lift_to))
        f.addRow("Độ nhạy", self.d_lift_sens)
        self._bind_schedule(self.d_lift, P.LIFT_SCHEDULED, self.d_lift_from, self.d_lift_to)
        b = button("Lưu vào vòng tay", "primary")
        b.clicked.connect(self._apply_lift)
        self.needs_connection.append(b)
        s.add_footer(b)
        lay.addWidget(s)

        s = Section("Chế độ ban đêm", "Giảm độ sáng màn hình vào buổi tối.")
        f = s.form()
        self.d_night = combo(
            [("Tắt", P.NIGHT_OFF), ("Từ hoàng hôn đến bình minh", P.NIGHT_SUNSET), ("Theo khung giờ", P.NIGHT_SCHEDULED)],
            st.get("night", P.NIGHT_OFF),
        )
        self.d_night_from = time_edit(st.get("night_from"), "19:00")
        self.d_night_to = time_edit(st.get("night_to"), "07:00")
        f.addRow("Chế độ", self.d_night)
        f.addRow("Khung giờ", row(self.d_night_from, "đến", self.d_night_to))
        self._bind_schedule(self.d_night, P.NIGHT_SCHEDULED, self.d_night_from, self.d_night_to)
        b = button("Lưu vào vòng tay", "primary")
        b.clicked.connect(self._apply_night)
        self.needs_connection.append(b)
        s.add_footer(b)
        lay.addWidget(s)

        s = Section("Khóa bằng mật khẩu", "Vòng tay hỏi mã 6 số khi bạn đeo lại sau khi tháo ra.")
        f = s.form()
        self.d_pw_on = QCheckBox("Bật khóa")
        self.d_pw_on.setChecked(bool(st.get("pw_on", False)))
        self.d_pw = QLineEdit(st.get("pw", ""))
        self.d_pw.setMaxLength(6)
        self.d_pw.setInputMask("999999;_")
        self.d_pw.setFixedWidth(120)
        f.addRow("", self.d_pw_on)
        f.addRow("Mã 6 số", self.d_pw)
        b = button("Lưu vào vòng tay", "primary")
        b.clicked.connect(self._apply_password)
        self.needs_connection.append(b)
        s.add_footer(b)
        lay.addWidget(s)

        s = Section("Menu trên vòng tay", "Đánh dấu mục muốn hiện, kéo thả để đổi thứ tự. 15 mục đầu ở màn hình chính, "
                                                "phần còn lại vào mục Thêm. Bản web có sắp xếp đầy đủ hơn.")
        g = QGridLayout()
        g.setHorizontalSpacing(16)
        self.d_items = self._item_list(P.DISPLAY_ITEMS_ALL, st.get("display_items", P.DISPLAY_ITEMS_DEFAULT))
        self.d_shortcuts = self._item_list(P.SHORTCUTS_ALL, st.get("shortcuts", P.SHORTCUTS_DEFAULT))
        b1 = button("Lưu ứng dụng", "primary")
        b1.clicked.connect(lambda: self._apply_menu(False))
        b2 = button("Lưu phím tắt", "primary")
        b2.clicked.connect(lambda: self._apply_menu(True))
        self.needs_connection += [b1, b2]
        for i, (cap, lst, btn) in enumerate([("Ứng dụng (vuốt lên, xuống)", self.d_items, b1),
                                             ("Phím tắt (vuốt trái, phải)", self.d_shortcuts, b2)]):
            c = QLabel(cap)
            c.setObjectName("help")
            g.addWidget(c, 0, i)
            g.addWidget(lst, 1, i)
            g.addWidget(btn, 2, i, Qt.AlignRight)
        s.lay.addLayout(g)
        lay.addWidget(s)
        lay.addStretch(1)
        return page

    def _item_list(self, all_items: list[str], enabled: list[str]) -> QListWidget:
        lst = QListWidget()
        lst.setObjectName("items")
        lst.setDragDropMode(QAbstractItemView.InternalMove)
        lst.setDefaultDropAction(Qt.MoveAction)
        lst.setMinimumHeight(300)
        ordered = [k for k in enabled if k in all_items] + [k for k in all_items if k not in enabled]
        for k in ordered:
            it = QListWidgetItem(P.MENU_LABELS.get(k, k))
            it.setData(Qt.UserRole, k)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            it.setCheckState(Qt.Checked if k in enabled else Qt.Unchecked)
            lst.addItem(it)
        return lst

    @staticmethod
    def _checked_items(lst: QListWidget) -> list[str]:
        return [lst.item(i).data(Qt.UserRole) for i in range(lst.count()) if lst.item(i).checkState() == Qt.Checked]

    @staticmethod
    def _bind_schedule(cmb: QComboBox, scheduled_value, *edits: QWidget) -> None:
        def upd():
            on = cmb.currentData() == scheduled_value
            for e in edits:
                e.setEnabled(on)
        cmb.currentIndexChanged.connect(upd)
        upd()

    # ------------------------------------------------------------ trang: sức khỏe

    def _page_health(self) -> QWidget:
        page, lay = make_page("Sức khỏe")
        st = self.settings

        s = Section("Đo nhịp tim tự động", "Đo thường xuyên hơn cho dữ liệu chi tiết hơn nhưng tốn pin hơn.")
        f = s.form()
        self.h_interval = combo([("Tắt", 0), ("Mỗi phút", 1), ("5 phút", 5), ("10 phút", 10), ("30 phút", 30)], st.get("hr_interval", 0))
        self.h_sleep = QCheckBox("Đo chính xác hơn khi ngủ")
        self.h_sleep.setChecked(bool(st.get("hr_sleep", False)))
        self.h_activity = QCheckBox("Đo dày hơn khi đang vận động")
        self.h_activity.setChecked(bool(st.get("hr_activity", False)))
        self.h_alert = QCheckBox("Cảnh báo nhịp tim cao")
        self.h_alert.setChecked(bool(st.get("hr_alert", False)))
        self.h_threshold = combo([(f"{v} nhịp/phút", v) for v in P.HR_ALERT_THRESHOLDS], st.get("hr_threshold", 120))
        self.h_stress = QCheckBox("Theo dõi căng thẳng")
        self.h_stress.setChecked(bool(st.get("stress", False)))
        f.addRow("Chu kỳ đo", self.h_interval)
        f.addRow("", self.h_sleep)
        f.addRow("", self.h_activity)
        f.addRow("", row(self.h_alert, self.h_threshold))
        f.addRow("", self.h_stress)
        b = button("Lưu vào vòng tay", "primary")
        b.clicked.connect(self._apply_hr_settings)
        self.needs_connection.append(b)
        s.add_footer(b)
        lay.addWidget(s)

        s = Section("Nhắc vận động", "Vòng tay rung khi bạn ngồi yên quá lâu trong khung giờ đã chọn.")
        f = s.form()
        self.i_on = QCheckBox("Bật nhắc")
        self.i_on.setChecked(bool(st.get("idle_on", False)))
        self.i_minutes = QSpinBox()
        self.i_minutes.setRange(15, 180)
        self.i_minutes.setSingleStep(5)
        self.i_minutes.setSuffix(" phút")
        self.i_minutes.setValue(int(st.get("idle_minutes", 60)))
        self.i_from = time_edit(st.get("idle_from"), "08:00")
        self.i_to = time_edit(st.get("idle_to"), "22:00")
        self.i_lunch = QCheckBox("Không nhắc trong giờ nghỉ trưa")
        self.i_lunch.setChecked(bool(st.get("idle_lunch", True)))
        self.i_lunch_from = time_edit(st.get("idle_lunch_from"), "12:00")
        self.i_lunch_to = time_edit(st.get("idle_lunch_to"), "13:30")
        f.addRow("", self.i_on)
        f.addRow("Nhắc sau khi ngồi", self.i_minutes)
        f.addRow("Khung giờ", row(self.i_from, "đến", self.i_to))
        f.addRow("", self.i_lunch)
        f.addRow("Nghỉ trưa", row(self.i_lunch_from, "đến", self.i_lunch_to))
        b = button("Lưu vào vòng tay", "primary")
        b.clicked.connect(self._apply_idle)
        self.needs_connection.append(b)
        s.add_footer(b)
        lay.addWidget(s)

        s = Section("Không làm phiền", "Tắt rung thông báo và cuộc gọi trong khung giờ này.")
        f = s.form()
        self.n_mode = combo([("Tắt", P.DND_OFF), ("Tự động khi ngủ", P.DND_AUTO), ("Theo khung giờ", P.DND_SCHEDULED)], st.get("dnd", P.DND_OFF))
        self.n_from = time_edit(st.get("dnd_from"), "23:00")
        self.n_to = time_edit(st.get("dnd_to"), "07:00")
        self.n_lift = QCheckBox("Vẫn cho nâng tay sáng màn hình")
        self.n_lift.setChecked(bool(st.get("dnd_lift", False)))
        f.addRow("Chế độ", self.n_mode)
        f.addRow("Khung giờ", row(self.n_from, "đến", self.n_to))
        f.addRow("", self.n_lift)
        self._bind_schedule(self.n_mode, P.DND_SCHEDULED, self.n_from, self.n_to)
        b = button("Lưu vào vòng tay", "primary")
        b.clicked.connect(self._apply_dnd)
        self.needs_connection.append(b)
        s.add_footer(b)
        lay.addWidget(s)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------ trang: báo thức

    def _page_alarms(self) -> QWidget:
        page, lay = make_page("Báo thức", "Mi Band 6 có 10 ô báo thức. Ô không dùng sẽ bị xóa khỏi vòng tay khi lưu.")
        s = Section("Danh sách báo thức")
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(8)
        for col, cap in enumerate(["Ô", "Giờ", "Lặp lại (để trống = một lần)", "Bật"]):
            c = QLabel(cap)
            c.setObjectName("help")
            g.addWidget(c, 0, col)
        self.alarm_rows = []
        saved = {a.get("slot"): a for a in self.settings.get("alarms", [])}
        for i in range(P.MAX_ALARMS):
            a = saved.get(i, {})
            use = QCheckBox(f"Báo thức {i + 1}")
            use.setChecked(bool(a.get("in_use", False)))
            te = QTimeEdit()
            te.setDisplayFormat("HH:mm")
            te.setTime(QTime(int(a.get("hour", 7)), int(a.get("minute", 0))))
            days = QHBoxLayout()
            days.setSpacing(4)
            day_btns = []
            for d, lab in enumerate(WEEKDAYS):
                tb = QToolButton()
                tb.setObjectName("day")
                tb.setText(lab)
                tb.setCheckable(True)
                tb.setChecked(bool(int(a.get("days", 0)) & P.DAY_BITS[d]))
                days.addWidget(tb)
                day_btns.append(tb)
            days.addStretch(1)
            on = QCheckBox("")
            on.setChecked(bool(a.get("enabled", True)))
            g.addWidget(use, i + 1, 0)
            g.addWidget(te, i + 1, 1)
            g.addLayout(days, i + 1, 2)
            g.addWidget(on, i + 1, 3)
            r = {"use": use, "time": te, "days": day_btns, "on": on}
            self.alarm_rows.append(r)

            def upd(_=None, r=r):
                en = r["use"].isChecked()
                for w in [r["time"], r["on"], *r["days"]]:
                    w.setEnabled(en)
            use.toggled.connect(upd)
            upd()
        g.setColumnStretch(2, 1)
        s.lay.addLayout(g)
        rd = button("Đọc từ vòng tay")
        rd.clicked.connect(self._read_alarms)
        wr = button("Lưu vào vòng tay", "primary")
        wr.clicked.connect(self._apply_alarms)
        self.needs_connection += [rd, wr]
        s.add_footer(rd, wr)
        lay.addWidget(s)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------ trang: thông báo

    def _page_tools(self) -> QWidget:
        page, lay = make_page("Thông báo và tìm")
        s = Section("Gửi thông báo", "Hiện một thông báo trên vòng tay, kèm biểu tượng và tên ứng dụng.")
        f = s.form()
        self.t_icon = combo([(k, v) for k, v in P.NOTIFICATION_ICONS.items()])
        self.t_app = QLineEdit("Máy tính")
        self.t_title = QLineEdit()
        self.t_title.setPlaceholderText("Tiêu đề hoặc người gửi")
        self.t_body = QPlainTextEdit()
        self.t_body.setPlaceholderText("Nội dung thông báo")
        self.t_body.setFixedHeight(90)
        for w in (self.t_app, self.t_title):
            w.setMinimumWidth(360)
        self.t_body.setMinimumWidth(360)
        f.addRow("Biểu tượng", self.t_icon)
        f.addRow("Ứng dụng", self.t_app)
        f.addRow("Tiêu đề", self.t_title)
        f.addRow("Nội dung", self.t_body)
        b = button("Gửi thông báo", "primary")
        b.clicked.connect(self._send_notification)
        self.needs_connection.append(b)
        s.add_footer(b)
        lay.addWidget(s)

        s = Section("Cuộc gọi đến", "Giả lập một cuộc gọi đến để thử rung và màn hình cuộc gọi.")
        f = s.form()
        self.t_caller = QLineEdit("Mẹ")
        self.t_caller.setMinimumWidth(260)
        f.addRow("Người gọi", self.t_caller)
        b1 = button("Gửi cuộc gọi", "primary")
        b1.clicked.connect(lambda: self._run("Gửi cuộc gọi", lambda: self.band.incoming_call(self.t_caller.text() or "Không rõ")))
        b2 = button("Kết thúc cuộc gọi")
        b2.clicked.connect(lambda: self._run("Kết thúc cuộc gọi", lambda: self.band.stop_call()))
        self.needs_connection += [b1, b2]
        s.add_footer(b2, b1)
        lay.addWidget(s)

        s = Section("Tìm vòng tay", "Vòng tay rung liên tục tối đa 30 giây, hoặc đến khi bạn bấm Dừng rung hay từ chối trên vòng.")
        b1 = button("Rung vòng tay", "primary")
        b1.clicked.connect(lambda: self._run("Rung vòng tay", lambda: self.band.find_band(True)))
        b2 = button("Dừng rung")
        b2.clicked.connect(lambda: self._run("Dừng rung", lambda: self.band.find_band(False)))
        self.needs_connection += [b1, b2]
        s.add_footer(b2, b1)
        lay.addWidget(s)

        s = Section("Tìm máy tính từ vòng tay")
        self.t_find_sound = QCheckBox("Phát âm thanh khi bấm Tìm điện thoại trên vòng tay")
        self.t_find_sound.setChecked(bool(self.settings.get("find_sound", True)))
        self.t_find_sound.toggled.connect(lambda on: self._save_settings(find_sound=on))
        s.lay.addWidget(self.t_find_sound)
        lay.addWidget(s)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------ trang: nhật ký

    def _page_log(self) -> QWidget:
        page, lay = make_page("Nhật ký", "Mọi gói tin Bluetooth gửi (→) và nhận (←). Hữu ích khi một cài đặt không có tác dụng.")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        mono.setPointSize(11)
        self.log_view.setFont(mono)
        self.log_view.setMinimumHeight(460)
        lay.addWidget(self.log_view, 1)
        clear = button("Xóa")
        clear.clicked.connect(self.log_view.clear)
        save = button("Lưu nhật ký…")
        save.clicked.connect(self._save_log)
        lay.addLayout(row(save, clear))
        return page

    # ============================================================ hành vi

    def _log(self, msg: str) -> None:
        self.log_view.appendPlainText(f"{dt.datetime.now():%H:%M:%S}  {msg}")

    def _toast(self, msg: str, error: bool = False) -> None:
        self.statusBar().setStyleSheet(f"color: {DANGER};" if error else "")
        self.statusBar().showMessage(msg, 8000)

    def _set_connected(self, on: bool, busy: bool = False) -> None:
        for w in self.needs_connection:
            w.setEnabled(on)
        self.btn_connect.setEnabled(not on and not busy)
        self.btn_disconnect.setEnabled(on)
        self.btn_scan.setEnabled(not busy)
        self.preview.connected = on
        self.preview.busy = busy
        self.preview.update()
        if not on:
            self.btn_hr_live.blockSignals(True)
            self.btn_hr_live.setChecked(False)
            self.btn_hr_live.blockSignals(False)

    def _run(self, what: str, make_coro, ok_msg: str | None = None, on_ok=None) -> None:
        if not self.band or not self.band.is_connected:
            self._toast("Chưa kết nối vòng tay.", True)
            return

        def ok(res):
            self._toast(ok_msg or f"Xong: {what.lower()}.")
            if on_ok:
                on_ok(res)

        def bad(e):
            self._toast(f"{what} không thành công: {e}", True)

        self.worker.submit(make_coro, ok, bad)

    def _save_settings(self, **kw) -> None:
        self.settings.update(kw)
        self.store.save()

    # ------------------------------------------------------------ kết nối

    def _scan(self) -> None:
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("Đang quét…")
        self.tbl.setRowCount(0)
        show_all = self.chk_all.isChecked()

        def done(results):
            self.btn_scan.setEnabled(True)
            self.btn_scan.setText("Quét lại")
            self.scan_results = results
            self.tbl.setRowCount(len(results))
            for i, (dev, rssi, is_band, name) in enumerate(results):
                self.tbl.setItem(i, 0, QTableWidgetItem(name or "(không tên)"))
                self.tbl.setItem(i, 1, QTableWidgetItem(dev.address))
                self.tbl.setItem(i, 2, QTableWidgetItem(f"{rssi} dBm" if rssi is not None else "—"))
            if results:
                self.tbl.selectRow(0)
                self._toast(f"Tìm thấy {len(results)} thiết bị.")
            else:
                self._toast("Không thấy Mi Band 6. Tắt Bluetooth trên điện thoại, đánh thức vòng tay rồi quét lại.", True)

        def fail(e):
            self.btn_scan.setEnabled(True)
            self.btn_scan.setText("Quét")
            self._toast(f"Không quét được Bluetooth: {e}. Kiểm tra Bluetooth đã bật và đã cấp quyền Bluetooth cho Terminal.", True)

        if self.demo:
            from ..simulator import DemoDevice

            async def fake_scan():
                await asyncio.sleep(1.2)
                return [(DemoDevice(), -54, True, DemoDevice.name)]

            self.worker.submit(fake_scan, done, fail)
            return
        self.worker.submit(lambda: scan(8.0, show_all), done, fail)

    def _on_pick_device(self) -> None:
        rows = self.tbl.selectionModel().selectedRows()
        if not rows:
            return
        dev, _, _, name = self.scan_results[rows[0].row()]
        self.selected_device = dev
        self.selected_address = dev.address
        self.lbl_addr.setText(f"{name or 'Thiết bị'}  ·  {dev.address}")
        saved = self.store.data["devices"].get(dev.address)
        if saved and saved.get("auth_key"):
            self.key_edit.setText(saved["auth_key"])

    def _connect(self) -> None:
        if not self.selected_address:
            self._toast("Hãy quét và chọn vòng tay trước.", True)
            return
        try:
            key = P.parse_auth_key(self.key_edit.text())
        except ValueError as e:
            self.lbl_conn.setText(str(e))
            self.lbl_conn.setStyleSheet(f"color: {DANGER};")
            return
        target = self.selected_device or self.selected_address
        name = getattr(self.selected_device, "name", None) or self.store.device(self.selected_address).get("name") or P.MI_BAND6_NAME
        proto = self.cmb_proto.currentData()
        self._set_connected(False, busy=True)
        self.lbl_conn.setStyleSheet("")
        self.lbl_conn.setText("Đang kết nối và xác thực…")
        self.device_line.setText("Đang kết nối…")

        async def go():
            if self.band:
                await self.band.disconnect()
            client = None
            if self.demo:
                from ..simulator import FakeBand

                client = FakeBand(key, "both")
                client.hr_delay = 6.0
            self.band = MiBand6(target, key, proto, on_event=self.worker.emit_event, log=self.worker.emit_log,
                                name=name, client=client)
            return await self.band.connect()

        def ok(used):
            self._set_connected(True)
            self.store.remember_device(self.selected_address, name, self.key_edit.text().strip(), used)
            label = "kiểu cũ" if used == PROTOCOL_CLASSIC else "kiểu mới (2021)"
            self.lbl_conn.setText(f"Đã kết nối, xác thực {label}. Giờ trên vòng tay đã được đồng bộ.")
            self.device_line.setText(name)
            self.info_labels["protocol"].setText(label.capitalize())
            self._toast("Đã kết nối vòng tay.")
            self.nav.setCurrentRow(1)
            self._refresh()
            self.worker.submit(lambda: self.band.request_alarms(), None, None)

        def fail(e):
            self._set_connected(False)
            self.device_line.setText("Chưa kết nối")
            self.lbl_conn.setText(f"Không kết nối được: {e}")
            self.lbl_conn.setStyleSheet(f"color: {DANGER};")

        self.worker.submit(go, ok, fail)

    def _disconnect(self) -> None:
        if not self.band:
            return
        band = self.band
        self.worker.submit(band.disconnect, lambda _: self._after_disconnect("Đã ngắt kết nối."))

    def _after_disconnect(self, msg: str) -> None:
        self._set_connected(False)
        self.device_line.setText("Chưa kết nối")
        self.lbl_conn.setStyleSheet("")
        self.lbl_conn.setText(msg)
        self._toast(msg)

    def _refresh(self) -> None:
        self._run("Đọc dữ liệu", lambda: self.band.refresh_all(), "Đã đọc dữ liệu mới nhất từ vòng tay.")

    def _sync_time(self) -> None:
        async def go():
            await self.band.set_time()
            return await self.band.read_time()
        self._run("Đồng bộ giờ", go, "Đã đồng bộ giờ với máy tính.")

    # ------------------------------------------------------------ sự kiện từ vòng

    def _on_band_event(self, kind: str, data) -> None:
        if kind == "battery":
            self.preview.battery, self.preview.charging = data.level, data.charging
            self.preview.update()
            self.lbl_bat.setText(f"{data.level}%")
            notes = ["Đang sạc"] if data.charging else []
            if data.last_charge:
                notes.append(f"Sạc lần gần nhất {data.last_charge:%d/%m/%Y %H:%M}")
            self.lbl_bat_note.setText(". ".join(notes))
        elif kind == "activity":
            self.preview.steps = data.steps
            self.preview.update()
            self.lbl_steps.setText(fmt_int(data.steps))
            self.bar_goal.setValue(min(data.steps, self.bar_goal.maximum()))
            if data.meters is not None:
                self.lbl_dist.setText(f"{data.meters / 1000:.2f}".replace(".", ","))
            if data.calories is not None:
                self.lbl_cal.setText(fmt_int(data.calories))
        elif kind == "heart_rate":
            self.preview.hr = data
            self.preview.update()
            self.lbl_hr.setText(f"{data} nhịp/phút")
        elif kind == "device_info":
            self.info_labels["name"].setText(data.name or "—")
            self.info_labels["firmware"].setText(data.firmware or "—")
            self.info_labels["hardware"].setText(data.hardware or "—")
            self.info_labels["serial"].setText(data.serial or "—")
        elif kind == "band_time":
            self.info_labels["band_time"].setText(data.strftime("%H:%M:%S  %d/%m/%Y") if data else "—")
        elif kind == "alarms":
            self._fill_alarms(data)
        elif kind == "device_event":
            label = P.DEVICE_EVENTS.get(data, f"Sự kiện {data:#04x}")
            self._log(f"Sự kiện: {label}")
            if data == P.EVENT_FIND_PHONE_START:
                self._start_find_phone()
            elif data == P.EVENT_FIND_PHONE_STOP:
                self._stop_find_phone()
        elif kind == "disconnected":
            self._stop_find_phone()
            self._after_disconnect("Vòng tay đã ngắt kết nối. Bấm Kết nối để nối lại.")
            self.nav.setCurrentRow(0)

    def _update_goal_label(self) -> None:
        goal = int(self.profile.get("goal", 8000))
        self.lbl_goal.setText(f"bước, mục tiêu {fmt_int(goal)}")
        self.bar_goal.setMaximum(goal)
        self.preview.goal = goal

    # ------------------------------------------------------------ tìm điện thoại

    def _start_find_phone(self) -> None:
        if not self.t_find_sound.isChecked():
            return
        self._stop_find_phone()
        t = QTimer(self)
        t.timeout.connect(self._beep)
        t.start(1500)
        QTimer.singleShot(30000, self._stop_find_phone)
        self._find_phone_timer = t
        self._beep()
        box = QMessageBox(QMessageBox.Information, "Vòng tay đang tìm máy tính", "Bạn vừa bấm Tìm điện thoại trên vòng tay.", QMessageBox.Ok, self)
        box.button(QMessageBox.Ok).setText("Đã thấy")
        box.finished.connect(lambda _: self._stop_find_phone())
        box.show()
        self._find_phone_box = box
        self.raise_()
        self.activateWindow()

    def _beep(self) -> None:
        if sys.platform == "darwin":
            try:
                subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"])
                return
            except OSError:
                pass
        QApplication.beep()

    def _stop_find_phone(self) -> None:
        if self._find_phone_timer:
            self._find_phone_timer.stop()
            self._find_phone_timer = None
        if self._find_phone_box:
            box, self._find_phone_box = self._find_phone_box, None
            box.close()

    # ------------------------------------------------------------ áp dụng cài đặt

    def _apply_profile(self) -> None:
        qd = self.p_birth.date()
        birth = dt.date(qd.year(), qd.month(), qd.day())
        alias = self.p_alias.text().strip() or "user"
        vals = dict(alias=alias, birth=birth.isoformat(), gender=self.p_gender.currentData(),
                    height=self.p_height.value(), weight=self.p_weight.value())
        self._run(
            "Lưu hồ sơ",
            lambda: self.band.set_user_info(alias, birth, vals["gender"], vals["height"], vals["weight"]),
            "Đã lưu hồ sơ vào vòng tay.",
            lambda _: (self.profile.update(vals), self.store.save()),
        )

    def _apply_goal(self) -> None:
        goal, notify = self.p_goal.value(), self.p_goal_notify.isChecked()

        async def go():
            await self.band.set_step_goal(goal)
            await self.band.write_config(P.goal_notification(notify))

        def saved(_):
            self.profile.update(goal=goal, goal_notify=notify)
            self.store.save()
            self._update_goal_label()

        self._run("Lưu mục tiêu", go, "Đã lưu mục tiêu vào vòng tay.", saved)

    def _apply_wear(self) -> None:
        left = self.p_left.isChecked()
        self._run("Lưu tay đeo", lambda: self.band.set_wear_location(left), "Đã lưu tay đeo vào vòng tay.",
                  lambda _: (self.profile.update(wear_left=left), self.store.save()))

    def _apply_formats(self) -> None:
        lang, h24, datef, metric = (self.d_lang.currentData(), self.d_24h.currentData(),
                                    self.d_date.currentData(), self.d_metric.currentData())

        async def go():
            await self.band.write_config(P.language(lang))
            await self.band.write_config(P.time_format_24h(h24))
            await self.band.write_config(P.date_format(datef))
            await self.band.write_config(P.distance_unit(metric))

        self._run("Lưu ngôn ngữ và định dạng", go, "Đã lưu ngôn ngữ và định dạng vào vòng tay.",
                  lambda _: self._save_settings(language=lang, time_24h=h24, date_format=datef, metric=metric))

    def _apply_lift(self) -> None:
        mode, a, b, sens = self.d_lift.currentData(), self.d_lift_from.time(), self.d_lift_to.time(), self.d_lift_sens.currentData()

        async def go():
            await self.band.write_config(P.lift_wrist(mode, qtime(a), qtime(b)))
            await self.band.write_config(P.lift_wrist_sensitive(sens))

        self._run("Lưu nâng tay", go, "Đã lưu cài đặt nâng tay vào vòng tay.",
                  lambda _: self._save_settings(lift=mode, lift_from=a.toString("HH:mm"), lift_to=b.toString("HH:mm"), lift_sensitive=sens))

    def _apply_night(self) -> None:
        mode, a, b = self.d_night.currentData(), self.d_night_from.time(), self.d_night_to.time()
        self._run("Lưu chế độ ban đêm", lambda: self.band.write_config(P.night_mode(mode, qtime(a), qtime(b))),
                  "Đã lưu chế độ ban đêm vào vòng tay.",
                  lambda _: self._save_settings(night=mode, night_from=a.toString("HH:mm"), night_to=b.toString("HH:mm")))

    def _apply_password(self) -> None:
        on, pin = self.d_pw_on.isChecked(), self.d_pw.text().replace("_", "")
        try:
            cmd = P.password(on, pin)
        except ValueError as e:
            self._toast(str(e), True)
            return
        self._run("Lưu mật khẩu", lambda: self.band.write_config(cmd), "Đã lưu mật khẩu vào vòng tay.",
                  lambda _: self._save_settings(pw_on=on, pw=pin))

    def _apply_menu(self, shortcuts: bool) -> None:
        lst = self.d_shortcuts if shortcuts else self.d_items
        items = self._checked_items(lst)
        if shortcuts:
            self._run("Lưu phím tắt", lambda: self.band.set_shortcuts(items), "Đã lưu phím tắt vào vòng tay.",
                      lambda _: self._save_settings(shortcuts=items))
        else:
            main, more = P.arrange_display_items(items, [])
            self._run("Lưu menu ứng dụng", lambda: self.band.set_display_items(main, more), "Đã lưu menu ứng dụng vào vòng tay.",
                      lambda _: self._save_settings(display_items=items))

    def _apply_hr_settings(self) -> None:
        iv, sl, ac, al, th, stv = (self.h_interval.currentData(), self.h_sleep.isChecked(), self.h_activity.isChecked(),
                                   self.h_alert.isChecked(), self.h_threshold.currentData(), self.h_stress.isChecked())

        async def go():
            await self.band.set_hr_interval(iv)
            await self.band.set_hr_sleep_assist(sl)
            await self.band.write_config(P.hr_activity_monitoring(ac))
            await self.band.write_config(P.hr_alert(al, th))
            await self.band.write_config(P.stress_monitoring(stv))

        self._run("Lưu cài đặt nhịp tim", go, "Đã lưu cài đặt nhịp tim vào vòng tay.",
                  lambda _: self._save_settings(hr_interval=iv, hr_sleep=sl, hr_activity=ac, hr_alert=al, hr_threshold=th, stress=stv))

    def _apply_idle(self) -> None:
        vals = dict(idle_on=self.i_on.isChecked(), idle_minutes=self.i_minutes.value(),
                    idle_from=self.i_from.time().toString("HH:mm"), idle_to=self.i_to.time().toString("HH:mm"),
                    idle_lunch=self.i_lunch.isChecked(), idle_lunch_from=self.i_lunch_from.time().toString("HH:mm"),
                    idle_lunch_to=self.i_lunch_to.time().toString("HH:mm"))
        cmd = P.inactivity_warnings(vals["idle_on"], vals["idle_minutes"], qtime(self.i_from.time()), qtime(self.i_to.time()),
                                    vals["idle_lunch"], qtime(self.i_lunch_from.time()), qtime(self.i_lunch_to.time()))
        self._run("Lưu nhắc vận động", lambda: self.band.write_config(cmd), "Đã lưu nhắc vận động vào vòng tay.",
                  lambda _: self._save_settings(**vals))

    def _apply_dnd(self) -> None:
        mode, a, b, lift = self.n_mode.currentData(), self.n_from.time(), self.n_to.time(), self.n_lift.isChecked()
        self._run("Lưu Không làm phiền", lambda: self.band.write_config(P.do_not_disturb(mode, qtime(a), qtime(b), lift)),
                  "Đã lưu Không làm phiền vào vòng tay.",
                  lambda _: self._save_settings(dnd=mode, dnd_from=a.toString("HH:mm"), dnd_to=b.toString("HH:mm"), dnd_lift=lift))

    # ------------------------------------------------------------ báo thức

    def _collect_alarms(self) -> list[P.Alarm]:
        out = []
        for i, r in enumerate(self.alarm_rows):
            days = sum(P.DAY_BITS[d] for d, b in enumerate(r["days"]) if b.isChecked())
            t = r["time"].time()
            out.append(P.Alarm(slot=i, enabled=r["on"].isChecked(), hour=t.hour(), minute=t.minute(),
                               days=days, in_use=r["use"].isChecked()))
        return out

    def _fill_alarms(self, alarms: list[P.Alarm]) -> None:
        by_slot = {a.slot: a for a in alarms}
        for i, r in enumerate(self.alarm_rows):
            a = by_slot.get(i)
            r["use"].setChecked(a is not None)
            if a:
                r["time"].setTime(QTime(a.hour, a.minute))
                r["on"].setChecked(a.enabled)
                for d, b in enumerate(r["days"]):
                    b.setChecked(bool(a.days & P.DAY_BITS[d]))

    def _read_alarms(self) -> None:
        self._run("Đọc báo thức", lambda: self.band.request_alarms(), "Đã đọc báo thức từ vòng tay.")

    def _apply_alarms(self) -> None:
        alarms = self._collect_alarms()

        async def go():
            for a in alarms:
                await self.band.set_alarm(a)

        self._run("Lưu báo thức", go, "Đã lưu báo thức vào vòng tay.",
                  lambda _: self._save_settings(alarms=[a.__dict__ for a in alarms]))

    # ------------------------------------------------------------ công cụ

    def _measure_hr(self) -> None:
        self.btn_hr.setEnabled(False)
        self.lbl_hr_note.setText("Đang đo, giữ yên tay khoảng 15–30 giây…")

        def ok(bpm):
            self.btn_hr.setEnabled(True)
            self.lbl_hr_note.setText(f"Đo lúc {dt.datetime.now():%H:%M}.")

        def bad(e):
            self.btn_hr.setEnabled(True)
            self.lbl_hr_note.setText("Không đo được. Đeo vòng sát cổ tay hơn rồi thử lại.")

        if self.band and self.band.is_connected:
            self.worker.submit(lambda: self.band.measure_heart_rate(), ok, bad)

    def _toggle_hr_live(self, on: bool) -> None:
        self.lbl_hr_note.setText("Đang theo dõi liên tục." if on else "Đã dừng theo dõi liên tục.")
        self._run("Theo dõi nhịp tim", lambda: self.band.realtime_heart_rate(on),
                  "Đang theo dõi nhịp tim liên tục." if on else "Đã dừng theo dõi nhịp tim.")

    def _send_notification(self) -> None:
        title, body, app, icon = self.t_title.text(), self.t_body.toPlainText(), self.t_app.text(), self.t_icon.currentData()
        if not (title or body):
            self._toast("Nhập tiêu đề hoặc nội dung trước khi gửi.", True)
            return
        self._run("Gửi thông báo", lambda: self.band.send_notification(title, body, app or "Máy tính", icon), "Đã gửi thông báo.")

    def _save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Lưu nhật ký", f"miband6-{dt.datetime.now():%Y%m%d-%H%M}.txt", "Văn bản (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.log_view.toPlainText())
            self._toast("Đã lưu nhật ký.")

    def _show_key_help(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Cách lấy auth key")
        box.setTextFormat(Qt.RichText)
        box.setText(
            "<p><b>Auth key</b> là mã 32 ký tự hex được tạo khi bạn ghép đôi vòng tay bằng app của hãng. "
            "Không có mã này thì vòng tay sẽ từ chối kết nối.</p>"
            "<p><b>Nếu bạn ghép đôi bằng Mi Fitness</b> (mã nằm trên máy chủ Xiaomi), chạy trong thư mục ứng dụng:</p>"
            "<pre>uv run tools/mifitness_key.py</pre>"
            "<p>Quét mã QR hiện ra bằng camera điện thoại (hoặc mở đường dẫn trong trình duyệt) và đăng nhập "
            "tài khoản Xiaomi. Script in key của Mi Smart Band 6 và tự chép vào clipboard.</p>"
            "<p><b>iPhone, không cần đăng nhập:</b> trong app Tệp, mở Trên iPhone → Mi Fitness → MHWCahe → "
            "thư mục số → VirtualDevice_registerList, AirDrop <code>manifest.sqlite</code> và "
            "<code>manifest.sqlite-wal</code> sang Mac rồi chạy "
            "<code>uv run tools/mifitness_key.py --file ~/Downloads/manifest.sqlite ~/Downloads/manifest.sqlite-wal</code>.</p>"
            "<p>Điện thoại Android còn một cách khác: Mi Fitness ghi mã vào tệp nhật ký, ở trường "
            "<code>huamiAuthKey</code> trong thư mục <code>Android/data/com.xiaomi.wearable/files/log/</code>.</p>"
            "<p><b>Nếu bạn ghép đôi bằng Zepp Life:</b> dùng huami-token: "
            "<code>uvx --from git+https://codeberg.org/argrento/huami-token huami-token --method amazfit "
            "--email EMAIL --password MẬT_KHẨU --bt_keys</code>.</p>"
            f"<p>Các cách khác có trong <a href='{GUIDE_URL}'>hướng dẫn của Gadgetbridge</a>.</p>"
            "<p><b>Lưu ý:</b> đừng hủy ghép đôi vòng tay trong app của hãng và đừng khôi phục cài đặt gốc vòng tay, "
            "vì làm vậy mã cũ sẽ mất hiệu lực.</p>"
        )
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.exec()

    def closeEvent(self, ev) -> None:
        band = self.band

        async def final():
            if band and band.is_connected:
                await band.disconnect()

        self.worker.shutdown(final)
        super().closeEvent(ev)


def setup_app(argv: list[str]) -> QApplication:
    app = QApplication(argv)
    app.setApplicationName("Quản lý Mi Band 6")
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in [
        (QPalette.Window, PAPER),
        (QPalette.Base, SURFACE),
        (QPalette.AlternateBase, PAPER),
        (QPalette.Text, INK),
        (QPalette.WindowText, INK),
        (QPalette.ButtonText, INK),
        (QPalette.Button, SURFACE),
        (QPalette.Highlight, ACCENT),
        (QPalette.HighlightedText, "#FFFFFF"),
        (QPalette.ToolTipBase, SURFACE),
        (QPalette.ToolTipText, INK),
        (QPalette.PlaceholderText, "#9AA29D"),
        (QPalette.Link, ACCENT),
    ]:
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(build_style())
    return app


def main() -> None:
    demo = "--demo" in sys.argv
    app = setup_app([a for a in sys.argv if a != "--demo"])
    w = MainWindow(demo=demo)
    if demo:
        w.key_edit.setText(os.urandom(16).hex())
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
