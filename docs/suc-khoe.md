# Trang Sức khỏe

Trang **Sức khỏe** hiện dữ liệu Mi Band 6 đã ghi: giấc ngủ, bước chân, nhịp tim, căng thẳng, PAI, SpO2 và các buổi tập, kèm một bản **phân tích sức khỏe**, **mức sẵn sàng**, **trạng thái tinh thần** (ước tính), **cường độ vận động** và **nhịp sinh học** dựa trên tất cả số liệu đó. Trang có trong cả bản web (`uv run miband6-web`) lẫn ứng dụng macOS.

## Đồng bộ

- Ứng dụng tự lấy dữ liệu mỗi lần kết nối vòng tay và theo lịch ở **Cài đặt ứng dụng → Tự đồng bộ** (mặc định mỗi 30 phút khi đang kết nối; có thể chọn 15 phút tới 2 giờ, hoặc chỉ khi bấm). Bấm **Đồng bộ** ở đầu trang để lấy ngay; dòng dưới tiêu đề cho biết đang lấy gì và lần đồng bộ gần nhất.
- Lần đầu ứng dụng lấy 30 ngày gần nhất, rồi một lần duy nhất hỏi vòng tay mọi dữ liệu cũ hơn mà nó còn giữ (dòng trạng thái ghi "dữ liệu cũ"), nên có thể mất vài phút. Các lần sau chỉ lấy phần mới.
- **Mi Fitness vẫn đồng bộ bình thường.** Ứng dụng chỉ sao chép: nó không gửi lệnh xác nhận "đã lấy xong", nên vòng tay vẫn giữ nguyên dữ liệu cho Mi Fitness.
- Dữ liệu được lưu trên máy tại `~/Library/Application Support/MiBand6Manager/health/` (mỗi vòng tay một tệp SQLite, chỉ tài khoản của bạn đọc được) và không gửi đi đâu.

Chọn ngày bằng nút ngày ở đầu trang (mở lịch; ngày có chấm xanh là ngày có dữ liệu, có sẵn nút **Hôm qua** / **Hôm nay**) hoặc hai nút ‹ ›; bấm vào một cột trong biểu đồ nhiều ngày để xem ngày đó.

## Các thẻ

| Thẻ | Nội dung |
| --- | --- |
| **Điểm sẵn sàng hôm nay** | Điểm 0–100 và lời khuyên hôm nay nên tập nặng, tập vừa, tập nhẹ hay nghỉ; 7 thành phần, thời gian hồi phục và xu hướng 14 ngày (xem bên dưới) |
| **Phân tích sức khỏe** | Nhận xét từng mặt (xem bên dưới) |
| **Trạng thái tinh thần** | Ước tính trạng thái (Thư thái, Cân bằng, Căng thẳng, Mệt mỏi, Quá tải), mức áp lực và các yếu tố góp phần |
| **Cường độ vận động** | Tỉ lệ cường độ vận động 7 ngày và số phút nhẹ / vừa / mạnh mỗi ngày |
| **Nhịp sinh học** | Lệch múi giờ xã hội, chronotype, độ đều đặn giấc ngủ (SRI), độ lệch pha (CPD) và giờ ngủ từng đêm |
| **Giấc ngủ** | Giờ ngủ, giờ dậy, tổng thời gian; sơ đồ các giai đoạn (thức, ngủ nông, ngủ sâu, REM ước tính) theo giờ; 14 đêm gần đây so với khoảng khuyến nghị 7–9 giờ và mức trung bình của bạn |
| **Bước chân** | Bước theo giờ trong ngày; mọi ngày vòng tay đã ghi so với mục tiêu; **Xem dạng bảng** để xem số liệu từng ngày |
| **Nhịp tim** | Nhịp tim cả ngày (vùng tô là lúc ngủ), thấp nhất, trung bình, cao nhất |
| **Căng thẳng** | Mức căng thẳng tự đo (đường) và đo tay (chấm), nền chia theo mức Thư giãn / Bình thường / Trung bình / Cao |
| **PAI** | Tổng PAI 7 ngày và phần tăng mỗi ngày, so với mốc 100 |
| **SpO2** | Các lần đo nồng độ oxy trong máu |
| **Tập luyện** | Các buổi tập: loại, giờ bắt đầu, thời gian, quãng đường, năng lượng, nhịp tim trung bình, số bước và nguồn (vòng tay hoặc Mi Fitness) |
| **Đo tự động** | Cài đặt đo hiện tại và lối tắt tới **Cài đặt vòng tay → Sức khỏe** |

