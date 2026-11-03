# Trang Sức khỏe

Trang **Sức khỏe** hiện dữ liệu Mi Band 6 đã ghi: giấc ngủ, bước chân, nhịp tim, căng thẳng, PAI, SpO2 và các buổi tập, kèm một bản **phân tích sức khỏe** dựa trên tất cả số liệu đó. Trang có trong cả bản web (`uv run miband6-web`) lẫn ứng dụng macOS.

## Đồng bộ

- Ứng dụng tự lấy dữ liệu mỗi lần kết nối vòng tay và mỗi 30 phút khi đang kết nối. Bấm **Đồng bộ** ở đầu trang để lấy ngay; dòng dưới tiêu đề cho biết đang lấy gì và lần đồng bộ gần nhất.
- Lần đầu ứng dụng lấy 30 ngày gần nhất, rồi một lần duy nhất hỏi vòng tay mọi dữ liệu cũ hơn mà nó còn giữ (dòng trạng thái ghi "dữ liệu cũ"), nên có thể mất vài phút. Các lần sau chỉ lấy phần mới.
- **Mi Fitness vẫn đồng bộ bình thường.** Ứng dụng chỉ sao chép: nó không gửi lệnh xác nhận "đã lấy xong", nên vòng tay vẫn giữ nguyên dữ liệu cho Mi Fitness.
- Dữ liệu được lưu trên máy tại `~/Library/Application Support/MiBand6Manager/health/` (mỗi vòng tay một tệp SQLite, chỉ tài khoản của bạn đọc được) và không gửi đi đâu.

Chọn ngày bằng nút ngày ở đầu trang (mở lịch; ngày có chấm xanh là ngày có dữ liệu, có sẵn nút **Hôm qua** / **Hôm nay**) hoặc hai nút ‹ ›; bấm vào một cột trong biểu đồ nhiều ngày để xem ngày đó.

## Các thẻ

| Thẻ | Nội dung |
| --- | --- |
| **Phân tích sức khỏe** | Nhận xét từng mặt (xem bên dưới) |
| **Giấc ngủ** | Giờ ngủ, giờ dậy, tổng thời gian; sơ đồ các giai đoạn (thức, ngủ nông, ngủ sâu, REM nếu vòng tay có ghi) theo giờ; 14 đêm gần đây so với khoảng khuyến nghị 7–9 giờ và mức trung bình của bạn |
| **Bước chân** | Bước theo giờ trong ngày; mọi ngày vòng tay đã ghi so với mục tiêu; **Xem dạng bảng** để xem số liệu từng ngày |
| **Nhịp tim** | Nhịp tim cả ngày (vùng tô là lúc ngủ), thấp nhất, trung bình, cao nhất |
| **Căng thẳng** | Mức căng thẳng tự đo (đường) và đo tay (chấm), nền chia theo mức Thư giãn / Bình thường / Trung bình / Cao |
| **PAI** | Tổng PAI 7 ngày và phần tăng mỗi ngày, so với mốc 100 |
| **SpO2** | Các lần đo nồng độ oxy trong máu |
| **Tập luyện** | Các buổi tập: loại, giờ bắt đầu, thời gian, quãng đường, năng lượng, nhịp tim trung bình, số bước và nguồn (vòng tay hoặc Mi Fitness) |
| **Đo tự động** | Cài đặt đo hiện tại và lối tắt tới **Cài đặt → Sức khỏe** |

Rê chuột (hoặc chọn bằng phím Tab) lên cột, đoạn hay đường trong biểu đồ để xem số liệu chi tiết.

### Lịch sử buổi tập từ Mi Fitness

Vòng tay chỉ giữ các buổi tập gần đây, và có thể xóa bớt sau khi Mi Fitness đồng bộ xong; lịch sử đầy đủ nằm trong tài khoản Mi Fitness. Bấm **Lấy lịch sử từ Mi Fitness** ở thẻ **Tập luyện**: ứng dụng dùng phiên đăng nhập Xiaomi đã lưu (hoặc hiện mã QR để đăng nhập, như nút **Đồng bộ** hồ sơ) rồi đọc các buổi tập 5 năm gần đây.

Sau lần đầu, việc này **tự chạy ngầm** mỗi khi kết nối vòng tay (nhiều nhất mỗi giờ một lần): ứng dụng lấy các buổi tập mới kể từ lần trước, cùng hồ sơ nếu đã hơn 12 giờ. Chạy ngầm không bao giờ hiện mã QR; nếu chưa đăng nhập hoặc phiên bị Xiaomi từ chối thì bỏ qua và ghi vào **Nhật ký Bluetooth**.

