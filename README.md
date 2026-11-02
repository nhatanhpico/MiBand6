# Quản lý Mi Band 6

Ứng dụng web chạy trên máy tính để kết nối Xiaomi Mi Smart Band 6 qua Bluetooth LE, xem thông tin và thay đổi cài đặt của vòng tay, không cần điện thoại. Server Python chạy trên máy Mac giữ kết nối Bluetooth; giao diện mở trong trình duyệt.

Chạy được trên macOS (Apple Silicon và Intel), Windows và Linux.

## Ứng dụng làm được gì

**Xem thông tin**
- Pin (mức pin, trạng thái sạc, lần sạc gần nhất)
- Bước chân, quãng đường, năng lượng tiêu hao hôm nay, tiến độ so với mục tiêu
- Nhịp tim: đo một lần hoặc theo dõi liên tục
- Firmware, phần cứng, số serial, giờ hiện tại trên vòng tay

**Thay đổi cài đặt**
- Hồ sơ cơ thể (ngày sinh, giới tính, chiều cao, cân nặng), mục tiêu bước chân, tay đeo; lấy sẵn từ tài khoản Mi Fitness bằng nút **Đồng bộ**
- Ngôn ngữ (có tiếng Việt), kiểu giờ 12/24, kiểu ngày, đơn vị khoảng cách
- Nâng tay sáng màn hình (tắt, luôn bật, theo khung giờ) và độ nhạy
- Chế độ ban đêm, khóa bằng mật khẩu 6 số
- Sắp xếp ứng dụng trên vòng tay thành ba nhóm: màn hình chính (tối đa 15), trong mục **Thêm**, hoặc ẩn; sắp xếp phím tắt
- Đo nhịp tim tự động, cảnh báo nhịp tim cao, theo dõi căng thẳng
- Nhắc vận động (kèm giờ nghỉ trưa), Không làm phiền
- 10 báo thức: đọc từ vòng tay, chỉnh sửa, lưu lại
- Đồng bộ giờ với máy tính (tự làm mỗi lần kết nối)

**Công cụ**
- Gửi thông báo có biểu tượng tới vòng tay, giả lập cuộc gọi đến
- Rung vòng tay để tìm
- Bấm "Tìm điện thoại" trên vòng tay thì máy tính phát âm thanh
- Nhật ký toàn bộ gói tin Bluetooth để chẩn đoán

**Giao diện**
- Tiếng Việt và tiếng Anh: đổi bằng nút **VI / EN** ở góc dưới thanh bên (trên điện thoại: ở thanh trên cùng). Lựa chọn được nhớ cho lần sau, kể cả thông báo của server.
- Giao diện tối, co giãn theo màn hình: thanh bên đầy đủ trên máy tính, thanh biểu tượng trên máy tính bảng, thanh tab dưới cùng trên điện thoại (dùng với `--lan`).

## Cài đặt và chạy

