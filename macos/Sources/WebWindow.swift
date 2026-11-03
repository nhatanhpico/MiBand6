import AppKit
import WebKit

/// Cửa sổ chính: hiện giao diện web của server trong WKWebView. Đóng cửa sổ chỉ ẩn nó đi,
/// ứng dụng (và kết nối Bluetooth) vẫn chạy trên thanh menu.
final class WebWindowController: NSWindowController, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    var onClose: (() -> Void)?
    private let webView: WKWebView
    private var serverURL: URL?
    private var downloads: [ObjectIdentifier: URL] = [:]

    init() {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()   // giữ localStorage (ngôn ngữ đã chọn) giữa các lần mở
        webView = WKWebView(frame: .zero, configuration: config)
        webView.setValue(false, forKey: "drawsBackground")   // không chớp nền trắng khi tải trang
        if #available(macOS 13.3, *) { webView.isInspectable = true }

        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1120, height: 780),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable],
                              backing: .buffered, defer: false)
        window.title = "Mi Band 6"
        window.minSize = NSSize(width: 360, height: 520)
        window.isReleasedWhenClosed = false
        window.appearance = NSAppearance(named: .darkAqua)   // giao diện web chỉ có nền tối
        window.backgroundColor = NSColor(srgbRed: 0x10 / 255, green: 0x16 / 255, blue: 0x15 / 255, alpha: 1)
        window.titlebarAppearsTransparent = true
        window.contentView = webView
        window.center()
        window.setFrameAutosaveName("MainWindow")
        super.init(window: window)
        window.delegate = self
        webView.navigationDelegate = self
        webView.uiDelegate = self
        showMessage(t("Đang khởi động…"))
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) không dùng") }

    /// Mở giao diện của server (bỏ qua nếu đang hiện đúng server đó).
    func load(_ url: URL) {
        let same = serverURL.map { $0.host == url.host && $0.port == url.port } ?? false
        serverURL = url
        if same, let current = webView.url, isServer(current) { return }
        webView.load(URLRequest(url: url))
    }

    func reload() {
        if let serverURL { webView.load(URLRequest(url: serverURL)) }
    }

    func showMessage(_ text: String) {
        let html = """
        <!doctype html><meta charset="utf-8"><body style="margin:0;height:100vh;display:flex;align-items:center;\
        justify-content:center;background:#101615;color:#95a5a1;font:15px -apple-system,sans-serif">\(text)</body>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    private func isServer(_ url: URL) -> Bool {
        guard let serverURL, let host = url.host else { return false }
        return ["127.0.0.1", "localhost"].contains(host) && url.port == serverURL.port
    }

    // MARK: NSWindowDelegate

    func windowWillClose(_ notification: Notification) {
        onClose?()
    }

    // MARK: WKNavigationDelegate

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if navigationAction.shouldPerformDownload {
            decisionHandler(.download)
            return
        }
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        if isServer(url) || ["about", "blob", "data"].contains(url.scheme ?? "") {
            decisionHandler(.allow)
        } else {
            // liên kết ra ngoài (hướng dẫn, đăng nhập Xiaomi) mở trong trình duyệt mặc định
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        // server chưa nhận kết nối (đang khởi động lại): thử lại. Bỏ qua các lỗi khác, ví dụ
        // "Frame load interrupted" khi một liên kết chuyển thành tải tệp.
        let e = error as NSError
        let retry = [NSURLErrorCannotConnectToHost, NSURLErrorNetworkConnectionLost, NSURLErrorTimedOut]
        guard e.domain == NSURLErrorDomain, retry.contains(e.code), let serverURL else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
            guard let self, self.serverURL == serverURL, !self.webView.isLoading else { return }
            self.webView.load(URLRequest(url: serverURL))
        }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        reload()
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }

    // MARK: WKUIDelegate

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        // target="_blank": mở trong trình duyệt thay vì cửa sổ mới
        if let url = navigationAction.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    // MARK: WKDownloadDelegate (nút "Tải về" nhật ký Bluetooth)

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let fm = FileManager.default
        let dir = fm.urls(for: .downloadsDirectory, in: .userDomainMask).first ?? fm.temporaryDirectory
        let name = (suggestedFilename as NSString).deletingPathExtension
        let ext = (suggestedFilename as NSString).pathExtension
        var url = dir.appendingPathComponent(suggestedFilename)
        var n = 1
        while fm.fileExists(atPath: url.path) {
            url = dir.appendingPathComponent(ext.isEmpty ? "\(name) (\(n))" : "\(name) (\(n)).\(ext)")
            n += 1
        }
        downloads[ObjectIdentifier(download)] = url
        completionHandler(url)
    }

    func downloadDidFinish(_ download: WKDownload) {
        if let url = downloads.removeValue(forKey: ObjectIdentifier(download)) {
            NSWorkspace.shared.activateFileViewerSelecting([url])
        }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloads.removeValue(forKey: ObjectIdentifier(download))
    }
}
