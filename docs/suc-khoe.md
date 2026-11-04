# Trang Sức khỏe

Trang **Sức khỏe** hiện dữ liệu Mi Band 6 đã ghi: giấc ngủ, bước chân, nhịp tim, căng thẳng, PAI, SpO2 và các buổi tập, kèm một bản **phân tích sức khỏe**, **mức sẵn sàng**, **trạng thái tinh thần** (ước tính), **tín hiệu cơ thể** (nhịp tim khi ngủ so với mức thường, có mô hình cá nhân), **giấc ngủ tối nay**, **cường độ vận động** và **nhịp sinh học** dựa trên tất cả số liệu đó. Trang có trong cả bản web (`uv run miband6-web`) lẫn ứng dụng macOS.

## Đồng bộ

- Ứng dụng tự lấy dữ liệu mỗi lần kết nối vòng tay và theo lịch ở **Cài đặt ứng dụng → Tự đồng bộ** (mặc định mỗi 30 phút khi đang kết nối; có thể chọn 15 phút tới 2 giờ, hoặc chỉ khi bấm). Bấm **Đồng bộ** ở đầu trang để lấy ngay; dòng dưới tiêu đề cho biết đang lấy gì và lần đồng bộ gần nhất.
- Lần đầu ứng dụng lấy 30 ngày gần nhất, rồi một lần duy nhất hỏi vòng tay mọi dữ liệu cũ hơn mà nó còn giữ (dòng trạng thái ghi "dữ liệu cũ"), nên có thể mất vài phút. Các lần sau chỉ lấy phần mới.
- **Mi Fitness vẫn đồng bộ bình thường.** Ứng dụng chỉ sao chép: nó không gửi lệnh xác nhận "đã lấy xong", nên vòng tay vẫn giữ nguyên dữ liệu cho Mi Fitness.
- Dữ liệu được lưu trên máy tại `~/Library/Application Support/MiBand6Manager/health/` (mỗi vòng tay một tệp SQLite, chỉ tài khoản của bạn đọc được) và không gửi đi đâu.

Chọn ngày bằng nút ngày ở đầu trang (mở lịch; ngày có chấm xanh là ngày có dữ liệu, có sẵn nút **Hôm qua** / **Hôm nay**) hoặc hai nút ‹ ›; bấm vào một cột trong biểu đồ nhiều ngày để xem ngày đó.

## Các thẻ

Trang chia theo nhóm, mỗi nhóm một thẻ ở dưới tiêu đề (ứng dụng nhớ thẻ mở lần trước). Những gì xem hằng ngày (điểm sẵn sàng, giấc ngủ đêm qua, bước chân, nhịp tim, căng thẳng, pin, chu kỳ) nằm gọn ở trang **Hôm nay**; bấm từng ô ở đó để mở đúng thẻ ở đây, bấm một cột trong biểu đồ 7 ngày để mở ngày đó.

