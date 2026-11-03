import Foundation

/// Chạy server Python (Contents/Resources/run-server → miband6-web --app) làm tiến trình con.
///
/// Server in một dòng "MIBAND6_READY http://127.0.0.1:PORT/" khi sẵn sàng (hoặc khi đã có server
/// khác chạy sẵn trên cổng, ví dụ `uv run miband6-web` trong Terminal). Mọi dòng in ra được ghi vào
/// ~/Library/Logs/MiBand6Manager/server.log. Server thoát bất thường thì được chạy lại.
final class ServerProcess {
    static let readyPrefix = "MIBAND6_READY "
    static let port = 8766

    var onReady: ((URL) -> Void)?
    var onStopped: ((Int32) -> Void)?

    let logURL: URL
    private var process: Process?
    private var stopping = false
    private var failures = 0
    private var startedAt = Date()

    init() {
        let dir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/MiBand6Manager", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        logURL = dir.appendingPathComponent("server.log")
    }

    var isRunning: Bool { process?.isRunning ?? false }

    func start() {
        guard process == nil, !stopping else { return }
        let log = openLog()
        guard let script = Bundle.main.url(forResource: "run-server", withExtension: nil) else {
            log?.write(Data("Không tìm thấy Contents/Resources/run-server; hãy đóng gói lại bằng macos/build.sh\n".utf8))
            onStopped?(127)
            return
        }
        let p = Process()
        p.executableURL = script
        // open "Mi Band 6.app" --args --demo: xem thử với vòng tay giả lập, không dùng Bluetooth
        let demo = CommandLine.arguments.contains("--demo")
        p.arguments = ["--app", "--port", String(Self.port)] + (demo ? ["--demo"] : [])
        p.currentDirectoryURL = FileManager.default.homeDirectoryForCurrentUser
        p.standardInput = FileHandle.nullDevice
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe

        let reader = LineReader(log: log) { [weak self] line in
            guard line.hasPrefix(Self.readyPrefix) else { return }
            let text = line.dropFirst(Self.readyPrefix.count).trimmingCharacters(in: .whitespaces)
            guard let url = URL(string: text) else { return }
            DispatchQueue.main.async { self?.onReady?(url) }
        }
        pipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
            } else {
                reader.consume(data)
            }
        }
        p.terminationHandler = { [weak self] proc in
            let code = proc.terminationStatus
            DispatchQueue.main.async { self?.exited(code) }
        }
        do {
            startedAt = Date()
            try p.run()
            process = p
        } catch {
            log?.write(Data("Không chạy được server: \(error)\n".utf8))
            process = nil
            exited(126)
        }
    }

    /// Dừng server (SIGTERM để nó ngắt kết nối vòng tay gọn gàng; quá 5 giây thì SIGKILL).
    func stop(completion: @escaping () -> Void) {
        stopping = true
        guard let p = process, p.isRunning else {
            completion()
            return
        }
        p.terminate()
        DispatchQueue.global(qos: .userInitiated).async {
            let deadline = Date().addingTimeInterval(5)
            while p.isRunning && Date() < deadline { usleep(100_000) }
            if p.isRunning { kill(p.processIdentifier, SIGKILL) }
            DispatchQueue.main.async(execute: completion)
        }
    }

    private func exited(_ code: Int32) {
        process = nil
        guard !stopping else { return }
        onStopped?(code)
        failures = Date().timeIntervalSince(startedAt) > 60 ? 1 : failures + 1
        let delay = min(30.0, pow(2.0, Double(failures - 1)))
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in self?.start() }
    }

    private func openLog() -> FileHandle? {
        let fm = FileManager.default
        // giữ tệp nhật ký gọn: quá 5 MB thì bắt đầu tệp mới
        if let size = (try? fm.attributesOfItem(atPath: logURL.path))?[.size] as? Int, size > 5_000_000 {
            try? fm.removeItem(at: logURL)
        }
        if !fm.fileExists(atPath: logURL.path) {
            fm.createFile(atPath: logURL.path, contents: nil)
        }
        let handle = try? FileHandle(forWritingTo: logURL)
        handle?.seekToEndOfFile()
        handle?.write(Data("\n===== \(Date()) =====\n".utf8))
        return handle
    }
}

/// Ghép dữ liệu stdout thành từng dòng (chạy trên hàng đợi riêng của FileHandle, lần lượt từng khối).
private final class LineReader: @unchecked Sendable {
    private var pending = Data()
    private let log: FileHandle?
    private let onLine: (String) -> Void

    init(log: FileHandle?, onLine: @escaping (String) -> Void) {
        self.log = log
        self.onLine = onLine
    }

    func consume(_ data: Data) {
        log?.write(data)
        pending.append(data)
        while let newline = pending.firstIndex(of: 0x0A) {
            let lineData = pending[pending.startIndex..<newline]
            pending.removeSubrange(pending.startIndex...newline)
            if let line = String(data: lineData, encoding: .utf8) {
                onLine(line)
            }
        }
    }
}
