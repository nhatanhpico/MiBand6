# Mặt đồng hồ và ảnh nền

Thẻ **Cài đặt → Mặt đồng hồ** cài mặt đồng hồ lên Mi Band 6: dùng ảnh của bạn làm ảnh nền, hoặc cài một tệp mặt đồng hồ `.bin`. Có trong cả bản web và ứng dụng macOS.

## Khung mô phỏng

Bên trái là hình Mi Band 6 với màn hình đúng kích thước thật (152 × 486 điểm ảnh, bo góc như vòng tay). Nó hiện đúng thứ sẽ lên vòng tay trước khi bạn cài:

- ảnh nền đang chỉnh (kèm giờ),
- ảnh xem trước có sẵn trong tệp `.bin` vừa chọn,
- hoặc, khi chưa chọn gì, mặt đồng hồ đã cài qua ứng dụng.

## Dùng ảnh của bạn

1. Chọn thẻ **Ảnh của bạn**, bấm **Chọn ảnh…**. Ảnh lớn cỡ nào cũng được (ảnh chụp từ điện thoại vẫn được): ứng dụng tự thu nhỏ cho vừa màn hình vòng tay.
2. Trong khung chỉnh, phần sáng hình viên thuốc là phần hiện trên vòng tay; phần tối sẽ bị cắt. Kéo ảnh để di chuyển, cuộn chuột hoặc dùng thanh **Phóng to**. Bàn phím: phím mũi tên để dịch (giữ Shift để dịch nhanh), `+` / `-` để phóng to, thu nhỏ.
3. **Cách đặt ảnh**: **Lấp đầy** phủ kín màn hình (cắt bớt mép ảnh); **Trọn ảnh** giữ cả ảnh, chỗ trống để màu đen.
4. **Giờ**: hiện giờ và phút xếp chồng ở trên, giữa hoặc dưới, hoặc **Ẩn**. **Màu chữ số**: trắng (ảnh tối) hoặc đen (ảnh sáng).
5. Bấm **Cài lên vòng tay**. Thanh tiến độ cho biết phần đã gửi; vòng tay tự chuyển sang mặt mới khi xong.

Ứng dụng dựng một tệp mặt đồng hồ Mi Band 6 từ ảnh và các chữ số giờ (định dạng theo mô tả của dự án [watchface-js](https://github.com/Nadeflore/watchface-js)). Cách này chưa được thử trên nhiều vòng tay; nếu vòng tay từ chối, **Nhật ký Bluetooth** ở trang **Thiết bị** cho biết bước nào lỗi.

## Cài tệp .bin

1. Chọn thẻ **Tệp .bin**, bấm **Chọn tệp .bin…**. Tệp phải là mặt đồng hồ dành cho Mi Band 6 (bắt đầu bằng `UIHH`; tệp của Mi Band 5 hay vòng khác bị từ chối).
2. Ứng dụng đọc ảnh xem trước trong tệp và hiện ở khung mô phỏng. Một số tệp dùng ảnh nén mà ứng dụng chưa đọc được; tệp đó vẫn cài được, chỉ không có ảnh xem trước.
3. Bấm **Cài lên vòng tay**.

Cách cài giống Gadgetbridge. Vòng tay từ chối khi pin yếu hoặc không đủ chỗ trống: sạc vòng tay hoặc xóa bớt mặt đồng hồ trên vòng tay rồi thử lại.

## Mặt đồng hồ có sẵn

Vòng tay không gửi ảnh mặt đồng hồ qua Bluetooth, và tài liệu công khai duy nhất về giao thức (Gadgetbridge) không có lệnh hỏi mặt đang dùng của Mi Band 6. Mi Fitness hiện được là nhờ ảnh trong kho mặt đồng hồ trên máy chủ Xiaomi (API không công khai). Vì vậy hình vòng tay ở trang **Tổng quan** chỉ hiện mặt đồng hồ cài qua ứng dụng.

Khi chưa có ảnh nào, trang Tổng quan và khung mô phỏng hiện **mặt mặc định của ứng dụng**: giờ (theo kiểu 12/24 giờ đã lưu), ngày, nhịp tim, vòng bước chân và pin, cập nhật trực tiếp từ vòng tay. Đây là mặt do ứng dụng vẽ, không phải mặt đang hiện trên vòng tay.

Nếu bạn dùng mặt có sẵn và muốn trang Tổng quan hiện đúng: chụp ảnh màn hình vòng tay, chọn ảnh đó ở **Ảnh của bạn**, đặt **Giờ** là **Ẩn**, rồi bấm **Chỉ đặt làm ảnh xem trước** (không cài gì lên vòng tay). **Bỏ ảnh xem trước đã đặt** để xóa ảnh này.
