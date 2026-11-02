"""Kiểm thử khói cho giao diện: chạy chế độ xem thử (vòng tay giả lập) không cần màn hình."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop  # noqa: E402

from miband6.gui import app as A  # noqa: E402


def _pump(qapp, until, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents(QEventLoop.AllEvents, 50)
        if until():
            return True
        time.sleep(0.02)
    return False


def test_demo_connect_and_apply_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "demo_store_path", lambda: tmp_path / "cfg.json")
    qapp = A.QApplication.instance() or A.setup_app(["test"])
    w = A.MainWindow(demo=True)
    w.key_edit.setText("8f2b1c0a77d94e3fa5c1b2e3d4f50617")
    w.show()
    w._scan()
    assert _pump(qapp, lambda: w.tbl.rowCount() == 1)
    w._connect()
    assert _pump(qapp, lambda: w.band is not None and w.band.authenticated)
    assert _pump(qapp, lambda: w.lbl_steps.text() == "6.543")
    assert w.lbl_bat.text() == "87%"
    assert w.info_labels["firmware"].text() == "1.0.6.16"
    # báo thức đọc từ vòng tay được điền vào bảng
    assert _pump(qapp, lambda: w.alarm_rows[0]["use"].isChecked() and w.alarm_rows[2]["use"].isChecked())

    band = w.band._client
    w.d_lang.setCurrentIndex(w.d_lang.findData("vi_VN"))
    w._apply_formats()
    assert _pump(qapp, lambda: A.P.language("vi_VN") in band.config_commands)
    w._apply_dnd()
    w._apply_alarms()
    assert _pump(qapp, lambda: sum(1 for c in band.config_commands if c[0] == 0x02) == A.P.MAX_ALARMS)
    w._disconnect()
    assert _pump(qapp, lambda: not w.btn_disconnect.isEnabled())
    w.close()