- Buổi tập trùng giờ bắt đầu (lệch không quá 3 phút) với buổi vòng tay đã ghi chỉ hiện một lần, dùng số liệu của vòng tay. Bấm lại nhiều lần không bị nhân đôi.
- Mi Fitness dùng mã loại bài tập khác vòng tay. Ứng dụng học cách đổi mã từ các buổi có cả hai nguồn; mã chưa biết hiện là "Bài tập (mã Mi Fitness …)".
- Ứng dụng chỉ đọc, không thay đổi gì trong tài khoản. Cách gọi API theo mô tả của dự án cộng đồng [mifit](https://github.com/Jenwein/mifit); Xiaomi không công bố API này nên có thể đổi bất cứ lúc nào.

### Bản đồ lộ trình

Mi Band 6 không có GPS: khi bạn tập chạy hoặc đạp xe ngoài trời với điện thoại, Mi Fitness ghi lộ trình bằng GPS của điện thoại và lưu trong tài khoản. Sau khi **Lấy lịch sử từ Mi Fitness**, các buổi có lộ trình hiện nút **Bản đồ**.

- Lần đầu mở, ứng dụng tải tệp lộ trình từ Mi Fitness (cần phiên đăng nhập Xiaomi còn hạn; nếu hết hạn, bấm **Lấy lịch sử từ Mi Fitness** để đăng nhập lại), giải mã rồi lưu trên máy; các lần sau mở ngay, không cần mạng cho phần lộ trình.
- **Ứng dụng macOS** mở lộ trình trong cửa sổ **Apple Maps** (MapKit): kéo, chụm hoặc cuộn để phóng to, có la bàn và thước tỉ lệ; ghim xanh là điểm bắt đầu, ghim đỏ là điểm kết thúc. Bản đồ nền do Apple cung cấp; lộ trình chỉ được vẽ trên máy.
- **Trình duyệt** dùng bản đồ dựng sẵn trong trang: kéo để di chuyển, cuộn chuột hoặc nút **+** / **−** để phóng to, nút khung vuông để xem trọn lộ trình. Bản đồ nền là ô ảnh của [OpenStreetMap](https://www.openstreetmap.org/copyright), tải trực tiếp từ máy chủ OpenStreetMap khi mở bản đồ (máy chủ đó biết khu vực đang xem, không nhận được lộ trình).
- Đọc được tệp lộ trình phiên bản 1, 2 (theo mô tả của dự án [mifit](https://github.com/Jenwein/mifit)) và 3 (Mi Fitness hiện nay, thêm độ cao; kiểm tra trên tệp thật). Tệp phiên bản mới hơn được dò cỡ dữ liệu tự động; nếu vẫn không đọc được, ứng dụng giữ tệp đã giải mã trong `health/gps-unread/` (chỉ trên máy bạn) để sửa bộ đọc.
- Quãng đường cộng từ các điểm GPS thường dài hơn số của Mi Fitness vài phần trăm vì GPS điện thoại dao động vài mét mỗi giây; Mi Fitness làm mượt lộ trình trước khi tính. Thẻ thống kê dùng số của Mi Fitness.

### Đo tự động

- **Nhịp tim** và **căng thẳng**: vòng tay tự đo theo **Cài đặt → Sức khỏe** (chu kỳ đo nhịp tim, Theo dõi căng thẳng). Không bật thì thẻ Căng thẳng trống.
- **SpO2**: Mi Band 6 chỉ đo khi bạn mở mục SpO2 trên vòng tay và bấm đo; ứng dụng không bật đo từ xa được (giao thức không có lệnh này). Kết quả hiện sau lần đồng bộ kế tiếp.

## Giấc ngủ được tính thế nào

Mi Band 6 ghi mỗi phút một mẫu. Byte đầu của mẫu là **mốc trạng thái** (4 bit thấp: 9 ngủ nông, 11 ngủ sâu, 12 thức dậy, 1 hoạt động), chỉ ghi ở phút trạng thái đổi; các phút giữa mang "không đổi". Ứng dụng đọc giống Gadgetbridge: mỗi phút mang trạng thái của mốc gần nhất trước nó.

Vòng tay ghi mốc ngủ và mốc dậy trễ chừng 10–12 phút. Để giờ ngủ, giờ dậy khớp với màn hình vòng tay và Mi Fitness, ứng dụng dùng thêm chỉ số "ngủ" vòng tay ghi mỗi phút: lúc thiếp đi là phút chỉ số này bắt đầu tăng, lúc dậy là phút nó tụt xuống. Mỗi đầu chỉ được chỉnh tối đa 30 phút, và bỏ qua nếu vòng tay không ghi chỉ số này.

Các khoảng thức ngắn hơn 45 phút ở giữa đêm vẫn tính là cùng một giấc (hiện ở hàng **Thức**); giấc ngắn hơn 20 phút bị bỏ qua. Mỗi giấc được tính cho ngày bạn thức dậy, như Mi Fitness.

## Phân tích sức khỏe

Thẻ đầu trang nhận xét tình trạng hiện tại từ dữ liệu 7–30 ngày gần nhất, theo khuyến nghị chung cho người lớn. Mỗi mục có nhãn **Tốt**, **Ổn**, **Nên chú ý** hoặc **Cần lưu ý** (kèm biểu tượng, không chỉ dựa vào màu) và một dòng giải thích.

| Mục | Tính từ | Tốt | Ổn / Nên chú ý / Cần lưu ý |
| --- | --- | --- | --- |
| Thời gian ngủ | Trung bình 7 đêm gần nhất có dữ liệu | 7–9,5 giờ | Nên chú ý: 6–7 giờ hoặc trên 9,5 giờ; Cần lưu ý: dưới 6 giờ |
| Ngủ sâu | Phần trăm ngủ sâu trong giấc ngủ | Từ 13% | Ổn: 10–13%; Nên chú ý: dưới 10% |
| Giờ đi ngủ đều đặn | Độ lệch giờ đi ngủ giữa các đêm | ±45 phút | Ổn: tới ±90 phút; Nên chú ý: hơn nữa |
| Nhịp tim nghỉ | Trung vị nhịp tim khi ngủ, trung bình 7 đêm | 40–75 nhịp/phút | Ổn: tới 80; Nên chú ý: trên 80, hoặc cao hơn tuần trước từ 5 nhịp/phút |
| Bước chân | Trung bình 7 ngày đã trọn (ngày có ít nhất 10 giờ dữ liệu) | Đạt mục tiêu bước | Ổn: từ 60% mục tiêu; Nên chú ý: thấp hơn |
| Vận động | Phút đi bộ nhanh (từ 100 bước/phút) và tập luyện trong 7 ngày | Từ 150 phút | Ổn: 75–150; Nên chú ý: dưới 75 |
| PAI | Tổng PAI mới nhất | Từ 100 | Ổn: 50–100; Nên chú ý: dưới 50 |
| SpO2 | Các lần đo 30 ngày | Thấp nhất từ 95% | Ổn: 92–94%; Nên chú ý: 90–91%; Cần lưu ý: dưới 90% |
| Căng thẳng | Trung bình số đo tự động 7 ngày | Dưới 40 | Ổn: 40–59; Nên chú ý: từ 60 |
| Dữ liệu | Thời điểm của dữ liệu mới nhất | | Nên chú ý: cũ hơn 2 ngày |

Mục nào chưa có dữ liệu thì không hiện (hoặc hiện **Chưa đủ dữ liệu**). Các ngưỡng lấy từ khuyến nghị phổ biến: ngủ 7–9 giờ mỗi đêm, 150 phút vận động vừa mỗi tuần (WHO), PAI từ 100, SpO2 bình thường từ 95%.

> Phân tích chỉ để tham khảo, không phải chẩn đoán. Cảm biến đeo tay có sai số, nhất là SpO2. Nếu thấy bất thường kéo dài hoặc có triệu chứng (khó thở, đau ngực, mệt bất thường), hãy hỏi ý kiến bác sĩ.

## Khắc phục sự cố

| Hiện tượng | Cách xử lý |
| --- | --- |
| Trang trống, "Chưa có dữ liệu" | Kết nối vòng tay rồi bấm **Đồng bộ**; lần đầu có thể mất một hai phút. |
| Giấc ngủ trống trong khi vòng tay có | Chọn đúng ngày thức dậy (giấc đêm qua nằm ở ngày hôm nay). Bấm **Đồng bộ** nếu vừa thức dậy. |
| Giờ ngủ lệch vài phút so với vòng tay | Vòng tay làm tròn theo cách riêng; tổng thời gian thường khớp tới từng phút. |
| Thẻ Căng thẳng trống | Bật **Theo dõi căng thẳng** ở **Cài đặt → Sức khỏe**. |
| Dòng dưới tiêu đề ghi "chưa lấy được: …" | Mục đó lỗi ở lần đồng bộ (thường do mất kết nối giữa chừng); bấm **Đồng bộ** lại. Chi tiết nằm trong **Nhật ký Bluetooth** ở trang **Thiết bị**. |
