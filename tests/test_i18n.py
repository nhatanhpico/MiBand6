import json
import re

import pytest

from miband6 import i18n
from miband6.i18n import set_lang, tr

import i18n_strings

CATALOG = json.loads(i18n.CATALOG_PATH.read_text("utf-8"))


@pytest.fixture(autouse=True)
def _reset_lang():
    yield
    set_lang("vi")


@pytest.mark.parametrize("group", ["html", "js", "py", "labels"])
def test_every_string_has_english(group):
    strings = i18n_strings.all_strings()[group]
    assert strings, group
    missing = sorted(s for s in strings if s not in CATALOG)
    assert not missing, f"Thiếu bản dịch tiếng Anh ({group}): {missing}"


def test_catalog_has_no_stale_entries():
    used = set().union(*i18n_strings.all_strings().values())
    assert not sorted(set(CATALOG) - used)


def test_placeholders_match():
    for src, en in CATALOG.items():
        ph = lambda s: sorted(re.findall(r"\{[^}]*\}", s))  # noqa: E731
        assert ph(src) == ph(en), src
        assert en.strip(), src


def test_tr_switches_language():
    assert tr("Đã lưu hồ sơ vào vòng tay.") == "Đã lưu hồ sơ vào vòng tay."
    assert set_lang("en") == "en"
    assert tr("Đã lưu hồ sơ vào vòng tay.") == "Profile saved to the band."
    assert tr("Tìm thấy {n} thiết bị.", n=3) == "Devices found: 3."
    assert tr("chuỗi chưa có", ) == "chuỗi chưa có"
    assert set_lang("fr") == "vi"
