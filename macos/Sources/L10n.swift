import Foundation

/// Chuỗi giao diện viết bằng tiếng Việt ngay trong mã, như phần web. Bản tiếng Anh lấy từ
/// /static/i18n/en.json của server (cùng một bảng dịch với giao diện web); tests/i18n_strings.py
/// thu thập mọi chuỗi trong lời gọi t(...) ở các tệp Swift này, nên chuỗi mới phải có trong en.json.
enum L10n {
    static var lang = "vi"
    static var catalog: [String: String] = [:]

    /// Tải bảng dịch từ server; gọi `done` trên luồng chính khi xong.
    static func load(from base: URL, done: @escaping () -> Void) {
        let url = base.appendingPathComponent("static/i18n/en.json")
        URLSession.shared.dataTask(with: url) { data, _, _ in
            guard let data, let dict = try? JSONSerialization.jsonObject(with: data) as? [String: String] else { return }
            DispatchQueue.main.async {
                catalog = dict
                done()
            }
        }.resume()
    }

    static var locale: Locale { Locale(identifier: lang == "en" ? "en_US" : "vi_VN") }
}

/// Dịch một chuỗi gốc tiếng Việt; {tên} được thay bằng vars["tên"].
func t(_ source: String, _ vars: [String: Any] = [:]) -> String {
    var out = L10n.lang == "en" ? (L10n.catalog[source] ?? source) : source
    for (key, value) in vars {
        out = out.replacingOccurrences(of: "{\(key)}", with: "\(value)")
    }
    return out
}
