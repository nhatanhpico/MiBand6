# Thời tiết trên vòng tay

Mi Band 6 không tự lấy thời tiết: điện thoại (Mi Fitness) gửi cho nó. Khi vòng tay nối với ứng dụng này, ứng dụng làm việc đó thay điện thoại. Cài đặt nằm ở **Cài đặt → Ứng dụng → Thời tiết**, có trong cả bản web và ứng dụng macOS.

## Gửi những gì, khi nào

- Mỗi lần kết nối vòng tay, rồi mỗi giờ khi vẫn kết nối. Bấm **Gửi thời tiết ngay** để gửi tức thì.
- Thời tiết hiện tại (biểu tượng, nhiệt độ, mô tả), dự báo 7 ngày (cao nhất, thấp nhất), chất lượng không khí (chỉ số AQI của Mỹ), gió (cấp Beaufort), độ ẩm, giờ mặt trời mọc và lặn, và tên địa điểm.
- Mô tả theo ngôn ngữ của vòng tay (tiếng Việt nếu vòng tay đặt tiếng Việt, còn lại tiếng Anh). Nhiệt độ theo °C, hoặc °F nếu vòng tay dùng đơn vị Anh (Cài đặt → Màn hình → Đơn vị).
- Dòng dưới cài đặt cho biết lần gửi gần nhất, ví dụ "Đã gửi lúc 15:20: Hà Nội · 24° · Có mây".

Tắt **Tự đồng bộ thời tiết** thì ứng dụng thôi gửi; vòng tay giữ thời tiết đã nhận lần trước.

## Vị trí

- **Tự động**: vị trí gần đúng theo địa chỉ IP của mạng đang dùng (hỏi [ipapi.co](https://ipapi.co), dự phòng [ipwho.is](https://ipwho.is); dùng lại kết quả trong 6 giờ). Dùng VPN thì vị trí là nơi đặt máy chủ VPN.
- **Chọn thành phố**: gõ tên thành phố rồi chọn trong danh sách (tìm bằng dịch vụ geocoding của Open-Meteo).

## Nguồn dữ liệu và quyền riêng tư

Dự báo lấy từ [Open-Meteo](https://open-meteo.com) (miễn phí, không cần tài khoản hay khóa API; dữ liệu theo giấy phép CC BY 4.0). Ứng dụng chỉ gửi tọa độ tới Open-Meteo; ở chế độ tự động, dịch vụ định vị thấy địa chỉ IP của bạn như với mọi trang web. Không có dữ liệu sức khỏe nào rời khỏi máy.

## Cách gửi tới vòng tay

Theo Gadgetbridge (`HuamiSupport.onSendWeather`): sáu gói qua kênh "chunked" loại 1, mã hóa khi vòng tay dùng giao thức 2021. Mã thời tiết WMO của Open-Meteo được đổi sang mã biểu tượng của vòng tay theo bảng `HuamiWeatherConditions` của Gadgetbridge.

## Khắc phục sự cố

| Hiện tượng | Cách xử lý |
| --- | --- |
| "Lần gửi trước không thành công: …" | Thường do mất mạng hoặc vòng tay ngắt kết nối giữa chừng; bấm **Gửi thời tiết ngay**. Chi tiết trong **Nhật ký Bluetooth** ở trang **Thiết bị**. |
| Vị trí tự động sai | Chọn **Chọn thành phố** và tìm thành phố của bạn. |
| Vòng tay vẫn hiện thời tiết cũ | Mở ứng dụng Thời tiết trên vòng tay sau khi gửi; nếu điện thoại cũng nối với vòng tay, Mi Fitness có thể ghi đè. |