Cần [uv](https://docs.astral.sh/uv/). Nếu chưa có:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Chạy server (lần đầu uv tự tải Python 3.12 và các thư viện):

```bash
cd ~/Project/MiBand6
uv run miband6-web
```

Server mở giao diện tại <http://localhost:8766> trong trình duyệt. Nhấn `Ctrl+C` trong Terminal để tắt. Có thể nhấp đúp `run.command` trong Finder thay cho lệnh trên.

Các tùy chọn:

| Lệnh | Tác dụng |
| --- | --- |
| `uv run miband6-web --demo` | Dùng vòng tay giả lập, không cần Bluetooth, để xem thử giao diện |
| `uv run miband6-web --lan` | Cho điện thoại/máy khác trong cùng mạng Wi-Fi mở giao diện. Server in ra một đường dẫn có mã truy cập; ai có đường dẫn đó đều điều khiển được vòng tay |
| `uv run miband6-web --port 9000` | Đổi cổng |
| `uv run miband6-web --env đường/dẫn/.env` | Đọc auth key từ một tệp `.env` khác |

Mặc định server chỉ nhận kết nối từ chính máy này, và từ chối yêu cầu do trang web khác gửi tới.

Bản desktop cũ (Qt) vẫn còn: `uv run --extra desktop miband6-app`.

### Quyền Bluetooth trên macOS

Lần quét đầu tiên, macOS sẽ hỏi "Terminal muốn sử dụng Bluetooth": chọn **Cho phép**. Nếu lỡ từ chối, vào **Cài đặt hệ thống → Quyền riêng tư & Bảo mật → Bluetooth** và bật cho Terminal (hoặc VS Code / iTerm, tùy bạn chạy lệnh từ đâu).

## Lấy auth key

Mi Band 6 chỉ nhận lệnh từ thiết bị biết **auth key**, mã 32 ký tự hex được tạo khi bạn ghép đôi vòng tay bằng app của hãng. Mã nằm ở đâu tùy vào app bạn đã dùng để ghép đôi.

### Nếu ghép đôi bằng Mi Fitness

Mi Fitness lưu mã trên máy chủ Xiaomi. Chạy script đi kèm, script tự cài thư viện cần thiết bằng uv:

```bash
cd ~/Project/MiBand6
uv run tools/mifitness_key.py
```

Script mở một mã QR và in ra một đường dẫn. Quét mã bằng camera điện thoại (hoặc mở đường dẫn trong trình duyệt), rồi đăng nhập tài khoản Xiaomi bạn dùng trong Mi Fitness. Nếu Xiaomi hỏi mã xác minh, nhập ngay trên trang đó. Đăng nhập xong, script in danh sách thiết bị kèm `Key: 0x...` và tự chép key của Mi Band 6 vào clipboard.

Muốn đăng nhập bằng mật khẩu ngay trong Terminal thì chạy `uv run tools/mifitness_key.py --password`. Script hỗ trợ cả mã xác minh gửi qua email/SMS, nhưng cách QR ổn định hơn.

Script ưu tiên máy chủ Singapore (`sg.hlth.io.mi.com`), nơi lưu dữ liệu của tài khoản Xiaomi Việt Nam. Nếu không lấy được key, script in chi tiết từng lần thử (không chứa mật khẩu hay token). Phiên đăng nhập được giữ 12 giờ để chạy lại không phải quét QR; thêm `--fresh` để đăng nhập lại.

> `huami-token --method xiaomi` báo `Missing ssecurity or location in auth response` khi Xiaomi đòi xác minh 2 bước, và chỉ hỏi máy chủ gốc nên tài khoản vùng Singapore nhận danh sách rỗng. Script trên xử lý cả hai.

**iPhone, không cần đăng nhập:** Mi Fitness lưu key trong một tệp mà ứng dụng Tệp (Files) mở được.

1. Mở **Tệp** → **Trên iPhone** → **Mi Fitness** → **MHWCahe** → thư mục tên là một dãy số → **VirtualDevice_registerList**.
2. AirDrop hai tệp `manifest.sqlite` và `manifest.sqlite-wal` sang máy Mac (có lúc chỉ có một tệp, vẫn được).
3. Chạy:

```bash
uv run tools/mifitness_key.py --file ~/Downloads/manifest.sqlite ~/Downloads/manifest.sqlite-wal
```

Có thể đưa cả thư mục Mi Fitness (hoặc tệp .zip của thư mục đó) cho `--file`. Xóa các tệp đã chép sau khi lấy xong key.

Điện thoại **Android** có thêm một cách không cần đăng nhập: Mi Fitness ghi mã vào tệp nhật ký trên điện thoại. Cắm điện thoại vào máy Mac, bật gỡ lỗi USB, rồi chạy:

```bash
adb shell "grep -Eo '(encryptKey|token|authKey|huamiAuthKey)[\":= ]+[[:xdigit:]]{32}' /sdcard/Android/data/com.xiaomi.wearable/files/log/*.log"
```

Ưu tiên giá trị nằm sau `huamiAuthKey`. Nếu có nhiều giá trị, thử giá trị cuối cùng trước.

### Nếu ghép đôi bằng Zepp Life

Dùng [huami-token](https://codeberg.org/argrento/huami-token) với tài khoản Zepp:

```bash
uvx --from git+https://codeberg.org/argrento/huami-token huami-token \
    --method amazfit --email EMAIL --password MAT_KHAU --bt_keys
```

Các cách khác (điện thoại đã root, Xiaomi Cloud Tokens Extractor…) có trong [hướng dẫn của Gadgetbridge](https://gadgetbridge.org/basics/pairing/huami-xiaomi-server/).

> **Quan trọng:** đừng **hủy ghép đôi** vòng tay trong Mi Fitness / Zepp Life và đừng khôi phục cài đặt gốc vòng tay. Làm vậy mã cũ mất hiệu lực và bạn phải lấy lại mã mới.

## Lưu auth key trong tệp .env

Thay vì nhập key trên giao diện, đặt nó trong tệp `.env` ở thư mục dự án:

```bash
cd ~/Project/MiBand6
cp .env.example .env
open -e .env        # điền MIBAND6_AUTH_KEY=...
```

Hoặc để script lấy key ghi thẳng vào `.env`: `uv run tools/mifitness_key.py --save-env`.

| Biến | Ý nghĩa |
| --- | --- |
| `MIBAND6_AUTH_KEY` | Auth key 32 ký tự hex (có hoặc không có `0x`) |
| `MIBAND6_ADDRESS` | Không bắt buộc: mã thiết bị Bluetooth, để kết nối mà không cần quét |
| `MIBAND6_PROTOCOL` | Không bắt buộc: `auto`, `classic` hoặc `2021` |

Khi có `MIBAND6_AUTH_KEY`, để trống ô auth key trên giao diện. Key chỉ nằm phía server, không gửi ra trình duyệt và không được chép vào `config.json`. Tệp `.env` đã có trong `.gitignore`; đừng đưa nó lên GitHub. `miband6-cli info` cũng đọc key và địa chỉ từ `.env`.

## Kết nối lần đầu

1. **Tắt Bluetooth trên điện thoại** (hoặc thoát hẳn Mi Fitness / Zepp Life). Vòng tay chỉ giữ một kết nối và sẽ không hiện ra khi đang nối với điện thoại.
2. Chạy `uv run miband6-web`, ở trang **Thiết bị** bấm **Quét**. Vòng tay hiện tên "Mi Smart Band 6".
3. Dán auth key (hoặc để trống nếu đã đặt trong `.env`), bấm **Kết nối**.

Ứng dụng nhớ vòng tay và kiểu xác thực đã dùng, lần sau chỉ cần bấm Kết nối. Tệp cấu hình nằm tại `~/Library/Application Support/MiBand6Manager/config.json` (chỉ tài khoản của bạn đọc được).

### Kiểu xác thực

Mi Band 6 có hai kiểu xác thực:

- **Kiểu cũ**: firmware gốc của vòng tay.
- **Kiểu mới (2021)**: các firmware cập nhật về sau. Nếu dùng sai kiểu, vòng tay có thể hiện thông báo "cập nhật ứng dụng". Ở kiểu này mọi lệnh cài đặt được mã hóa bằng khóa phiên trao đổi qua ECDH.

Để mặc định **Tự động**, ứng dụng thử kiểu cũ trước rồi chuyển sang kiểu mới, và ghi nhớ kiểu dùng được cho lần sau.

## Lấy hồ sơ từ Mi Fitness

Vòng tay chỉ cho ghi hồ sơ, không cho đọc lại qua Bluetooth, nên lần đầu các ô ở **Cài đặt → Hồ sơ** là giá trị mặc định. Bấm **Đồng bộ** ở đầu trang đó để lấy tên, ngày sinh, giới tính, chiều cao, cân nặng và mục tiêu bước từ tài khoản Mi Fitness:

1. Giao diện hiện mã QR đăng nhập Xiaomi. Quét bằng camera điện thoại và đăng nhập đúng tài khoản dùng trong Mi Fitness (hoặc bấm "Hoặc đăng nhập trong trình duyệt").
2. Server đọc hồ sơ từ máy chủ Mi Fitness, điền vào các ô và ghi ngay vào vòng tay nếu đang kết nối. Nếu chưa kết nối, hồ sơ được ghi tự động ở lần kết nối tới.

Server chỉ đọc, không thay đổi gì trong tài khoản. Phiên đăng nhập được giữ 12 giờ trong `~/Library/Caches/MiBand6Manager/xiaomi-session.json` (chỉ tài khoản của bạn đọc được) để lần sau khỏi quét lại; nút **Đăng nhập lại** trong hộp thoại bỏ phiên cũ. Nếu không đọc được hồ sơ, chi tiết từng lần gọi máy chủ nằm trong **Nhật ký Bluetooth** ở trang Thiết bị.

## Sắp xếp ứng dụng trên vòng tay

Trang **Cài đặt → Ứng dụng** chia ứng dụng thành ba nhóm:

- **Màn hình chính:** hiện ngay khi vuốt lên, xuống, tối đa 15 ứng dụng.
- **Trong mục Thêm:** gom vào mục "Thêm" ở cuối danh sách.
- **Ẩn:** không hiện ở đâu.

Chọn nhóm bằng ô chọn bên cạnh mỗi ứng dụng, đổi thứ tự bằng nút mũi tên hoặc kéo thả, rồi bấm **Lưu bố cục**. Ứng dụng Cài đặt không ẩn được. **Về bố cục gốc** đưa giao diện về bố cục gần với mặc định của vòng tay (chưa ghi cho tới khi bấm Lưu).

Vòng tay không cho đọc lại bố cục hiện tại, nên ứng dụng chỉ nhớ lần lưu gần nhất của chính nó.

## Khắc phục sự cố

| Hiện tượng | Cách xử lý |
| --- | --- |
| Quét không thấy vòng tay | Tắt Bluetooth trên điện thoại, chạm màn hình vòng tay cho sáng rồi quét lại. Thử tích "Hiện mọi thiết bị Bluetooth". |
| "Auth key không đúng" | Kiểm tra lại mã (32 ký tự hex). Nếu huami-token trả về nhiều thiết bị, chọn đúng dòng có MAC của Mi Band 6. Nếu vừa hủy ghép đôi trong app của hãng, mã cũ đã mất hiệu lực. |
| "Vòng tay không phản hồi bước xác thực" | Vòng tay có thể vẫn đang nối với điện thoại. Thử chọn kiểu xác thực "Kiểu mới". |
| Lỗi quyền Bluetooth | Cấp quyền Bluetooth cho Terminal như mục trên. |
| Đồng bộ Mi Fitness báo không đọc được hồ sơ | Bấm **Đăng nhập lại** và quét mã bằng đúng tài khoản Xiaomi của Mi Fitness. Vẫn lỗi thì chép các dòng "Mi Fitness:" trong Nhật ký Bluetooth gửi kèm khi báo lỗi. |
| Một cài đặt không có tác dụng | Mở **Nhật ký Bluetooth** cuối trang **Thiết bị**, bấm **Tải về** để xem vòng tay trả lời gì. |
| Vòng tay mất mục Thêm hoặc mất Cài đặt | Vào **Cài đặt → Ứng dụng**, bấm **Về bố cục gốc** rồi **Lưu bố cục**. |
| Trình duyệt báo không mở được localhost:8766 | Server chưa chạy hoặc đã tắt: chạy lại `uv run miband6-web`. Nếu cổng bận, server tự dùng cổng kế tiếp; xem đường dẫn in trong Terminal. |
| (Bản desktop) uv báo không có bản PySide6 phù hợp | PySide6 mới cần macOS 14 trở lên. Trên macOS cũ hơn, sửa `PySide6-Essentials>=6.6` trong `pyproject.toml` thành `PySide6-Essentials>=6.6,<6.8`, xóa `uv.lock` rồi chạy lại. |

## Dòng lệnh

Để kiểm tra nhanh mà không mở giao diện:

```bash
uv run miband6-cli scan
uv run miband6-cli info --address <MÃ_THIẾT_BỊ> --key <AUTH_KEY> -v
uv run miband6-cli info -v        # lấy địa chỉ và key từ .env
```

## Chưa hỗ trợ

- Tải lịch sử hoạt động, giấc ngủ, nhịp tim theo ngày từ vòng tay (chỉ đọc số liệu hiện tại).
- Cập nhật firmware, cài mặt đồng hồ, thời tiết, điều khiển nhạc.

## Cấu trúc mã nguồn

```
src/miband6/
  protocol.py   UUID, dựng và giải mã gói tin (hàm thuần, dễ kiểm thử)
  crypto.py     AES, ECDH trên đường cong B-163, kênh truyền mã hóa kiểu 2021
  device.py     Lớp MiBand6 bất đồng bộ (bleak): kết nối, xác thực, đọc, ghi
  simulator.py  Vòng tay giả lập, dùng cho kiểm thử và chế độ --demo
  config.py     Lưu auth key và cài đặt
  envfile.py    Đọc auth key từ tệp .env
  i18n.py       Dịch thông báo của server (tiếng Việt / tiếng Anh)
  xiaomi_cloud.py  Đăng nhập Xiaomi (QR) và API Mi Fitness: danh sách thiết bị, hồ sơ người dùng
  cli.py        Công cụ dòng lệnh
  web/server.py Server web (aiohttp): REST API + WebSocket, dùng chung vòng lặp với Bluetooth
  web/cloud.py  Đồng bộ hồ sơ từ Mi Fitness chạy nền
  web/static/   Giao diện trình duyệt (HTML, CSS, JavaScript; không cần build)
  web/static/i18n/en.json  Bản dịch tiếng Anh (khóa là chuỗi tiếng Việt gốc)
  web/static/fonts/        Phông Be Vietnam Pro (SIL OFL), không cần mạng
  gui/          Bản desktop cũ (Qt, tùy chọn)
tools/mifitness_key.py  Lấy auth key từ tài khoản Mi Fitness
tests/          Kiểm thử giao thức, mã hóa, toàn bộ luồng kết nối và giao diện
```

Thêm chuỗi giao diện mới thì viết bằng tiếng Việt (trong HTML, `t("…")` ở app.js hoặc `tr('…')` ở Python) rồi thêm bản dịch vào `en.json`. `uv run python tests/i18n_strings.py` liệt kê các chuỗi còn thiếu; kiểm thử cũng báo lỗi nếu thiếu.

Chạy kiểm thử:

```bash
uv run pytest
```

Phần ECDH được đối chiếu với OpenSSL (sect163r2); hai kiểu xác thực được kiểm thử đầu cuối với vòng tay giả lập, gồm cả kiểm tra CRC và số thứ tự của gói mã hóa.

## Ghi công

Giao thức Bluetooth của vòng tay Huami/Xiaomi do cộng đồng dịch ngược; ứng dụng này tham khảo cách hoạt động của dự án [Gadgetbridge](https://gadgetbridge.org/). Ứng dụng không liên quan tới Xiaomi hay Zepp Health. Thay đổi cài đặt vòng tay bằng công cụ không chính thức là rủi ro của người dùng.
