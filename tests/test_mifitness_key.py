"""Kiểm thử tools/mifitness_key.py (không gọi mạng)."""

import base64
import json
import plistlib
import runpy
import shutil
import sqlite3
from pathlib import Path
from plistlib import UID

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT / "tools" / "mifitness_key.py"))


def test_rc4_known_vector():
    assert M["rc4"](b"Key", b"Plaintext", drop=0).hex() == "bbf316e8d940af0ad3"
    s = M["RC4Stream"](b"Key")
    assert s.crypt(b"ab") + s.crypt(b"c") == M["rc4"](b"Key", b"abc")


def test_request_params_and_response_roundtrip():
    ssec = base64.b64encode(b"s" * 16).decode()
    nonce = M["make_nonce"]()
    plain = {"data": '{"page_size":50,"status":1}'}
    st = M["stream_params"](M["HEALTH_PATH"], plain, ssec, nonce)
    assert set(st) == {"data", "rc4_hash__", "signature", "_nonce"}
    mh = M["mihome_params"](M["HEALTH_PATH"], plain, ssec, nonce)
    assert set(mh) == {"data", "rc4_hash__", "signature", "ssecurity", "_nonce"}
    # cả hai kiểu đều giải ra được dữ liệu gốc
    key = base64.b64decode(M["signed_nonce"](ssec, nonce))
    assert M["rc4"](key, base64.b64decode(mh["data"])).decode() == plain["data"]
    assert M["RC4Stream"](key).crypt(base64.b64decode(st["data"])).decode() == plain["data"]
    body = {"code": 0, "result": {"list": [{"name": "Mi Smart Band 6", "detail": json.dumps(
        {"mac": "C8:0F:10:AA:BB:CC", "auth_key": "8F2B1C0A77D94E3FA5C1B2E3D4F50617"})}]}}
    enc = base64.b64encode(M["rc4"](key, json.dumps(body).encode())).decode()
    res = M["decrypt_body"](enc, ssec, nonce)
    devs = M["parse_source_list"](res)
    assert devs == [{"name": "Mi Smart Band 6", "model": "", "mac": "C8:0F:10:AA:BB:CC",
                     "key": "8f2b1c0a77d94e3fa5c1b2e3d4f50617", "field": "auth_key"}]
    assert M["is_band6"](devs[0])


def _archive(devices):
    objs = ["$null"]

    def add(o):
        objs.append(o)
        return UID(len(objs) - 1)

    cls = add({"$classname": "MHWVirtualDevice", "$classes": ["MHWVirtualDevice", "NSObject"]})
    arr_cls = add({"$classname": "NSArray", "$classes": ["NSArray", "NSObject"]})
    refs = [add({"$class": cls, **{k: add(v) for k, v in d.items()}}) for d in devices]
    arr = add({"NS.objects": refs, "$class": arr_cls})
    top = add({"list": arr, "$class": cls})
    return plistlib.dumps({"$version": 100000, "$archiver": "NSKeyedArchiver", "$top": {"root": top},
                           "$objects": objs}, fmt=plistlib.FMT_BINARY)


SCHEMA = ("CREATE TABLE manifest (key text, filename text, size integer, inline_data blob, "
          "modification_time integer, last_access_time integer, extended_data blob, primary key(key))")


def test_iphone_plain_sqlite_with_data_file(tmp_path):
    """manifest.sqlite thường; một danh sách nằm inline, một danh sách nằm trong tệp data/."""
    folder = tmp_path / "Mi Fitness/MHWCahe/123/VirtualDevice_registerList"
    (folder / "data").mkdir(parents=True)
    con = sqlite3.connect(folder / "manifest.sqlite")
    con.execute(SCHEMA)
    inline = _archive([{"name": "Mi Smart Band 6", "mac": "C8:0F:10:01:02:03", "encryptKey": "0x" + "ab" * 16},
                       {"name": "Phone", "encryptKey": "short"}])
    con.execute("insert into manifest values (?,?,?,?,?,?,?)", ("registerList_sg", None, 0, inline, 0, 0, None))
    con.execute("insert into manifest values (?,?,?,?,?,?,?)", ("registerList_de", "f1", 0, None, 0, 0, None))
    con.execute("insert into manifest values (?,?,?,?,?,?,?)", ("other", None, 1, b"x", 0, 0, None))
    con.commit()
    con.close()
    (folder / "data" / "f1").write_bytes(_archive([{"name": "Redmi Watch", "mac": "11:22:33:44:55:66",
                                                    "encryptKey": "cd" * 16}]))
    devs, notes = M["keys_from_files"]([str(tmp_path / "Mi Fitness")])
    assert not notes
    assert [(d["name"], d["key"]) for d in devs] == [("Mi Smart Band 6", "ab" * 16), ("Redmi Watch", "cd" * 16)]


def test_iphone_wal_only(tmp_path):
    """Mi Fitness giữ cả CSDL trong tệp -wal; đọc được khi chỉ có tệp -wal."""
    db = tmp_path / "manifest.sqlite"
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute(SCHEMA)
    blob = _archive([{"name": "Mi Smart Band 6", "model": "hlth.band.mb6", "mac": "C8:0F:10:01:02:03",
                      "encryptKey": "AABBCCDDEEFF00112233445566778899"}])
    con.execute("insert into manifest values (?,?,?,?,?,?,?)", ("registerList_sg", None, len(blob), blob, 0, 0, None))
    con.commit()
    only = tmp_path / "copy"
    only.mkdir()
    shutil.copy(str(db) + "-wal", only / "manifest.sqlite-wal")
    con.close()
    devs, _ = M["keys_from_files"]([str(only / "manifest.sqlite-wal")])
    assert [(d["name"], d["mac"], d["key"]) for d in devs] == [
        ("Mi Smart Band 6", "C8:0F:10:01:02:03", "aabbccddeeff00112233445566778899")]
    assert M["is_band6"](devs[0])