Rê chuột (hoặc chọn bằng phím Tab) lên cột, đoạn hay đường trong biểu đồ để xem số liệu chi tiết.

### Lịch sử buổi tập từ Mi Fitness

Vòng tay chỉ giữ các buổi tập gần đây, và có thể xóa bớt sau khi Mi Fitness đồng bộ xong; lịch sử đầy đủ nằm trong tài khoản Mi Fitness. Bấm **Lấy lịch sử từ Mi Fitness** ở thẻ **Tập luyện**: ứng dụng dùng phiên đăng nhập Xiaomi đã lưu (hoặc hiện mã QR để đăng nhập, như nút **Đồng bộ** hồ sơ) rồi đọc các buổi tập 5 năm gần đây.

Sau lần đầu, việc này **tự chạy ngầm** theo lịch ở **Cài đặt ứng dụng → Tự đồng bộ** (mặc định mỗi giờ, cả khi vòng tay không kết nối; có thể chọn tới mỗi ngày, hoặc chỉ khi bấm): ứng dụng lấy các buổi tập mới kể từ lần trước, cùng hồ sơ nếu đã hơn 12 giờ. Chạy ngầm không bao giờ hiện mã QR; nếu chưa đăng nhập hoặc phiên bị Xiaomi từ chối thì bỏ qua và ghi vào **Nhật ký Bluetooth**. Trạng thái đăng nhập, **Gia hạn ngay**, **Đăng nhập lại** và **Đăng xuất** nằm ở **Cài đặt ứng dụng → Tài khoản Mi Fitness**.

