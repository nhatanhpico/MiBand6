"""Công cụ dòng lệnh để kiểm tra nhanh khi giao diện gặp sự cố.

    uv run miband6-cli scan
    uv run miband6-cli info --address <ĐỊA_CHỈ> --key <AUTH_KEY>
    uv run miband6-cli info          # lấy địa chỉ và key từ tệp .env
"""

from __future__ import annotations

import argparse
import asyncio

import os

from . import protocol as P
from .device import MiBand6, scan
from .envfile import ENV_ADDRESS, ENV_KEY, ENV_PROTOCOL, load_env


async def _scan(args) -> None:
    print(f"Đang quét {args.timeout:.0f} giây…")
    found = await scan(args.timeout, show_all=args.all)
    if not found:
        print("Không thấy Mi Band 6. Hãy tắt Bluetooth trên điện thoại rồi thử lại.")
    for dev, rssi, is_band, name in found:
        mark = "★" if is_band else " "
        print(f"{mark} {name or '(không tên)':<24} {dev.address}  RSSI {rssi}")


async def _info(args) -> None:
    if not args.key or not args.address:
        raise SystemExit("Thiếu --key/--address (hoặc MIBAND6_AUTH_KEY/MIBAND6_ADDRESS trong .env).")
    key = P.parse_auth_key(args.key)
    band = MiBand6(args.address, key, args.protocol, log=print if args.verbose else None)
    proto = await band.connect()
    try:
        info = await band.read_device_info()
        bat = await band.read_battery()
        act = await band.read_activity()
        t = await band.read_time()
        print(f"Giao thức: {proto}")
        print(f"Firmware : {info.firmware}   Phần cứng: {info.hardware}   Serial: {info.serial}")
        if bat:
            print(f"Pin      : {bat.level}%{' (đang sạc)' if bat.charging else ''}")
        if act:
            print(f"Bước     : {act.steps}   Quãng đường: {act.meters} m   Calo: {act.calories}")
        print(f"Giờ vòng : {t}")
    finally:
        await band.disconnect()


def main() -> None:
    ap = argparse.ArgumentParser(prog="miband6-cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="Quét tìm vòng tay")
    s.add_argument("--timeout", type=float, default=8)
    s.add_argument("--all", action="store_true", help="Hiện mọi thiết bị BLE")
    i = sub.add_parser("info", help="Kết nối và in thông tin")
    load_env()
    i.add_argument("--address", default=os.environ.get(ENV_ADDRESS))
    i.add_argument("--key", default=os.environ.get(ENV_KEY))
    i.add_argument("--protocol", default=os.environ.get(ENV_PROTOCOL) or "auto", choices=["auto", "classic", "2021"])
    i.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    asyncio.run(_scan(args) if args.cmd == "scan" else _info(args))


if __name__ == "__main__":
    main()
