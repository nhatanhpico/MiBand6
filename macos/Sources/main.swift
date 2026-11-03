// Ứng dụng macOS "Mi Band 6": vỏ native (thanh menu + cửa sổ WKWebView) quanh server Python của dự án.
// Server (miband6-web --app) chạy làm tiến trình con và giữ kết nối Bluetooth; ứng dụng vẫn chạy trên
// thanh menu khi đóng cửa sổ, nên vòng tay luôn được nối. Đóng gói bằng macos/build.sh.

import AppKit

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