- Buổi tập trùng giờ bắt đầu (lệch không quá 3 phút) với buổi vòng tay đã ghi chỉ hiện một lần, dùng số liệu của vòng tay. Bấm lại nhiều lần không bị nhân đôi.
- Mi Fitness dùng mã loại bài tập khác vòng tay. Ứng dụng học cách đổi mã từ các buổi có cả hai nguồn; mã chưa biết hiện là "Bài tập (mã Mi Fitness …)".
- Ứng dụng chỉ đọc, không thay đổi gì trong tài khoản. Cách gọi API theo mô tả của dự án cộng đồng [mifit](https://github.com/Jenwein/mifit); Xiaomi không công bố API này nên có thể đổi bất cứ lúc nào.

### Bản đồ lộ trình

Mi Band 6 không có GPS: khi bạn tập chạy hoặc đạp xe ngoài trời với điện thoại, Mi Fitness ghi lộ trình bằng GPS của điện thoại và lưu trong tài khoản. Sau khi **Lấy lịch sử từ Mi Fitness**, các buổi có lộ trình hiện nút **Bản đồ**.

- Ứng dụng **tải sẵn ở nền** mọi lộ trình còn thiếu (khi server khởi động và sau mỗi lần lấy lịch sử), giải mã rồi lưu trên máy, nên bấm **Bản đồ** là mở ngay. Mỗi lộ trình tải trong khoảng 1 giây. (Trước đây mất tới 60 giây mỗi lộ trình: tên máy chủ tệp của Xiaomi trỏ tới ba địa chỉ IP, và từ một số mạng hai địa chỉ không trả lời. Ứng dụng giờ thử mọi địa chỉ cùng lúc, như trình duyệt, và nhớ địa chỉ trả lời nhanh.) Cần phiên đăng nhập Xiaomi còn hạn; nếu hết hạn, bấm **Lấy lịch sử từ Mi Fitness** để đăng nhập lại.
- Bản đồ mở trong một hộp thoại ngay trong ứng dụng, không mở cửa sổ mới. Chấm xanh là điểm bắt đầu, chấm đỏ là điểm kết thúc.
- **Ứng dụng macOS** dùng **Apple Maps** (MapKit) gắn ngay trong hộp thoại: kéo, chụm hoặc cuộn để di chuyển, phóng to; nút mũi tên ở góc trên trái để xem trọn lộ trình; phím Esc để đóng. Bản đồ nền do Apple cung cấp.
- **Trình duyệt** không có Apple Maps: khung bản đồ báo cần ứng dụng macOS, kèm nút **Mở trong ứng dụng** (liên kết `miband6://`) mở đúng bản đồ đó trong ứng dụng. Số liệu và bộ lọc vẫn hiện trên trình duyệt.
- **Chia sẻ ảnh** (ứng dụng macOS): lưu ảnh PNG của bản đồ đang xem, kèm lộ trình, tiêu đề, ngày và số liệu, vào thư mục **Tải về**, rồi mở bảng chia sẻ của macOS (AirDrop, Tin nhắn, Mail…).
- **Lọc theo nơi** (bản đồ **Những nơi đã đến**): chọn một quốc gia hoặc thành phố để chỉ hiện các lộ trình ở đó; bản đồ tự vừa khung và số liệu tính lại theo lựa chọn. Tên nơi được tra một lần cho mỗi vùng khoảng 1 km quanh điểm đầu lộ trình, bằng dịch vụ Nominatim của OpenStreetMap (gửi tọa độ đã làm tròn, tối đa 1 yêu cầu mỗi giây), rồi lưu trên máy.
- **Những nơi đã đến** (nút ở đầu thẻ **Tập luyện**) gom mọi lộ trình lên một bản đồ, tô màu theo loại: cam là chạy bộ, xanh lá là đi bộ, xanh dương là đạp xe. Bấm nút của từng loại để ẩn, hiện; bấm vào một lộ trình để xem buổi tập đó (nút **Tất cả lộ trình** để quay lại). Dưới bản đồ là số lộ trình, tổng quãng đường, thời gian và số ngày của các loại đang hiện.
- Ô bản đồ do Apple cung cấp; lộ trình chỉ được vẽ trên máy.
- Đọc được tệp lộ trình phiên bản 1, 2 (theo mô tả của dự án [mifit](https://github.com/Jenwein/mifit)) và 3 (Mi Fitness hiện nay, thêm độ cao; kiểm tra trên tệp thật). Tệp phiên bản mới hơn được dò cỡ dữ liệu tự động; nếu vẫn không đọc được, ứng dụng giữ tệp đã giải mã trong `health/gps-unread/` (chỉ trên máy bạn) để sửa bộ đọc.
- Quãng đường cộng từ các điểm GPS thường dài hơn số của Mi Fitness vài phần trăm vì GPS điện thoại dao động vài mét mỗi giây; Mi Fitness làm mượt lộ trình trước khi tính. Thẻ thống kê dùng số của Mi Fitness.

### Đo tự động

- **Nhịp tim** và **căng thẳng**: vòng tay tự đo theo **Cài đặt vòng tay → Sức khỏe** (chu kỳ đo nhịp tim, Theo dõi căng thẳng). Không bật thì thẻ Căng thẳng trống.
- **SpO2**: Mi Band 6 chỉ đo khi bạn mở mục SpO2 trên vòng tay và bấm đo; ứng dụng không bật đo từ xa được (giao thức không có lệnh này). Kết quả hiện sau lần đồng bộ kế tiếp.

## Giấc ngủ được tính thế nào

Mi Band 6 ghi mỗi phút một mẫu. Byte đầu của mẫu là **mốc trạng thái** (4 bit thấp: 9 ngủ nông, 11 ngủ sâu, 12 thức dậy, 1 hoạt động), chỉ ghi ở phút trạng thái đổi; các phút giữa mang "không đổi". Ứng dụng đọc giống Gadgetbridge: mỗi phút mang trạng thái của mốc gần nhất trước nó.

Vòng tay ghi mốc ngủ và mốc dậy trễ chừng 10–12 phút. Để giờ ngủ, giờ dậy khớp với màn hình vòng tay và Mi Fitness, ứng dụng dùng thêm chỉ số "ngủ" vòng tay ghi mỗi phút: lúc thiếp đi là phút chỉ số này bắt đầu tăng, lúc dậy là phút nó tụt xuống. Mỗi đầu chỉ được chỉnh tối đa 30 phút, và bỏ qua nếu vòng tay không ghi chỉ số này.

Các khoảng thức ngắn hơn 45 phút ở giữa đêm vẫn tính là cùng một giấc (hiện ở hàng **Thức**); giấc ngắn hơn 20 phút bị bỏ qua. Mỗi giấc được tính cho ngày bạn thức dậy, như Mi Fitness. Giấc còn đang ngủ (kéo tới phút mới nhất đã đồng bộ, vòng tay chưa ghi lúc thức dậy) chưa được tính là "đêm qua": đồng bộ lúc nửa đêm thì đêm qua không còn bị tính là giấc ngủ chỉ vài chục phút, kéo lệch điểm ngủ, mức sẵn sàng và phân tích.

### REM (ước tính)

[Xiaomi công bố hỗ trợ REM](https://www.mi.com/sg/support/faq/details/KA-07049/), nhưng bộ giải mã Bluetooth của ứng dụng chưa xác minh được REM của hãng. Byte REM bằng 0 trong các dữ liệu đã quan sát không chứng minh rằng thiết bị hoặc mọi ứng dụng đồng hành không hỗ trợ REM. Tùy chọn dưới đây là ước tính riêng từ nhịp tim, chưa được kiểm chứng với PSG và không phải kết quả REM của Xiaomi:

- Khi ngủ REM cơ thể gần như bất động, nhưng nhịp tim tăng so với nền NREM và dao động nhiều hơn.
- Chỉ xét giấc từ 3 giờ trở lên có nhịp tim ở ít nhất 80% số phút. Bật **Cài đặt vòng tay → Sức khỏe → Hỗ trợ giấc ngủ** để vòng tay đo nhịp tim mỗi phút khi ngủ; đêm không đủ thì không ước tính.
- Nền NREM là phân vị 30% của nhịp tim (đã làm mượt 3 phút) trong cửa sổ 61 phút quanh mỗi phút. Phút "ngủ nông" ít cử động, sau ít nhất 60 phút từ lúc ngủ, có nhịp tim cao hơn nền từ 4 nhịp/phút (hoặc dao động trong 9 phút từ 1,6 lần mức thường của đêm và cao hơn nền 2 nhịp/phút) được xem là REM. Các đoạn cách nhau tới 10 phút được nối; đoạn ngắn hơn 6 phút bị bỏ.
- Nếu REM vượt 30% thời gian ngủ, ngưỡng được nâng dần (người lớn khỏe thường có 20–25% REM).

Trên dữ liệu thật, cách này cho 15–29% REM mỗi đêm, giai đoạn REM đầu tiên sau khối ngủ sâu đầu đêm, lặp lại mỗi 60–90 phút và dài dần về sáng, đúng cấu trúc giấc ngủ thường gặp. Chưa có phép đo đa ký giấc ngủ để đối chiếu, nên đây chỉ là ước tính: các thiết bị đeo chuyên dụng dùng nhịp tim và HRV chỉ nhận ra REM với độ nhạy khoảng 60% (Firstbeat, Kuula & Pesonen 2021). Tắt REM ở **Cài đặt ứng dụng → Giấc ngủ REM** thì REM được gộp lại vào ngủ nông.

## Phân tích sức khỏe

Thẻ đầu trang nhận xét tình trạng hiện tại từ dữ liệu 7–30 ngày gần nhất, theo khuyến nghị chung cho người lớn. Mỗi mục có nhãn **Tốt**, **Ổn**, **Nên chú ý** hoặc **Cần lưu ý** (kèm biểu tượng, không chỉ dựa vào màu) và một dòng giải thích.

| Mục | Tính từ | Tốt | Ổn / Nên chú ý / Cần lưu ý |
| --- | --- | --- | --- |
| Thời gian ngủ | Trung bình 7 đêm gần nhất có dữ liệu | 7–9,5 giờ | Nên chú ý: 6–7 giờ hoặc trên 9,5 giờ; Cần lưu ý: dưới 6 giờ |
| Ngủ sâu | Phần trăm ngủ sâu trong giấc ngủ | Từ 13% | Ổn: 10–13%; Nên chú ý: dưới 10% |
| Giờ đi ngủ đều đặn | Độ lệch giờ đi ngủ giữa các đêm | ±45 phút | Ổn: tới ±90 phút; Nên chú ý: hơn nữa |
| Nhịp tim nghỉ | Trung vị nhịp tim khi ngủ, trung bình 7 đêm | 40–75 nhịp/phút | Ổn: tới 80; Nên chú ý: trên 80, hoặc cao hơn tuần trước từ 5 nhịp/phút |
| Bước chân | Trung bình 7 ngày đã trọn (ngày đeo vòng ít nhất 10 giờ; vòng tay vẫn ghi mỗi phút khi tháo ra, nên đếm phút đeo, không đếm bản ghi) | Đạt mục tiêu bước | Ổn: từ 60% mục tiêu; Nên chú ý: thấp hơn |
| Vận động | Phút đi bộ nhanh (từ 100 bước/phút) và tập luyện trong 7 ngày | Từ 150 phút | Ổn: 75–150; Nên chú ý: dưới 75 |
| PAI | Tổng PAI mới nhất | Từ 100 | Ổn: 50–100; Nên chú ý: dưới 50 |
| SpO2 | Các lần đo 30 ngày | Thấp nhất từ 95% | Ổn: 92–94%; Nên chú ý: 90–91%; Cần lưu ý: dưới 90% |
| Căng thẳng | Trung bình số đo tự động 7 ngày | Dưới 40 | Ổn: 40–59; Nên chú ý: từ 60 |
| Dữ liệu | Thời điểm của dữ liệu mới nhất | | Nên chú ý: cũ hơn 2 ngày |

Mục nào chưa có dữ liệu thì không hiện (hoặc hiện **Chưa đủ dữ liệu**). Các ngưỡng lấy từ khuyến nghị phổ biến: ngủ 7–9 giờ mỗi đêm, 150 phút vận động vừa mỗi tuần (WHO), PAI từ 100, SpO2 bình thường từ 95%.

> Phân tích chỉ để tham khảo, không phải chẩn đoán. Cảm biến đeo tay có sai số, nhất là SpO2. Nếu thấy bất thường kéo dài hoặc có triệu chứng (khó thở, đau ngực, mệt bất thường), hãy hỏi ý kiến bác sĩ.

## Điểm sẵn sàng hôm nay

Thẻ đầu tiên của trang. Điểm 0–100 trả lời câu hỏi **hôm nay nên tập hay nên nghỉ**, như Readiness của Apple Watch, Physical Readiness của Huawei Watch GT 7 hay Training Readiness của Garmin. Các hãng không công bố công thức, nhưng cùng dựa trên ba nhóm dữ liệu so với **mức nền của chính bạn**: giấc ngủ (đêm qua và các đêm gần đây), chỉ số cơ thể (nhịp tim nghỉ, HRV) và tải vận động (các ngày gần đây và thời gian hồi phục). Ứng dụng làm theo cấu trúc đó; trọng số và ngưỡng dưới đây là lựa chọn của ứng dụng.

| Thành phần (trọng số) | Tính từ | 100 điểm khi |
| --- | --- | --- |
| Nhịp tim nghỉ (18%) | Trung vị nhịp tim khi ngủ đêm qua so với 30 đêm trước (cần ít nhất 7) | Không cao hơn mức nền quá 0,5 độ lệch chuẩn; mỗi độ lệch chuẩn thêm trừ khoảng 25 điểm |
| Chỉ số hồi phục (8%) | Thời điểm trung bình 5 phút của nhịp tim thấp nhất, tính theo phần đêm đã qua (như Oura) | Thấp nhất trong nửa đầu đêm (75% đêm: 60 điểm) |
| Giấc ngủ đêm qua (20%) | Thời lượng (50%), tỉ lệ thời gian trên giường là ngủ (15%), phần ngủ sâu (15%), giờ ngủ so với chronotype (20%) | Ngủ 7,5–9 giờ, liền mạch từ 95%, ngủ sâu từ 16%, giữa giấc lệch chronotype dưới 30 phút |
| Cân bằng giấc ngủ (14%) | Ngủ 14 đêm so với nhu cầu 7,5 giờ (đêm gần nặng hơn), kèm nợ ngủ 7 đêm | Đạt 100% nhu cầu |
| Thời gian hồi phục (15%) | Mệt mỏi từ tải vận động các giờ gần đây (xem dưới), như "recovery time" của Garmin | Đã hồi phục (12 giờ: 80; 24 giờ: 60; 48 giờ: 35) |
| Cân bằng vận động (10%) | Tỉ lệ tải cấp/tải mạn (ACWR, Gabbett): TRIMP trung bình 7 ngày / 28 ngày đủ dữ liệu tải (cần 14 ngày, xem dưới) | Trong khoảng 0,8–1,3 (1,5: 75; 2: 45) |
| Cân bằng căng thẳng, thay cho HRV (15%) | Chỉ số căng thẳng của vòng tay 2 ngày gần nhất so với mức nền | Không cao hơn mức nền; từ 60 trở lên tối đa 70 điểm |

**Thời gian hồi phục** dùng mô hình thể lực - mệt mỏi kiểu Banister, rút gọn: mỗi giờ có tải (TRIMP) cộng vào "mệt mỏi", mờ dần theo e^(−t/36 giờ). Với tải đều đặn C mỗi ngày (trung bình 28 ngày đủ dữ liệu tải, tối thiểu 30), mệt mỏi ổn định quanh C × 36/24; thời gian hồi phục còn lại = 36 × ln(mệt mỏi / mức ổn định) giờ, tối đa 96. Tải trong hôm nay cũng được tính, nên điểm hôm nay giảm ngay sau một buổi tập (như Apple Watch). Ví dụ: buổi tập TRIMP 450 với người thường có 100 mỗi ngày, 20 giờ sau còn khoảng 19,5 giờ hồi phục.

**TRIMP** (tải vận động) theo Edwards: mỗi phút ở 50–60 / 60–70 / 70–80 / 80–90 / 90–100% nhịp tim tối đa tính 1 / 2 / 3 / 4 / 5 điểm; nhịp tim tối đa = 208 − 0,7 × tuổi (Tanaka 2001, tuổi lấy từ hồ sơ).

Vòng tay đo nhịp tim theo chu kỳ đã cài (mỗi phút, 5, 10 hay 30 phút), và chu kỳ có thể đổi giữa các ngày. Mỗi số đo được tính cho khoảng tới số đo kế tiếp, **tối đa 10 phút** và không kéo qua lúc tháo vòng, nên tải một ngày không phụ thuộc chu kỳ đo; nếu chỉ cộng các phút có số đo, ngày đo mỗi 10 phút trông nhẹ hơn chừng 10 lần, mức nền bị kéo thấp và một ngày bình thường bị coi là quá tải. Một ngày chỉ vào **mức nền tải** (thời gian hồi phục, cân bằng vận động) khi đeo vòng ít nhất 10 giờ và có nhịp tim ít nhất 60% thời gian đeo; ngày đo mỗi 30 phút hay tắt đo nhịp tim bị bỏ ra thay vì coi là ngày nghỉ. Phút đeo vòng: vòng tay không ghi "không đeo" / "đang sạc", hoặc có nhịp tim.

**Điểm và lời khuyên**

- Điểm là trung bình có trọng số của các thành phần có dữ liệu (cần ít nhất 3, trong đó có nhịp tim nghỉ hoặc giấc ngủ đêm qua). Nếu một thành phần cơ thể (mọi thành phần trừ Cân bằng vận động) dưới 40, điểm không vượt 59. Cân bằng vận động chỉ góp theo trọng số: nó là xu hướng tải theo tuần, khả năng dự báo chấn thương của ACWR còn tranh cãi (Impellizzeri 2020), và nó nhảy vọt khi lịch đeo vòng thay đổi; một mình nó không biến ngày khỏe thành ngày "nên tập nhẹ".
- Mức và gợi ý tập (vùng nhịp tim theo % nhịp tim tối đa của bạn):

| Điểm | Lời khuyên | Gợi ý |
| --- | --- | --- |
| 80–100 | **Sẵn sàng tập nặng** | Chạy nhanh, interval, sức mạnh nặng; nhịp tim có thể lên vùng 4–5 (80–100%) |
| 60–79 | **Sẵn sàng tập luyện** | Tập như kế hoạch ở cường độ vừa, vùng 2–3 (60–80%) |
| 40–59 | **Nên tập nhẹ** | Đi bộ, đạp xe chậm, yoga, giãn cơ, dưới 70% |
| 0–39 | **Nên nghỉ ngơi** | Ngủ sớm, đi lại nhẹ nhàng, uống đủ nước |

- Dù các thành phần khác tốt, lời khuyên và điểm bị hạ khi cơ thể chưa sẵn sàng (như Garmin: còn hồi phục thì điểm thấp): còn từ 24 giờ hồi phục hoặc nhịp tim nghỉ tăng mạnh (thành phần dưới 40) thì tối đa "Nên tập nhẹ" (điểm tối đa 59); còn từ 12 giờ hồi phục thì tối đa "Sẵn sàng tập luyện" (điểm tối đa 79).
- Dòng thứ hai giải thích thành phần thấp nhất. Biểu đồ dưới thẻ là điểm 14 ngày gần đây (các ngày trước tính lúc 8 giờ sáng).
- **Điều chỉnh cho Mi Band 6:** Apple, Huawei, Garmin và Oura dùng HRV, nhiệt độ da; Mi Band 6 không cho đọc HRV thô hay nhiệt độ. "HRV" được thay bằng chỉ số căng thẳng của vòng tay (vòng tay tính nó từ HRV), không có thành phần nhiệt độ.
- Cần đeo vòng khi ngủ ít nhất 8 đêm (Apple cần 7 đêm, Huawei 3 ngày đêm) để có mức nền; trước đó thẻ hiện số đêm đã có.

## Trạng thái tinh thần (ước tính)

Ước tính có giải thích, **không phải chẩn đoán**. Dựa trên các yếu tố mà nghiên cứu cho thấy liên quan tới tâm trạng: căng thẳng (HRV), thiếu ngủ và thời gian thức dài (nghiên cứu 2.602 bác sĩ nội trú, *PLOS Digital Health* 2024), lệch nhịp sinh học (dịch pha nhịp sinh học là yếu tố dự báo mạnh nhất cho giai đoạn khí sắc, *npj Digital Medicine* 2024), nhịp tim nghỉ tăng và ít vận động.

| Yếu tố (trọng số) | Nhóm | Mức 0 → 1 |
| --- | --- | --- |
| Căng thẳng trung bình 3 ngày (35%) | Căng | 25 → 75, cộng thêm nửa tỉ lệ số đo ở mức cao |
| Giấc ngủ 3 đêm và nợ ngủ 7 đêm (25%) | Mệt | 7,5 giờ → 5 giờ, cộng tối đa 0,4 cho nợ ngủ (15 giờ) |
| Áp lực nhịp sinh học (15%) | Mệt | Từ CPD (0,5 → 2,5 giờ) và lệch múi giờ xã hội (0 → 2 giờ) |
| Nhịp tim nghỉ so với mức nền (15%) | Căng | 0 → 2,5 độ lệch chuẩn |
| Vận động vừa/mạnh 7 ngày (10%) | Mệt | 150 → 0 phút |

**Áp lực tổng** là trung bình có trọng số (0–100). Trạng thái theo hai nhóm: cả "căng" và "mệt" từ 50 là **Quá tải**; chỉ căng là **Căng thẳng**; chỉ mệt là **Mệt mỏi**; căng dưới 25 và mệt dưới 30 là **Thư thái**; còn lại **Cân bằng**. Độ tin cậy cao khi có từ 40 số đo căng thẳng trong 3 ngày và 3 đêm dữ liệu.

## Cường độ vận động

**Tỉ lệ cường độ vận động** = phút vừa + mạnh / tổng phút vận động (nhẹ + vừa + mạnh), 7 ngày gần nhất.

- Mỗi phút xếp theo nhịp bước (CADENCE-Adults, Tudor-Locke và cộng sự): 20–99 bước/phút là nhẹ, 100–129 là vừa (khoảng 3 MET), từ 130 là mạnh (khoảng 6 MET).
- Trong buổi tập (kể cả đạp xe, không có bước) dùng nhịp tim dự trữ (ACSM): từ 40% là vừa, từ 60% là mạnh; nhịp tim nghỉ lấy từ giấc ngủ.
- Từ 25% là **tốt**, 10–25% là **ổn**, dưới 10% là **thấp**. Kèm số phút tương đương vận động vừa mỗi tuần (phút mạnh tính gấp đôi, như WHO) để so với khuyến nghị 150 phút.

## Nhịp sinh học

Dùng giấc ngủ chính mỗi đêm (giấc dài nhất kết thúc trong ngày), 28 đêm gần nhất. Đêm trước ngày nghỉ là đêm thức dậy vào thứ Bảy, Chủ nhật.

- **Lệch múi giờ xã hội** (social jetlag, Wittmann 2006; MCTQ của Roenneberg): |MSF − MSW|, với MSW, MSF là giờ giữa giấc trung bình đêm trước ngày làm việc / ngày nghỉ. Dưới 1 giờ là tốt.
- **Chronotype (MSFsc)**: giờ giữa giấc ngày nghỉ, hiệu chỉnh ngủ bù: nếu ngày nghỉ ngủ dài hơn ngày làm, MSFsc = MSF − (SDf − SDtuần)/2, với SDtuần = (5 × SDw + 2 × SDf)/7.
- **Độ lệch pha tổng hợp (CPD**, Fischer, Vetter, Roenneberg 2016): mỗi đêm √((giữa giấc − chronotype)² + (giữa giấc − giữa giấc đêm trước)²), trung bình 14 đêm, tính bằng giờ. Dưới 1 giờ là ổn định.
- **Độ đều đặn giấc ngủ (SRI**, Phillips 2017): −100 + 200 × xác suất mỗi phút có cùng trạng thái ngủ/thức với đúng 24 giờ sau, trong 14 ngày (chỉ tính các cặp phút có đeo vòng). 100 là hoàn toàn đều, 0 là ngẫu nhiên; ứng dụng coi dưới 60 là không đều.
- **Áp lực nhịp sinh học** (0–100) do ứng dụng định nghĩa: trung bình có trọng số của lệch múi giờ xã hội (35%, 2 giờ = 100), CPD (35%, 0,5 → 2,5 giờ) và SRI (30%, 85 → 40). Dưới 30 là **thấp**, 30–60 **vừa**, trên 60 **cao**.

> Các chỉ số trên chỉ để tham khảo, không phải chẩn đoán. Nếu buồn chán, lo âu hoặc mất ngủ kéo dài trên hai tuần, hãy trò chuyện với người thân hoặc chuyên gia sức khỏe tâm thần.

## Khắc phục sự cố

| Hiện tượng | Cách xử lý |
| --- | --- |
| Trang trống, "Chưa có dữ liệu" | Kết nối vòng tay rồi bấm **Đồng bộ**; lần đầu có thể mất một hai phút. |
| Giấc ngủ trống trong khi vòng tay có | Chọn đúng ngày thức dậy (giấc đêm qua nằm ở ngày hôm nay). Bấm **Đồng bộ** nếu vừa thức dậy. |
| Giờ ngủ lệch vài phút so với vòng tay | Vòng tay làm tròn theo cách riêng; tổng thời gian thường khớp tới từng phút. |
| Thẻ Căng thẳng trống | Bật **Theo dõi căng thẳng** ở **Cài đặt vòng tay → Sức khỏe**. |
| Dòng dưới tiêu đề ghi "chưa lấy được: …" | Mục đó lỗi ở lần đồng bộ (thường do mất kết nối giữa chừng); bấm **Đồng bộ** lại. Chi tiết nằm trong **Nhật ký Bluetooth** ở trang **Thiết bị**. |
