#!/usr/bin/env python3
"""Lấy auth key của Mi Band 6 đã ghép đôi bằng Mi Fitness (tài khoản Xiaomi).

Cách 1, qua máy chủ Xiaomi (mặc định):
    uv run tools/mifitness_key.py              # đăng nhập bằng mã QR / trình duyệt
    uv run tools/mifitness_key.py --password   # đăng nhập bằng tài khoản + mật khẩu
    uv run tools/mifitness_key.py --fresh      # bỏ phiên đăng nhập đã lưu, đăng nhập lại

Cách 2, đọc tệp của Mi Fitness trên iPhone (không cần đăng nhập):
    Tệp (Files) → Trên iPhone → Mi Fitness → MHWCahe → <thư mục số> → VirtualDevice_registerList
    AirDrop manifest.sqlite và manifest.sqlite-wal sang máy Mac, rồi:
    uv run tools/mifitness_key.py --file ~/Downloads/manifest.sqlite ~/Downloads/manifest.sqlite-wal

Script chỉ đọc; không thay đổi gì trên tài khoản hay vòng tay.
Tham khảo: huami-token (MIT), Xiaomi-cloud-tokens-extractor (MIT), miband-hack.
"""

from __future__ import annotations

import argparse
import getpass
import os
import plistlib
import re
import sqlite3
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    from miband6.xiaomi_cloud import (  # noqa: F401 (một số tên dùng trong kiểm thử)
        HEALTH_PATH, HEX32, KEY_FIELDS, REGIONS, LoginError, RC4Stream, XiaomiLogin, _key_of, decrypt_body,
        describe_source, device_from_record, fetch_devices, make_nonce, mihome_params, parse_source_list, rc4,
        signed_nonce, stream_params,
    )
except ImportError:  # chạy ngoài môi trường của dự án
    sys.exit("Chạy script trong thư mục ứng dụng bằng: uv run tools/mifitness_key.py")


# ============================================================ đọc tệp Mi Fitness trên iPhone


def unarchive(blob: bytes):
    """Giải NSKeyedArchiver (bplist) thành dict/list Python."""
    pl = plistlib.loads(blob)
    objs = pl.get("$objects") or []

    def res(v, depth=0):
        if depth > 60:
            return None
        if isinstance(v, plistlib.UID):
            v = objs[v.data] if v.data < len(objs) else None
            if v == "$null":
                return None
        if isinstance(v, dict):
            if "NS.keys" in v and "NS.objects" in v:
                return {str(res(k, depth + 1)): res(o, depth + 1) for k, o in zip(v["NS.keys"], v["NS.objects"])}
            if "NS.objects" in v:
                return [res(o, depth + 1) for o in v["NS.objects"]]
            if "NS.string" in v:
                return res(v["NS.string"], depth + 1)
            return {k: res(x, depth + 1) for k, x in v.items() if k != "$class"}
        if isinstance(v, list):
            return [res(x, depth + 1) for x in v]
        return v

    return res(pl.get("$top", {}))