| Thẻ | Nội dung |
| --- | --- |
| **Giấc ngủ** | Đêm của ngày đang xem: giờ ngủ, giờ dậy, tổng thời gian, phần ngủ sâu, độ liền mạch, nhịp tim khi ngủ, **điểm ngủ**; sơ đồ các giai đoạn (thức, ngủ nông, ngủ sâu, REM ước tính) theo giờ; **giấc ngủ tối nay** (khi xem hôm nay: nên lên giường lúc nào); 14 đêm gần đây so với khoảng khuyến nghị 7–9 giờ và mức trung bình của bạn; **nhịp sinh học** (lệch múi giờ xã hội, chronotype, SRI, CPD, giờ ngủ từng đêm) |
| **Vận động** | Bước theo giờ trong ngày; mọi ngày vòng tay đã ghi so với mục tiêu (**Xem dạng bảng** để xem số liệu từng ngày); **cường độ vận động** 7 ngày (phút nhẹ / vừa / mạnh); **PAI** 7 ngày so với mốc 100 |
| **Tim mạch** | Nhịp tim cả ngày (vùng tô là lúc ngủ), thấp nhất, trung bình, cao nhất và nhịp tim nghỉ (khi ngủ) so với mức nền; **căng thẳng** tự đo (đường) và đo tay (chấm); **SpO2** các lần đo; cách vòng tay đang đo tự động |
| **Cơ thể** | Cân nặng, chiều cao, BMI mới nhất; thay đổi 30 / 90 ngày, xu hướng kg/tuần, biểu đồ cân nặng; ghi cân nặng và danh sách các lần ghi (xem [Hồ sơ](#hồ-sơ-tuổi-giới-tính-chiều-cao-cân-nặng)) |
| **Tập luyện** | Các buổi tập: loại, giờ bắt đầu, thời gian, quãng đường, năng lượng, nhịp tim trung bình, số bước và nguồn (vòng tay hoặc Mi Fitness); bản đồ lộ trình |
| **Chu kỳ** (hồ sơ nữ) | Nhật ký kỳ kinh và dự đoán, xem [Nhật ký riêng](#nhật-ký-riêng-chu-kỳ-kinh-nguyệt-và-xuất-tinh) |
| **Sinh lý** (hồ sơ nam) | Nhật ký xuất tinh và so sánh giấc ngủ, xem [Nhật ký riêng](#nhật-ký-riêng-chu-kỳ-kinh-nguyệt-và-xuất-tinh) |
| **Xu hướng** | Như **Tóm tắt sức khỏe** của Mi Fitness: các chỉ số vừa **thay đổi rõ** (30 ngày / 26 tuần), **7 ngày qua** so với tuần trước, **hôm nay so với thường lệ** (xem [Xu hướng](#xu-hướng)) |
| **Phân tích** | **Điểm sẵn sàng** (điểm 0–100, lời khuyên, các thành phần, thời gian hồi phục, xu hướng 14 ngày), **phân tích sức khỏe** từng mặt, **trạng thái tinh thần** ước tính và **tín hiệu cơ thể** (nhịp tim khi ngủ so với mức thường, mô hình cá nhân; xem bên dưới) |

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

- **Nhịp tim** và **căng thẳng**: vòng tay tự đo theo **Cài đặt vòng tay → Sức khỏe** (chu kỳ đo nhịp tim, Theo dõi căng thẳng). Không bật thì thẻ Căng thẳng chỉ có các lần đo tay (chấm). Các lần đo tay cũng được tính vào phân tích căng thẳng và trạng thái tinh thần. Cách đo hiện tại ghi ở cuối thẻ **Tim mạch**.
- **Theo dõi nhịp tim liên tục** (số đo theo thời gian thực ở trang Hôm nay) bật tay ở thẻ **Đo nhịp tim**, hoặc tự bật mỗi lần kết nối nếu bật **Cài đặt ứng dụng → Nhịp tim trực tiếp**. Vòng tay đo liên tục tốn pin hơn.
- **SpO2**: Mi Band 6 chỉ đo khi bạn mở mục SpO2 trên vòng tay và bấm đo; ứng dụng không bật đo từ xa được (giao thức không có lệnh này). Kết quả hiện sau lần đồng bộ kế tiếp.

## Giấc ngủ được tính thế nào

Mi Band 6 ghi mỗi phút một mẫu. Byte đầu của mẫu là **mốc trạng thái** (4 bit thấp: 9 ngủ nông, 11 ngủ sâu, 12 thức dậy, 1 hoạt động, 3 không đeo, 6 đang sạc), chỉ ghi ở phút trạng thái đổi; các phút giữa mang "không đổi". Ứng dụng đọc giống Gadgetbridge: mỗi phút mang trạng thái của mốc gần nhất trước nó. Mỗi phút còn có chỉ số **"ngủ"** (0–62, tăng khi thiếp đi, tụt khi tỉnh), **điểm ngủ sâu** và (firmware từ 11/2026) **điểm REM** do vòng tay tính.

Các bước (`health.sleep_sessions`), kiểm chứng với báo cáo giấc ngủ của Mi Fitness trên 40 đêm thật (9–11/2026):

1. **Không đeo thì không ngủ.** Phút vòng tay báo "không đeo" / "đang sạc" (ở phút đó hoặc từ trước, và từ đó chưa đo được nhịp tim) và phút có từ 20 bước không bao giờ là ngủ. Vòng tay nằm yên trên bàn trông như người đang ngủ: chỉ số "ngủ" vẫn tăng, và lúc đeo vào vòng tay hay ghi một mốc "ngủ sâu". Vừa đeo lại thì chỉ số này còn giữ mức lúc nằm trên bàn và giảm dần; ứng dụng coi là 0 cho tới khi nó tăng trở lại (tối đa 30 phút). Trước đây đêm 4/11 bị tính ngủ từ 00:54 (vòng tay trên bàn từ 00:48) và thêm 11 phút "ngủ" lúc 9:57–10:08 (tháo vòng sau khi dậy).
2. **Lúc thiếp đi.** Vòng tay ghi mốc ngủ trễ chừng 11 phút. Ứng dụng lấy phút đầu tiên của **đợt tăng cuối cùng** của chỉ số "ngủ" (từ 9 trở lên, tăng liên tục tới khi trung vị 5 phút đạt 40), lùi tối đa 30 phút. Các lần lơ mơ rồi tỉnh trước đó, và mẩu ngủ dưới 10 phút ở đầu giấc cách phần sau từ 3 phút thức, không tính.
3. **Lúc dậy.** Cắt phần cuối giấc có chỉ số "ngủ" (trung vị 5 phút) dưới 30, tối đa 30 phút; phút chuyển tiếp (chỉ số đang tụt) tính là đã dậy. Vòng tay không ghi chỉ số này thì giữ nguyên mốc của vòng tay.
4. **Thức giữa giấc.** Vòng tay ít khi ghi các lần thức ngắn. Một phút là ứng viên "thức" khi nhịp tim (trung vị 3 phút) cao hơn nền khi ngủ quanh đó (phân vị 25% trong 61 phút) từ 8 nhịp/phút, kèm cử động trong ±2 phút và chỉ số "ngủ" tụt (dưới 45 và dưới 80% mức của đêm); với vòng tay có điểm REM: điểm REM ở mức sàn (≤ 21, như lúc thức) và cử động hoặc chỉ số "ngủ" tụt. Cần ít nhất 4 phút ứng viên liền nhau, đợt được nối dài khi dấu hiệu (điểm REM ở mức sàn, hoặc cử động) còn, và chỉ tính khi cả đợt từ 10 phút: các lần tỉnh ngắn hơn thường không nhớ được và Mi Fitness cũng tính là ngủ. Đêm 4/11: thức 8:29–8:40 (người dùng xác nhận 8:29–8:41), dậy 9:13.
5. **Ngủ sâu, REM.** Mốc "ngủ sâu" của vòng tay **không** khớp với Mi Fitness (trên 40 đêm lệch trung bình 64 phút; có đêm 0 phút, có đêm 236 phút, trong khi Mi Fitness luôn 10–23%). Ứng dụng xếp các phút theo **điểm ngủ sâu** của vòng tay (trung bình 5 phút), chỉ xét phút nằm yên (không cử động trong ±2 phút) và nhịp tim không cao hơn nền quá 4 nhịp/phút, rồi chọn ngưỡng để tổng phút ngủ sâu bằng: số của **Mi Fitness cho đúng đêm đó** nếu đã lấy; nếu chưa, **tỉ lệ học được** (trung vị các đêm Mi Fitness ≥ 3 giờ gần nhất, cần ít nhất 5 đêm); nếu chưa đăng nhập Mi Fitness, **15%** (trung bình Mi Fitness trên 39 đêm là 15,3%). REM làm tương tự với điểm REM (chỉ khi vòng tay ghi), mặc định điểm > 55 như Gadgetbridge. Đoạn ngủ sâu / REM cách nhau tới 2 phút được nối, đoạn dưới 3 phút bị bỏ. Giấc dưới 60 phút (ngủ trưa) không chia giai đoạn, như Mi Fitness. Vòng tay không ghi điểm ngủ sâu thì dùng mốc ngủ sâu của nó.

Các khoảng thức ngắn hơn 45 phút ở giữa đêm vẫn tính là cùng một giấc (hiện ở hàng **Thức**); giấc ngắn hơn 20 phút bị bỏ qua. Mỗi giấc được tính cho ngày bạn thức dậy, như Mi Fitness. Giấc còn đang ngủ (kéo tới phút mới nhất đã đồng bộ, vòng tay chưa ghi lúc thức dậy) chưa được tính là "đêm qua": đồng bộ lúc nửa đêm thì đêm qua không còn bị tính là giấc ngủ chỉ vài chục phút, kéo lệch điểm ngủ, mức sẵn sàng và phân tích.

### So với Mi Fitness

Lượt **Lấy lịch sử từ Mi Fitness** (và lượt chạy ngầm theo lịch) lấy cả **báo cáo giấc ngủ** của Mi Fitness (giờ ngủ, giờ dậy, phút ngủ sâu / nông / REM / thức, điểm ngủ). Mi Fitness không tải lên diễn biến từng phút của Mi Band 6, chỉ có tổng mỗi giấc. Báo cáo được lưu trên máy (bảng `mf_sleep`) và dùng để:

- hiện dòng **Mi Fitness:** dưới biểu đồ giấc ngủ của đêm đó, kèm điểm ngủ của Mi Fitness;
- lấy đúng số phút ngủ sâu, REM của Mi Fitness cho đêm đó (vị trí trên biểu đồ, giờ ngủ, giờ dậy và các lần thức vẫn do ứng dụng tính);
- học tỉ lệ ngủ sâu, REM cho các đêm chưa có báo cáo (đêm qua trước khi điện thoại đồng bộ, hoặc khi chỉ dùng ứng dụng này);
- đo **độ khớp** của thuật toán (tính như khi chưa có Mi Fitness, không hiệu chỉnh) và hiện dưới thẻ Giấc ngủ.

Độ khớp trên 40 đêm (sai lệch tuyệt đối trung bình, chưa hiệu chỉnh): giờ ngủ 1,4 phút (trước đây 29 phút), giờ dậy 7,4 phút (10,7), thời lượng 6,7 phút (26,3), ngủ sâu 10,4 phút (64), thức 5,3 phút (13,2). Phần lớn sai lệch giờ dậy còn lại là các buổi sáng nằm lơ mơ sau khi tỉnh.

Điểm ngủ của ứng dụng (thang kiểu Oura, xem [Điểm sẵn sàng](#điểm-sẵn-sàng-hôm-nay)) khác thang của Mi Fitness: Mi Fitness hiếm khi cho trên 80 và trừ nặng khi đi ngủ muộn (trên dữ liệu thật, mỗi giờ đi ngủ muộn hơn trừ khoảng 4 điểm), nên hai con số không so trực tiếp được.

### REM (ước tính)

[Xiaomi công bố hỗ trợ REM](https://www.mi.com/sg/support/faq/details/KA-07049/). Trên dữ liệu thật, từ 15:11 ngày 3/11/2026 (có lẽ sau một bản cập nhật firmware) vòng tay bắt đầu ghi **điểm REM** mỗi phút (byte REM có bit 7) và Mi Fitness bắt đầu báo REM từ đêm 4/11 (trước đó luôn 0). Khi vòng tay có điểm REM, ứng dụng dùng nó (xem bước 5 ở trên). Với dữ liệu cũ không có điểm REM, tùy chọn dưới đây là ước tính riêng từ nhịp tim, chưa được kiểm chứng với PSG và không phải kết quả REM của Xiaomi:

- Khi ngủ REM cơ thể gần như bất động, nhưng nhịp tim tăng so với nền NREM và dao động nhiều hơn.
- Chỉ xét giấc từ 3 giờ trở lên có nhịp tim ở ít nhất 80% số phút. Bật **Cài đặt vòng tay → Sức khỏe → Hỗ trợ giấc ngủ** để vòng tay đo nhịp tim mỗi phút khi ngủ; đêm không đủ thì không ước tính.
- Nền NREM là phân vị 30% của nhịp tim (đã làm mượt 3 phút) trong cửa sổ 61 phút quanh mỗi phút. Phút "ngủ nông" ít cử động, sau ít nhất 60 phút từ lúc ngủ, có nhịp tim cao hơn nền từ 4 nhịp/phút (hoặc dao động trong 9 phút từ 1,6 lần mức thường của đêm và cao hơn nền 2 nhịp/phút) được xem là REM. Các đoạn cách nhau tới 10 phút được nối; đoạn ngắn hơn 6 phút bị bỏ.
- Nếu REM vượt 30% thời gian ngủ, ngưỡng được nâng dần (người lớn khỏe thường có 20–25% REM).

Trên dữ liệu thật, cách này cho 15–29% REM mỗi đêm, giai đoạn REM đầu tiên sau khối ngủ sâu đầu đêm, lặp lại mỗi 60–90 phút và dài dần về sáng, đúng cấu trúc giấc ngủ thường gặp. Chưa có phép đo đa ký giấc ngủ để đối chiếu, nên đây chỉ là ước tính: các thiết bị đeo chuyên dụng dùng nhịp tim và HRV chỉ nhận ra REM với độ nhạy khoảng 60% (Firstbeat, Kuula & Pesonen 2021). Tắt REM ở **Cài đặt ứng dụng → Giấc ngủ REM** thì REM được gộp lại vào ngủ nông.

## Xu hướng

Thẻ **Xu hướng** làm như **Tóm tắt sức khỏe** của Mi Fitness, tính tới ngày đang xem (`trends.py`, dữ liệu do `HealthDB.trends` dựng):

| Chỉ số | Theo | Mức chênh tối thiểu | Chiều tốt |
| --- | --- | --- | --- |
| Thời gian ngủ chính | giấc dài nhất mỗi ngày thức dậy (≥ 3 giờ) | 20 phút | tăng (giảm mà vẫn đủ nhu cầu, hay tăng khi đã ngủ quá nhu cầu 2 giờ: bình thường) |
| Giờ đi ngủ | giờ thiếp đi của giấc đó | 20 phút | sớm hơn |
| Tỉ lệ ngủ sâu | phút ngủ sâu / phút ngủ | 2 điểm % | tăng |
| Nhịp tim khi ngủ | trung vị nhịp tim lúc ngủ (≥ 10 số đo, như mọi chỗ khác: đo mỗi 30 phút vẫn đủ) | 2 nhịp/phút | giảm |
| Bước chân | ngày đã trọn, đeo vòng ≥ 10 giờ | 500 bước | tăng |
| Năng lượng vận động | như trên | 20 kcal | tăng |
| Vận động vừa và mạnh | phút nhịp bước ≥ 100 bước/phút cộng phút trong buổi tập | 5 phút | tăng |
| Căng thẳng | trung bình các số đo tự động (≥ 12 số đo trong ngày) | 4 | giảm |

- **Thay đổi gần đây**: trong 30 ngày (bước chân, năng lượng, phút vận động thêm theo tuần trong 26 tuần, chỉ tuần thứ Hai–Chủ nhật đã trọn có ≥ 4 ngày dữ liệu), thử mọi cách chia "gần đây / trước đó" (phần gần đây từ 3 ngày / tuần, không dài hơn phần trước; phần trước từ 7 ngày / 4 tuần), lấy cách chia có kiểm định t Welch lớn nhất. Báo khi |t| ≥ 2,5 (cao hơn mức 2 thường dùng vì đã thử nhiều điểm chia) và mức chênh từ ngưỡng trong bảng. Đây là cách Mi Fitness hiện "3 ngày qua so với 27 ngày trước đó", "8 ngày / 22 ngày", "5 tuần / 21 tuần".
- **7 ngày qua**: trung bình 7 ngày qua so với 7 ngày trước đó (mỗi bên cần ≥ 4 ngày); "gần như không đổi" khi chênh dưới nửa ngưỡng trong bảng. **Giờ thức dậy**: độ lệch chuẩn 7 ngày ≤ 30 phút là đều đặn, ≤ 60 phút khá đều, hơn nữa là chưa đều.
- **Hôm nay so với thường lệ**: bước chân và năng lượng cộng dồn theo từng 15 phút tới giờ này, so với trung vị cùng giờ của 28 ngày trước (chỉ ngày đeo vòng ≥ 10 giờ, cần ≥ 7 ngày). Lệch quá 25% (và quá 300 bước / 15 kcal) là cao hơn / thấp hơn thường lệ.
- **Năng lượng vận động** (ước tính, không gồm năng lượng lúc nghỉ, như "calo vận động" của Mi Fitness): phương trình chuyển hóa của ACSM, đi bộ tốn thêm 0,1 ml O2/kg/m, chạy 0,2 ml O2/kg/m (phút từ 140 bước), 1 lít O2 ≈ 5 kcal; chiều dài bước ≈ 0,415 × chiều cao (nam), 0,413 × chiều cao (nữ); cân nặng, chiều cao từ hồ sơ (chưa có thì 65 kg, 170 cm). Buổi tập có số năng lượng (vòng tay / Mi Fitness) thì dùng số đó thay phần ước tính trong buổi tập. Trên dữ liệu thật: 266 kcal/ngày trong 7 ngày, Mi Fitness 281.

## Phân tích sức khỏe

Thẻ đầu trang nhận xét tình trạng hiện tại từ dữ liệu 7–30 ngày gần nhất, theo khuyến nghị chung cho người lớn. Mỗi mục có nhãn **Tốt**, **Ổn**, **Nên chú ý** hoặc **Cần lưu ý** (kèm biểu tượng, không chỉ dựa vào màu) và một dòng giải thích.

| Mục | Tính từ | Tốt | Ổn / Nên chú ý / Cần lưu ý |
| --- | --- | --- | --- |
| Thời gian ngủ | Trung bình 7 đêm gần nhất có dữ liệu | 7–9,5 giờ | Nên chú ý: 6–7 giờ hoặc trên 9,5 giờ; Cần lưu ý: dưới 6 giờ |
| Ngủ sâu | Phần trăm ngủ sâu trong giấc ngủ | Từ 13% | Ổn: 10–13%; Nên chú ý: dưới 10% |
| Giờ đi ngủ đều đặn | Độ lệch giờ đi ngủ giữa các đêm | ±45 phút | Ổn: tới ±90 phút; Nên chú ý: hơn nữa |
| Nhịp tim nghỉ | Trung vị nhịp tim các phút đang ngủ (không gồm các lần thức giữa đêm, cần ≥ 10 số đo), trung bình 7 đêm | 40–75 nhịp/phút | Ổn: tới 80; Nên chú ý: trên 80, hoặc cao hơn tuần trước từ 5 nhịp/phút |
| Bước chân | Trung bình 7 ngày đã trọn (ngày đeo vòng ít nhất 10 giờ; vòng tay vẫn ghi mỗi phút khi tháo ra, nên đếm phút đeo, không đếm bản ghi) | Đạt mục tiêu bước | Ổn: từ 60% mục tiêu; Nên chú ý: thấp hơn |
| Vận động | Phút đi bộ nhanh (từ 100 bước/phút) và tập luyện trong 7 ngày | Từ 150 phút | Ổn: 75–150; Nên chú ý: dưới 75 |
| PAI | Tổng PAI mới nhất | Từ 100 | Ổn: 50–100; Nên chú ý: dưới 50 |
| SpO2 | Các lần đo 30 ngày | Thấp nhất từ 95% | Ổn: 92–94%; Nên chú ý: 90–91%; Cần lưu ý: dưới 90% |
| Căng thẳng | Trung bình mọi số đo 7 ngày, tự đo và đo tay (ghi kèm số số đo) | Dưới 40 | Ổn: 40–59; Nên chú ý: từ 60 |
| Nhịp tim lúc nghỉ | Các đợt nhịp tim từ 120 hoặc dưới 40 nhịp/phút kéo dài ≥ 10 phút khi không vận động, 7 ngày (xem dưới) | Không có đợt nào (chỉ kết luận khi đo đủ dày: ≥ 144 số đo lúc nghỉ cách nhau ≤ 10 phút) | Nên chú ý: có đợt; Cần lưu ý: đợt cao tới 150 |
| Dữ liệu | Thời điểm của dữ liệu mới nhất | | Nên chú ý: cũ hơn 2 ngày |

**Nhịp tim lúc nghỉ** làm như thông báo nhịp tim cao / thấp của Apple Watch (mức mặc định 120, thấp 40 nhịp/phút, 10 phút khi không vận động): chỉ xét lúc thức (ngoài giấc ngủ), không đi lại (không có bước nào trong 5 phút trước mỗi số đo, cả đợt tối đa 5 bước do tay cử động), không trong buổi tập hay 30 phút sau. Một đợt là các số đo liền nhau (cách nhau tối đa 10 phút) cùng vượt ngưỡng, ít nhất 2 số đo, kéo dài từ 10 phút. Nhịp tim cao khi nghỉ có thể do cà phê, lo âu, sốt, mất nước, thuốc, hoặc vòng tay đo sai khi tay cử động; thấp lúc thức có thể bình thường ở người tập luyện nhiều. Lặp lại hoặc kèm hồi hộp, chóng mặt, khó thở, đau ngực, ngất thì nên đi khám.

Mục nào chưa có dữ liệu thì không hiện (hoặc hiện **Chưa đủ dữ liệu**). Các ngưỡng lấy từ khuyến nghị phổ biến: ngủ 7–9 giờ mỗi đêm, 150 phút vận động vừa mỗi tuần (WHO), PAI từ 100, SpO2 bình thường từ 95%.

> Phân tích chỉ để tham khảo, không phải chẩn đoán. Cảm biến đeo tay có sai số, nhất là SpO2. Nếu thấy bất thường kéo dài hoặc có triệu chứng (khó thở, đau ngực, mệt bất thường), hãy hỏi ý kiến bác sĩ.

## Điểm sẵn sàng hôm nay

Ô đầu tiên của trang **Hôm nay**; chi tiết ở thẻ **Phân tích**. Điểm 0–100 trả lời câu hỏi **hôm nay nên tập hay nên nghỉ**, như Readiness của Apple Watch, Physical Readiness của Huawei Watch GT 7 hay Training Readiness của Garmin. Các hãng không công bố công thức, nhưng cùng dựa trên ba nhóm dữ liệu so với **mức nền của chính bạn**: giấc ngủ (đêm qua và các đêm gần đây), chỉ số cơ thể (nhịp tim nghỉ, HRV) và tải vận động (các ngày gần đây và thời gian hồi phục). Ứng dụng làm theo cấu trúc đó; trọng số và ngưỡng dưới đây là lựa chọn của ứng dụng.

| Thành phần (trọng số) | Tính từ | 100 điểm khi |
| --- | --- | --- |
| Nhịp tim nghỉ (18%) | Trung vị nhịp tim khi ngủ đêm qua (cần ≥ 10 số đo) so với mức nền: trung vị tối đa 30 đêm trước (cần ít nhất 7), độ lệch chuẩn bền vững 1,4826 × MAD, tối thiểu 2 nhịp/phút (vài đêm ốm hay uống rượu trong mức nền không kéo lệch nó) | Không cao hơn mức nền quá 0,5 độ lệch chuẩn; mỗi độ lệch chuẩn thêm trừ khoảng 25 điểm |
| Chỉ số hồi phục (8%) | Thời điểm có trung bình nhịp tim thấp nhất trong 5 phút liên tiếp. Chỉ tính khi có số đo hợp lệ ở ít nhất 70% số phút ngủ và ít nhất 30 phút ngủ có số đo | Thấp nhất trong nửa đầu đêm (75% đêm: 60 điểm) |
| Giấc ngủ đêm qua (20%) | Thời lượng (50%), tỉ lệ thời gian trên giường là ngủ (15%), phần ngủ sâu (15%), giờ ngủ so với chronotype (20%) | Ngủ 7,5–9 giờ, liền mạch từ 95%, ngủ sâu từ 16%, giữa giấc lệch chronotype dưới 30 phút |
| Cân bằng giấc ngủ (14%) | Tổng phút ngủ trong 14 ngày so với nhu cầu theo tuổi (ngày gần nặng hơn), kèm số phút còn thiếu trong 7 ngày. Mỗi giấc đã kết thúc từ 20 phút được tính một lần theo ngày thức dậy. Ngày thiếu dữ liệu được bỏ qua | Đạt 100% nhu cầu |
| Thời gian hồi phục (15%) | Mệt mỏi từ tải vận động các giờ gần đây (xem dưới), như "recovery time" của Garmin | Đã hồi phục (12 giờ: 80; 24 giờ: 60; 48 giờ: 35) |
| Cân bằng vận động (10%) | Tỉ lệ tải cấp/tải mạn (ACWR, Gabbett): TRIMP trung bình 7 ngày / 28 ngày đủ dữ liệu tải (cần 14 ngày, xem dưới) | Trong khoảng 0,8–1,3 (1,5: 75; 2: 45) |
| Cân bằng căng thẳng, thay cho HRV (15%) | Chỉ số căng thẳng của vòng tay 2 ngày gần nhất so với mức nền | Không cao hơn mức nền; từ 60 trở lên tối đa 70 điểm |

**Thời gian hồi phục** dùng mô hình thể lực - mệt mỏi kiểu Banister, rút gọn: mỗi giờ có tải (TRIMP) cộng vào "mệt mỏi", mờ dần theo e^(−t/36 giờ). Với tải đều đặn C mỗi ngày (trung bình 28 ngày đủ dữ liệu tải, tối thiểu 30), mệt mỏi ổn định quanh C × 36/24; thời gian hồi phục còn lại = 36 × ln(mệt mỏi / mức ổn định) giờ, tối đa 96. Tải trong hôm nay cũng được tính, nên điểm hôm nay giảm ngay sau một buổi tập (như Apple Watch). Ví dụ: buổi tập TRIMP 450 với người thường có 100 mỗi ngày, 20 giờ sau còn khoảng 19,5 giờ hồi phục.

**TRIMP** (tải vận động) theo Edwards: mỗi phút ở 50–60 / 60–70 / 70–80 / 80–90 / 90–100% nhịp tim tối đa tính 1 / 2 / 3 / 4 / 5 điểm; nhịp tim tối đa lấy từ hồ sơ như mô tả bên dưới.

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

## Hồ sơ: tuổi, giới tính, chiều cao, cân nặng

Ứng dụng đọc hồ sơ ở **Cài đặt vòng tay → Hồ sơ** (nhập tay hoặc lấy từ Mi Fitness):

- **Nhịp tim tối đa** (cho TRIMP, cường độ buổi tập và vùng nhịp tim gợi ý): nhập số đã đo trong mục **Vùng nhịp tim** và chọn **Lưu trên máy**. Giá trị này áp dụng cả khi xem lại dữ liệu cũ. Để trống và lưu để dùng lại ước tính. Khi ước tính, nữ theo Gulati 2010, 206 − 0,88 × tuổi (đo trên 5.437 phụ nữ); còn lại theo Tanaka 2001, 208 − 0,7 × tuổi. Chưa có ngày sinh thì coi 30 tuổi.
- **Nhu cầu ngủ** theo tuổi (National Sleep Foundation / AASM, lấy giữa khoảng): 6–13 tuổi 10 giờ (9–11), 14–17 tuổi 9 giờ (8–10), người lớn 7,5 giờ (7–9; từ 65 tuổi 7–8). Dùng cho điểm giấc ngủ, cân bằng giấc ngủ, trạng thái tinh thần và mục "Thời gian ngủ" của phân tích (Tốt khi trung bình từ nhu cầu − 30 phút tới nhu cầu + 2 giờ; dưới mức đó 1 giờ là Cần lưu ý).
- **Lịch sử chiều cao, cân nặng** (thẻ **Cơ thể**): mỗi lần lưu hồ sơ, ghi cân nặng ở thẻ Cơ thể, hay Mi Fitness có số mới đều thêm một lần ghi (mỗi ngày một lần ghi; lần đầu lấy số trong hồ sơ). Lần ghi mới nhất thành hồ sơ và được ghi vào vòng tay. Đồng bộ ngầm với Mi Fitness (12 giờ một lần) chỉ nhận chiều cao, cân nặng khi số trong Mi Fitness đã đổi so với lần trước, nên số bạn ghi trong ứng dụng không bị số cũ đè; bấm **Đồng bộ** hồ sơ thì luôn nhận. Phân tích (mục **Cân nặng**): thay đổi so với lần ghi gần nhất trước 30 / 90 ngày; tốc độ kg/tuần là hồi quy tuyến tính các lần ghi trong 90 ngày (cần cách nhau từ 14 ngày); thay đổi 6 tháng so với lần ghi cũ nhất trong 183 ngày (cách từ 28 ngày). **Nên chú ý** khi thay đổi từ 5% trong 6 tháng (mốc sụt cân không chủ ý đáng kể; dùng cả cho tăng cân), giảm nhanh hơn 1 kg/tuần (khuyến nghị giảm cân an toàn 0,5–1 kg/tuần) hoặc tăng từ 0,5 kg/tuần; **Cần lưu ý** khi đang thiếu cân (BMI dưới 18,5) mà vẫn giảm.
- **BMI** = cân nặng / chiều cao² (từ 18 tuổi; dưới 18 tuổi BMI phải so theo bách phân vị tuổi nên không hiện). Ngưỡng cho người châu Á của WHO (Lancet 2004), vì người Việt có nguy cơ tim mạch, tiểu đường ở BMI thấp hơn ngưỡng chung 25/30: dưới 18,5 thiếu cân (Nên chú ý), 18,5–22,9 bình thường (Tốt), 23–24,9 thừa cân (Ổn), 25–29,9 béo phì độ I (Nên chú ý), từ 30 béo phì độ II (Cần lưu ý). BMI không phân biệt cơ và mỡ.

## Nhật ký riêng: chu kỳ kinh nguyệt và xuất tinh

Vòng tay không đo được những điều này, nên bạn tự ghi: bấm một ngày trên lịch của thẻ để ghi hoặc bỏ ghi. Thẻ **Chu kỳ** chỉ hiện khi giới tính trong hồ sơ là Nữ, thẻ **Sinh lý** chỉ khi là Nam. Dữ liệu nằm trong tệp SQLite của vòng tay trên máy tính này và không gửi đi đâu. Mi Band 6 có theo dõi chu kỳ trong Mi Fitness / Zepp Life, nhưng nhật ký đó nằm ở ứng dụng điện thoại; giao thức Bluetooth của ứng dụng này không có lệnh đọc nó.

**Chu kỳ kinh nguyệt** (`personal.py`)
- Các ngày có kinh cách nhau tối đa 2 ngày không ghi là một kỳ kinh. Độ dài chu kỳ là trung vị khoảng cách giữa các ngày bắt đầu (6 chu kỳ gần nhất, chỉ tính 18–50 ngày, nên quên ghi một tháng không làm lệch); chưa có thì 28 ngày. Độ dài kỳ kinh là trung vị các kỳ đã ghi đủ (chỉ ghi ngày đầu thì coi như 5 ngày).
- Rụng trứng ước tính 14 ngày trước kỳ kinh kế tiếp (pha hoàng thể khá ổn định quanh 14 ngày, Lenton 1984); **cửa sổ dễ thụ thai** từ 5 ngày trước tới 1 ngày sau đó (Wilcox 1995). Các pha: hành kinh, nang noãn, rụng trứng (±1 ngày), hoàng thể. Quá ngày dự đoán mà chưa ghi kỳ mới thì hiện số ngày trễ. Chu kỳ gần đây chênh nhau hơn 7 ngày thì báo dự đoán kém chính xác. **Không dùng để tránh thai hay chẩn đoán.**
- **Điểm sẵn sàng**: ở pha hoàng thể nhịp tim nghỉ thường cao hơn 2–3 nhịp/phút so với pha nang noãn (Shilaih 2017). Trước khi so với mức nền, ứng dụng trừ phần tăng này khỏi nhịp tim khi ngủ của các đêm pha hoàng thể (cả đêm nay lẫn các đêm làm mức nền), để chu kỳ bình thường không bị báo là "chưa hồi phục". Có từ 5 đêm ở mỗi pha thì dùng mức chênh của chính bạn (giới hạn 0–6 nhịp/phút), chưa đủ thì 2 nhịp/phút. Trạng thái tinh thần dùng cùng giá trị đã trừ.

**Xuất tinh** (`personal.py`)
- Lần gần nhất, số lần 7 và 30 ngày qua, trung bình mỗi tuần trong 4 tuần.
- **Giấc ngủ đêm sau so với các đêm khác** (60 ngày): thời lượng, phần ngủ sâu, thức giấc, giờ đi ngủ trung bình và nhịp tim khi ngủ của đêm ngay sau ngày có ghi (đêm thức dậy hôm sau), so với các đêm còn lại; cần ít nhất 3 đêm mỗi nhóm. Đây chỉ là so sánh trên dữ liệu của bạn, không cho thấy nguyên nhân.
- Điểm sẵn sàng **không** đổi theo nhật ký này: chưa có bằng chứng hoạt động tình dục đêm trước làm giảm thể lực hôm sau (tổng quan Zavorsky 2019); nhiều người tự thấy dễ ngủ hơn sau cực khoái (Lastella 2019, tự báo cáo), điều mà phần so sánh giấc ngủ giúp bạn tự kiểm tra.

## Trạng thái tinh thần (ước tính)

Ước tính có giải thích, **không phải chẩn đoán**. Dựa trên các yếu tố mà nghiên cứu cho thấy liên quan tới tâm trạng: căng thẳng (HRV), thiếu ngủ và thời gian thức dài (nghiên cứu 2.602 bác sĩ nội trú, *PLOS Digital Health* 2024), lệch nhịp sinh học (dịch pha nhịp sinh học là yếu tố dự báo mạnh nhất cho giai đoạn khí sắc, *npj Digital Medicine* 2024), nhịp tim nghỉ tăng và ít vận động.

**Căng thẳng đo bởi vòng tay** là nguồn chính của mức "căng": vòng tay tính chỉ số này từ HRV, nên nó đo trực tiếp hơn mọi thứ ứng dụng suy ra. Ứng dụng dùng **mọi số đo 72 giờ qua, cả tự đo lẫn đo tay** (nhiều người không bật tự đo và chỉ đo tay), số đo càng mới càng nặng (trọng số giảm một nửa sau mỗi 24 giờ). Thẻ hiện đúng các con số đó (trung bình, số số đo, hôm nay, mức thường ngày) để đối chiếu với thẻ Căng thẳng.

| Yếu tố (trọng số trong áp lực tổng) | Nhóm | Mức 0 → 1 |
| --- | --- | --- |
| Căng thẳng vòng tay đo, 72 giờ (35%; ít số đo thì góp ít hơn, tối thiểu 40% trọng số khi dưới 6 số đo hiệu dụng) | Căng | Trung bình có trọng số 35 → 85 (60, mức "trung bình" của vòng tay, cho 0,5), cộng nửa tỉ lệ số đo ở mức cao (≥ 80); cao hơn hẳn mức thường của bạn (trung vị các ngày có ≥ 6 số đo tự động, cần 7 ngày) cộng thêm tối đa 0,25 |
| Giấc ngủ chính 3 đêm gần nhất (tới ngày đang xem) và nợ ngủ 7 ngày, tính cả giấc ngủ ngắn (25%) | Mệt | 7,5 giờ → 5 giờ, cộng tối đa 0,4 cho nợ ngủ (15 giờ) |
| Áp lực nhịp sinh học (15%) | Mệt | Từ CPD (0,5 → 2,5 giờ) và lệch múi giờ xã hội (0 → 2 giờ) |
| Nhịp tim khi ngủ đêm qua so với mức nền (15%) | Cơ thể | 0 → 2,5 độ lệch chuẩn; khi mô hình cá nhân đang dùng: phần không giải thích được (xem [Tín hiệu cơ thể](#tín-hiệu-cơ-thể-và-mô-hình-cá-nhân)) |
| Vận động vừa/mạnh 7 ngày đã trọn (10%) | Lối sống | 150 → 0 phút |

- **Căng** = mức căng thẳng vòng tay đo được. Nhịp tim nghỉ chỉ củng cố khi vòng tay cũng đo thấy căng (mức căng ≥ 0,3: cộng 0,15 × mức của nhịp tim nghỉ). Nhịp tim khi ngủ tăng vì nhiều nguyên nhân thể chất (tập nặng, đi ngủ muộn, rượu bia, ăn khuya, sắp ốm), nên **một mình nó không bao giờ làm trạng thái thành "Căng thẳng"**: chưa có số đo căng thẳng nào thì nó thay thế nhưng tối đa 0,45, dưới ngưỡng 0,5. Khi nhịp tim khi ngủ cao mà vòng tay đo thấy thư giãn, thẻ ghi riêng đó là dấu hiệu thể chất. Trước đây (khi chỉ dùng số đo tự động và cần ≥ 6 số đo mỗi ngày), người chỉ đo tay bị báo "Căng thẳng", mức căng 100, chỉ vì nhịp tim khi ngủ +8 trong khi vòng tay đo 26 (thư giãn).
- **Mệt** = trung bình có trọng số của giấc ngủ và nhịp sinh học. Chỉ dùng các đêm trong 3 ngày tới ngày đang xem: đêm cũ hơn (chưa đồng bộ đêm qua) không nói gì về hôm nay.
- **Áp lực tổng** là trung bình có trọng số của mọi yếu tố (0–100).
- Trạng thái: cả "căng" và "mệt" từ 50 là **Quá tải**; chỉ căng là **Căng thẳng**; chỉ mệt là **Mệt mỏi**; căng dưới 25, mệt dưới 30 và nhịp tim khi ngủ không cao là **Thư thái**; còn lại **Cân bằng**.
- **Độ tin cậy**: cao khi có từ 6 số đo căng thẳng hiệu dụng và 3 đêm gần đây; trung bình khi có từ 2 số đo căng thẳng và ít nhất 1 đêm gần đây; còn lại thấp. Không có số đo căng thẳng, hoặc chỉ có đo tay, thì thẻ nhắc bật **Theo dõi căng thẳng**.
- Xem hôm nay thì phụ đề ghi dữ liệu tới lúc nào: khi vòng tay không kết nối (ra ngoài, đi tập), số liệu dừng ở lần đồng bộ trước. Kết quả của hôm nay được tính lại mỗi giờ dù chưa có dữ liệu mới.

## Tín hiệu cơ thể và mô hình cá nhân

Thẻ **Tín hiệu cơ thể** (thẻ **Phân tích**) so nhịp tim khi ngủ 3 đêm gần nhất với mức nền của bạn (như thành phần nhịp tim nghỉ của điểm sẵn sàng: trung vị, độ lệch chuẩn bền vững) và vẽ 14 đêm gần đây trên dải mức thường (± 2 độ lệch chuẩn).

- Một đêm **cao** khi lệch từ 3 nhịp/phút **và** từ 2 độ lệch chuẩn (dùng phần không giải thích được nếu mô hình cá nhân đang dùng).
- **Bình thường**: đêm gần nhất không cao. **Cao 1 đêm** (Ổn): thường do nguyên nhân tạm thời. **Cao 2/3 đêm** (Nên chú ý): cơ thể có thể đang chịu tải (sắp ốm, tập quá sức, thiếu ngủ, rượu bia). **Cao 3 đêm liền** (Cần lưu ý): thường là dấu hiệu đang chống lại bệnh hoặc quá sức; có sốt, ho, đau họng, khó thở, đau ngực hay mệt bất thường thì nên đi khám. Nhịp tim nghỉ tăng vài ngày trước và trong khi ốm là điều các nghiên cứu phát hiện bệnh sớm bằng thiết bị đeo đã ghi nhận (Mishra và cộng sự 2020, *Nature Biomedical Engineering*; Quer và cộng sự 2021, *Nature Medicine*).

**Mô hình cá nhân** (`models.py`, học trên máy, không cần mạng hay thư viện ngoài): nhịp tim khi ngủ tăng vì nhiều lý do đã biết; mô hình học xem **với riêng bạn** mỗi lý do làm tăng bao nhiêu, để chỉ phần còn lại mới bị coi là tín hiệu.

- Mục tiêu: độ lệch nhịp tim khi ngủ của mỗi đêm so với mức nền của chính đêm đó.
- Yếu tố (0 = đêm bình thường của bạn): tải vận động hôm trước so với trung bình 28 ngày đủ dữ liệu tải (mỗi 100 TRIMP), tải trong 4 giờ trước khi ngủ (mỗi 100 TRIMP), giờ đi ngủ muộn hơn trung vị 14 đêm trước (giờ), ngủ ngắn hơn trung vị đó (giờ).
- Hồi quy ridge (hệ số phạt 4 trên yếu tố đã chuẩn hóa; ít đêm, các yếu tố liên quan nhau). Các đêm lệch quá 3,5 độ lệch chuẩn bền vững (thường là đêm ốm) không dùng để học; 3 đêm gần nhất cũng không (đó là các đêm cần đánh giá).
- **Chỉ dùng khi tốt hơn mức nền**: cần từ 21 đêm, và sai số tuyệt đối trung bình khi kiểm chứng chéo bỏ-một (mỗi đêm được dự đoán bằng mô hình học từ các đêm còn lại) phải nhỏ hơn mô hình chỉ có hệ số chặn ít nhất 5%. Nếu không, thẻ ghi rõ và ứng dụng chỉ so với mức nền. Độ lệch chuẩn của phần không giải thích được là độ lệch chuẩn bền vững của sai số kiểm chứng chéo (tối thiểu 1,5 nhịp/phút).
- Thẻ hiện mức dự đoán, phần chưa giải thích được, các yếu tố của đêm gần nhất (mỗi yếu tố từ 0,5 nhịp/phút) và những gì mô hình học được về bạn (chỉ yếu tố có hệ số khác 0 rõ: |t| ≥ 2), ví dụ "Đi ngủ muộn hơn 1 giờ: +1,8 nhịp/phút".
- Điểm sẵn sàng vẫn dùng độ lệch thật của nhịp tim nghỉ: cơ thể sau một đêm ngủ muộn vẫn chưa hồi phục hẳn, dù biết nguyên nhân.

## Giấc ngủ tối nay

Khi xem hôm nay, thẻ **Giấc ngủ** (và ô giấc ngủ ở trang **Hôm nay**) gợi ý giờ lên giường tối nay:

- Thời gian ngủ cần = nhu cầu ngủ theo tuổi + phần bù nợ ngủ: 1/3 số phút còn thiếu trong 7 ngày (tính cả giấc ngủ ngắn), làm tròn 5 phút, tối đa 60 phút mỗi đêm. Nợ ngủ nên được bù dần qua vài đêm.
- Giờ dậy: trung vị giờ dậy 28 đêm gần nhất cùng loại với ngày mai (ngày làm việc hoặc ngày nghỉ; ít hơn 3 đêm cùng loại thì dùng mọi đêm). Cần ít nhất 5 đêm.
- Giờ lên giường = giờ dậy − thời gian ngủ cần − thời gian thức giữa đêm thường gặp (trung vị) − 15 phút để thiếp đi (10–20 phút là bình thường).
- Không khuyên lên giường sớm hơn giờ ngủ quen thuộc quá 60 phút: đi ngủ quá sớm so với nhịp sinh học thường chỉ nằm trằn trọc; khi đó thẻ khuyên giữ giờ dậy cố định và bù dần.

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
| Trạng thái tinh thần có độ tin cậy thấp hoặc nhắc bật Theo dõi căng thẳng | Vòng tay có ít hoặc không có số đo căng thẳng trong 3 ngày qua. Bật **Theo dõi căng thẳng** ở **Cài đặt vòng tay → Sức khỏe** để vòng tay tự đo cả ngày, hoặc đo tay trên vòng tay rồi đồng bộ. |
| Thẻ Tín hiệu cơ thể ghi mô hình cá nhân chưa dùng | Cần ít nhất 21 đêm có nhịp tim khi ngủ (không tính 3 đêm gần nhất), và mô hình phải dự đoán tốt hơn mức nền. Với nhiều người, nhịp tim khi ngủ ít phụ thuộc giờ ngủ hay tải vận động; khi đó ứng dụng chỉ so với mức nền, vẫn đúng. |
| Dòng dưới tiêu đề ghi "chưa lấy được: …" | Mục đó lỗi ở lần đồng bộ (thường do mất kết nối giữa chừng); bấm **Đồng bộ** lại. Chi tiết nằm trong **Nhật ký Bluetooth** ở trang **Thiết bị**. |
