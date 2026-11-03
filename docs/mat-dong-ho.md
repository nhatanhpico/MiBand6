# Mặt đồng hồ và ảnh nền

Thẻ **Cài đặt vòng tay → Mặt đồng hồ** cài mặt đồng hồ lên Mi Band 6: dùng ảnh của bạn làm ảnh nền, hoặc cài một tệp mặt đồng hồ `.bin`. Có trong cả bản web và ứng dụng macOS.

## Khung mô phỏng

Bên trái là hình Mi Band 6 với màn hình đúng kích thước thật (152 × 486 điểm ảnh, bo góc như vòng tay). Nó hiện đúng thứ sẽ lên vòng tay trước khi bạn cài:

- ảnh nền đang chỉnh (kèm giờ),
- ảnh xem trước có sẵn trong tệp `.bin` vừa chọn,
- hoặc, khi chưa chọn gì, mặt đồng hồ đã cài qua ứng dụng.

## Dùng ảnh của bạn

> **Đã sửa lỗi làm vòng tay treo.** Bản trước dựng tệp với phần tiêu đề của Mi Band 5 (lấy từ mẫu của watchface-js): Mi Band 6 nhận tệp nhưng treo khi vẽ. Giờ tệp dùng tiêu đề của Mi Band 6 (mã thiết bị 148), giống bộ dựng mặt đồng hồ đã chạy trên Mi Band 6 thật của dự án [pixel-watchface](https://github.com/mishamyrt/pixel-watchface). Nếu vòng tay của bạn từng bị ảnh hưởng, xem [Khi vòng tay bị treo hoặc mất mặt đồng hồ](#khi-vòng-tay-bị-treo-hoặc-mất-mặt-đồng-hồ).

1. Chọn thẻ **Ảnh của bạn**, bấm **Chọn ảnh…**. Ảnh lớn cỡ nào cũng được (ảnh chụp từ điện thoại vẫn được): ứng dụng tự thu nhỏ cho vừa màn hình vòng tay.
2. Trong khung chỉnh, phần sáng hình viên thuốc là phần hiện trên vòng tay; phần tối sẽ bị cắt. Kéo ảnh để di chuyển, cuộn chuột hoặc dùng thanh **Phóng to**. Bàn phím: phím mũi tên để dịch (giữ Shift để dịch nhanh), `+` / `-` để phóng to, thu nhỏ.
3. **Cách đặt ảnh**: **Lấp đầy** phủ kín màn hình (cắt bớt mép ảnh); **Trọn ảnh** giữ cả ảnh, chỗ trống để màu đen.
4. **Giờ**: hiện giờ và phút xếp chồng ở trên, giữa hoặc dưới, hoặc **Ẩn**. **Màu chữ số**: trắng (ảnh tối) hoặc đen (ảnh sáng).
5. Bấm **Cài lên vòng tay**. Thanh tiến độ cho biết phần đã gửi; vòng tay tự chuyển sang mặt mới khi xong. **Chỉ đặt làm ảnh xem trước** thì không cài gì, chỉ đổi hình ở trang **Tổng quan**.

Ứng dụng dựng tệp mặt đồng hồ Mi Band 6 từ ảnh nền (24 bit) và các chữ số giờ, theo mô tả định dạng của [watchface-js](https://github.com/Nadeflore/watchface-js) và phần tiêu đề, kiểu ảnh của [pixel-watchface](https://github.com/mishamyrt/pixel-watchface). Mặt đồng hồ này không kèm ảnh xem trước riêng, nên danh sách mặt đồng hồ trên vòng tay có thể hiện ô trống cho nó.

## Cài tệp .bin

1. Chọn thẻ **Tệp .bin**, bấm **Chọn tệp .bin…**. Tệp phải là mặt đồng hồ dành cho Mi Band 6 (bắt đầu bằng `UIHH`; tệp của Mi Band 5 hay vòng khác bị từ chối).
2. Ứng dụng đọc ảnh xem trước trong tệp và hiện ở khung mô phỏng. Một số tệp dùng ảnh nén mà ứng dụng chưa đọc được; tệp đó vẫn cài được, chỉ không có ảnh xem trước.
3. Bấm **Cài lên vòng tay**.

Cách cài giống Gadgetbridge. Vòng tay từ chối khi pin yếu hoặc không đủ chỗ trống: sạc vòng tay hoặc xóa bớt mặt đồng hồ trên vòng tay rồi thử lại.

## Khi vòng tay bị treo hoặc mất mặt đồng hồ

Nếu sau khi cài, vòng tay không còn mặt đồng hồ (mở thẳng vào menu ứng dụng) hoặc bị treo khi chọn mặt đó:

1. Ở trang **Thiết bị**, bấm **Ngắt kết nối** để điện thoại nối được với vòng tay. Nếu Mi Fitness vẫn không thấy vòng tay, tắt Bluetooth trên máy Mac một lát.
2. Mở **Mi Fitness** trên điện thoại → vòng tay → **Mặt đồng hồ**, cài một mặt bất kỳ trong cửa hàng. Mặt mới thay mặt bị lỗi. Nếu mặt lỗi có trong danh sách mặt đã cài, xóa nó ở đó.
3. **Đừng khôi phục cài đặt gốc** vòng tay: làm vậy mã xác thực đổi và ứng dụng này phải lấy lại mã mới.

## Mặt đồng hồ có sẵn

Vòng tay không gửi ảnh mặt đồng hồ qua Bluetooth, và tài liệu công khai duy nhất về giao thức (Gadgetbridge) không có lệnh hỏi mặt đang dùng của Mi Band 6. Mi Fitness hiện được là nhờ ảnh trong kho mặt đồng hồ trên máy chủ Xiaomi (API không công khai). Vì vậy hình vòng tay ở trang **Tổng quan** chỉ hiện mặt đồng hồ cài qua ứng dụng.

Khi chưa có ảnh nào, trang Tổng quan và khung mô phỏng hiện **mặt mặc định của ứng dụng**: giờ (theo kiểu 12/24 giờ đã lưu), ngày, nhịp tim, vòng bước chân và pin, cập nhật trực tiếp từ vòng tay. Đây là mặt do ứng dụng vẽ, không phải mặt đang hiện trên vòng tay.

Nếu bạn dùng mặt có sẵn và muốn trang Tổng quan hiện đúng: chụp ảnh màn hình vòng tay, chọn ảnh đó ở **Ảnh của bạn**, đặt **Giờ** là **Ẩn**, rồi bấm **Chỉ đặt làm ảnh xem trước** (không cài gì lên vòng tay). **Bỏ ảnh xem trước đã đặt** để xóa ảnh này.