def _walk_records(o, out: list[dict]) -> None:
    if isinstance(o, dict):
        if any(_key_of(o.get(f)) for f in KEY_FIELDS) or isinstance(o.get("detail"), (dict, str)) and "name" in o:
            out.extend(device_from_record(o))
        for v in o.values():
            _walk_records(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk_records(v, out)


def _page1_from_wal(wal: bytes) -> bytes | None:
    """Lấy trang 1 mới nhất trong tệp WAL để dựng lại tệp CSDL chính khi chỉ có -wal."""
    if len(wal) < 32:
        return None
    page_size = struct.unpack(">I", wal[8:12])[0]
    page_size = 65536 if page_size == 1 else page_size
    page1, off = None, 32
    while off + 24 + page_size <= len(wal):
        if struct.unpack(">I", wal[off:off + 4])[0] == 1:
            page1 = wal[off + 24:off + 24 + page_size]
        off += 24 + page_size
    return page1


def keys_from_manifest(main: bytes | None, wal: bytes | None, data_files: dict[str, bytes]) -> list[dict]:
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "manifest.sqlite"
        if main and main[:15] == b"SQLite format 3":
            db.write_bytes(main)
        elif wal:
            page1 = _page1_from_wal(wal)
            if not page1:
                return []
            db.write_bytes(page1)
        else:
            return []
        if wal:
            (Path(d) / "manifest.sqlite-wal").write_bytes(wal)
        con = sqlite3.connect(str(db))
        try:
            rows = con.execute("SELECT key, filename, inline_data FROM manifest WHERE key LIKE 'registerList%'").fetchall()
        finally:
            con.close()
    out: list[dict] = []
    for _key, filename, inline in rows:
        blob = bytes(inline) if inline else data_files.get(filename or "")
        if not blob or not blob.startswith(b"bplist"):
            continue
        try:
            _walk_records(unarchive(blob), out)
        except Exception:  # noqa: BLE001 - tệp lạ: bỏ qua bản ghi này
            continue
    return out


def keys_from_files(paths: list[str]) -> tuple[list[dict], list[str]]:
    """Đọc key từ manifest.sqlite / -wal, thư mục Mi Fitness hoặc tệp .zip của thư mục đó."""
    files: dict[str, bytes] = {}
    for p in map(Path, paths):
        p = p.expanduser()
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and ("VirtualDevice_registerList" in f.as_posix() or f.name.startswith("manifest.sqlite")):
                    files[f.as_posix()] = f.read_bytes()
        elif p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if "VirtualDevice_registerList/" in n and "__MACOSX" not in n and not n.endswith("/"):
                        files[n] = z.read(n)
        elif p.is_file():
            files[p.as_posix()] = p.read_bytes()
        else:
            raise LoginError(f"Không tìm thấy tệp: {p}")
    mains = {k: v for k, v in files.items() if k.endswith("manifest.sqlite")}
    wals = {k: v for k, v in files.items() if k.endswith("manifest.sqlite-wal")}
    data = {Path(k).name: v for k, v in files.items() if "/data/" in k}
    results: list[dict] = []
    notes: list[str] = []
    pairs = []
    for k, v in mains.items():
        wal = wals.get(k + "-wal") or (next(iter(wals.values())) if len(mains) == 1 and len(wals) == 1 else None)
        pairs.append((v, wal))
    if not mains:
        pairs += [(None, w) for w in wals.values()]
    for main, wal in pairs:
        try:
            results += keys_from_manifest(main, wal, data)
        except sqlite3.DatabaseError as e:
            notes.append(f"Không mở được CSDL: {e}")
    if not results:
        # Dự phòng: tìm mọi chuỗi 32 hex trong các tệp.
        for name, b in files.items():
            for m in re.finditer(rb"(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])", b):
                results.append({"name": f"(ứng viên trong {Path(name).name})", "model": "", "mac": "",
                                "key": m.group(0).decode().lower(), "field": "?"})
        if results:
            notes.append("Không đọc được cấu trúc tệp; dưới đây là mọi chuỗi 32 ký tự hex tìm thấy, hãy thử lần lượt.")
    uniq, seen = [], set()
    for r in results:
        if (r["mac"], r["key"]) not in seen:
            seen.add((r["mac"], r["key"]))
            uniq.append(r)
    return uniq, notes


# ============================================================ in kết quả


def is_band6(d: dict) -> bool:
    n = (d.get("name", "") + " " + d.get("model", "")).lower()
    return "band 6" in n or "band6" in n or "手环6" in n or "手環6" in n


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def save_env(key: str) -> None:
    lines = ENV_PATH.read_text("utf-8").splitlines() if ENV_PATH.is_file() else []
    lines = [ln for ln in lines if ln.strip().removeprefix("export ").split("=", 1)[0].strip() != "MIBAND6_AUTH_KEY"]
    lines.append(f"MIBAND6_AUTH_KEY={key}")
    ENV_PATH.write_text("\n".join(lines) + "\n", "utf-8")
    os.chmod(ENV_PATH, 0o600)
    print(f"Đã ghi MIBAND6_AUTH_KEY vào {ENV_PATH}")


def report(devices: list[dict], where: str, write_env: bool = False) -> int:
    print(f"\nKey tìm được ({where}):")
    band = None
    for d in devices:
        star = "★" if is_band6(d) else " "
        print(f" {star} {d['name']}" + (f"  [{d['model']}]" if d.get("model") else ""))
        print(f"     MAC: {d['mac'] or '—'}")
        print(f"     Key: 0x{d['key']}   (trường {d['field']})")
        if star == "★" and band is None:
            band = d
    if band is None and len({d['key'] for d in devices}) == 1:
        band = devices[0]
    if band and write_env:
        print()
        save_env(band["key"])
    elif band and sys.platform == "darwin":
        try:
            subprocess.run(["pbcopy"], input=band["key"].encode(), check=True)
            print("\nĐã chép key của Mi Band 6 vào clipboard. Dán vào ô Auth key trong ứng dụng,")
            print("hoặc chạy lại với --save-env để ghi thẳng vào tệp .env.")
        except (OSError, subprocess.CalledProcessError):
            pass
    print("Đừng hủy ghép đôi vòng tay trong Mi Fitness, nếu không key này sẽ mất hiệu lực.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Lấy auth key Mi Band 6 từ tài khoản hoặc tệp Mi Fitness.")
    ap.add_argument("--file", nargs="+", metavar="TỆP",
                    help="Đọc key từ manifest.sqlite / manifest.sqlite-wal (hoặc .zip thư mục Mi Fitness) chép từ iPhone")
    ap.add_argument("--password", action="store_true", help="Đăng nhập bằng tài khoản + mật khẩu thay vì mã QR")
    ap.add_argument("--user", help="Email / số điện thoại / Xiaomi ID (dùng với --password)")
    ap.add_argument("--region", help="Chỉ thử một vùng máy chủ, ví dụ sg (mặc định thử sg trước)")
    ap.add_argument("--fresh", action="store_true", help="Bỏ phiên đăng nhập đã lưu, đăng nhập lại")
    ap.add_argument("--timeout", type=float, help="Thời gian chờ quét QR, giây")
    ap.add_argument("--save-env", action="store_true", help="Ghi key của Mi Band 6 vào tệp .env của ứng dụng")
    args = ap.parse_args()

    try:
        if args.file:
            devices, notes = keys_from_files(args.file)
            for n in notes:
                print(n)
            if not devices:
                print("Không tìm thấy key trong các tệp đã chọn. Hãy chọn đúng manifest.sqlite và manifest.sqlite-wal "
                      "trong thư mục VirtualDevice_registerList.")
                return 1
            return report(devices, "tệp Mi Fitness", args.save_env)

        if args.fresh:
            XiaomiLogin.forget()
        login = XiaomiLogin(seed=args.user)
        reused = login.load()
        if reused:
            print("Dùng lại phiên đăng nhập Xiaomi lúc trước (chạy kèm --fresh để đăng nhập lại).")
        elif args.password:
            user = args.user or input("Email, số điện thoại hoặc Xiaomi ID: ").strip()
            pw = getpass.getpass("Mật khẩu (không hiện khi gõ): ")
            login = XiaomiLogin(seed=user)
            login.login_password(user, pw)
        else:
            login.login_qr(args.timeout)
        if not reused:
            login.save()
        print(f"Đã đăng nhập Xiaomi ID {login.user_id}. Đang đọc danh sách thiết bị…", flush=True)
        regions = [args.region.lower(), ""] if args.region else REGIONS
        devices, trail, answered = fetch_devices(login, regions)
    except LoginError as e:
        print(f"\nLỗi: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nĐã hủy.")
        return 130

    if devices:
        XiaomiLogin.forget()  # xong việc: xóa phiên đã lưu
        return report(devices, "máy chủ Xiaomi", args.save_env)

    print("\nKhông lấy được key từ máy chủ. Chi tiết từng lần thử (không chứa mật khẩu hay token):")
    for line in trail:
        print("   ", line)
    if not answered and reused:
        print("\nPhiên đăng nhập cũ có thể đã hết hạn. Chạy lại với --fresh.")
    print(f"\nKiểm tra Xiaomi ID {login.user_id} có trùng với ID ở tab Profile trong Mi Fitness không.")
    print("Trên iPhone có thể lấy key từ tệp, không cần đăng nhập. Xem: uv run tools/mifitness_key.py --help")
    return 1


if __name__ == "__main__":
    sys.exit(main())
