import Foundation

/// Trạng thái vòng tay rút gọn cho thanh menu, lấy từ state() của server.
struct BandSnapshot {
    var connected = false
    var busy = false
    var reconnectAttempt: Int?
    var name = ""
    var battery: Int?
    var charging = false
    var steps: Int?
    var heartRate: Int?
    var keepConnected = true
    var lang = "vi"
    var healthSyncState = "idle"
    var healthSyncStep = ""
    var healthSyncErrors: [String] = []
    var healthLastSync: Date?
    /// Vòng tay kết nối gần nhất: (địa chỉ, auth key, giao thức) để nút Kết nối trên thanh menu dùng lại.
    var lastDevice: (address: String, key: String, proto: String)?

    mutating func apply(state: [String: Any]) {
        connected = state["connected"] as? Bool ?? false
        busy = state["busy"] as? Bool ?? false
        reconnectAttempt = (state["reconnect"] as? [String: Any])?["attempt"] as? Int
        name = (state["device"] as? [String: Any])?["name"] as? String ?? ""
        let settings = state["settings"] as? [String: Any] ?? [:]
        keepConnected = settings["keep_connected"] as? Bool ?? true
        lang = settings["ui_lang"] as? String ?? lang
        applyHealth(state["health"] as? [String: Any] ?? [:])
        battery = nil
        steps = nil
        heartRate = nil
        for (kind, data) in state["live"] as? [String: Any] ?? [:] {
            apply(kind: kind, data: data)
        }
        lastDevice = nil
        if let address = state["last_device"] as? String,
           let saved = (state["saved_devices"] as? [[String: Any]])?.first(where: { $0["address"] as? String == address }) {
            lastDevice = (address, saved["auth_key"] as? String ?? "", saved["protocol"] as? String ?? "auto")
        }
    }

    /// Sync is owned by the background server and remains observable with the window closed.
    mutating func applyHealth(_ status: [String: Any]) {
        healthSyncState = status["state"] as? String ?? "idle"
        healthSyncStep = status["step"] as? String ?? ""
        healthSyncErrors = status["errors"] as? [String] ?? []
        healthLastSync = (status["last_sync"] as? NSNumber).map { Date(timeIntervalSince1970: $0.doubleValue) }
    }

    /// Cập nhật từ một sự kiện lẻ (pin, bước chân, nhịp tim). Trả về true nếu có thay đổi.
    @discardableResult
    mutating func apply(kind: String, data: Any?) -> Bool {
        switch kind {
        case "battery":
            let d = data as? [String: Any]
            battery = d?["level"] as? Int
            charging = d?["charging"] as? Bool ?? false
        case "activity":
            steps = (data as? [String: Any])?["steps"] as? Int
        case "heart_rate":
            heartRate = data as? Int
        default:
            return false
        }
        return true
    }
}

struct APIError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

/// Nghe /api/events (WebSocket) và gọi REST API của server, như trang web.
final class BandEvents {
    var onChange: ((BandSnapshot) -> Void)?
    var onEvent: ((String, Any?) -> Void)?
    private(set) var snapshot = BandSnapshot()
    private(set) var online = false

    private var base: URL?
    private var task: URLSessionWebSocketTask?
    private var generation = 0

    func connect(to base: URL) {
        if base == self.base, task != nil { return }
        self.base = base
        open()
    }

    private func open() {
        guard let base, var comps = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return }
        generation += 1
        let gen = generation
        task?.cancel(with: .goingAway, reason: nil)
        comps.scheme = "ws"
        comps.path = "/api/events"
        guard let url = comps.url else { return }
        let task = URLSession.shared.webSocketTask(with: url)
        self.task = task
        task.resume()
        receive(task, gen)
    }

    private func receive(_ task: URLSessionWebSocketTask, _ gen: Int) {
        task.receive { [weak self] result in
            DispatchQueue.main.async {
                guard let self, gen == self.generation else { return }
                switch result {
                case .success(let message):
                    if case .string(let text) = message { self.handle(text) }
                    self.receive(task, gen)
                case .failure:
                    self.task = nil
                    if self.online {
                        self.online = false
                        self.onChange?(self.snapshot)
                    }
                    // server đang khởi động lại: thử nối lại sau 2 giây
                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
                        guard let self, gen == self.generation else { return }
                        self.open()
                    }
                }
            }
        }
    }

    private func handle(_ text: String) {
        guard let data = text.data(using: .utf8),
              let msg = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let type = msg["type"] as? String else { return }
        switch type {
        case "hello", "state":
            guard let state = msg["state"] as? [String: Any] else { return }
            online = true
            snapshot.apply(state: state)
            onChange?(snapshot)
        case "disconnected", "device_event":
            onEvent?(type, type == "disconnected" ? msg["reconnecting"] : msg["data"])
        case "health":
            guard let status = msg["status"] as? [String: Any] else { return }
            snapshot.applyHealth(status)
            onChange?(snapshot)
        default:
            if snapshot.apply(kind: type, data: msg["data"]) {
                onChange?(snapshot)
            }
        }
    }

    // ------------------------------------------------------------ REST

    func post(_ path: String, _ body: [String: Any] = [:],
              done: ((Result<[String: Any], Error>) -> Void)? = nil) {
        guard let base, let url = URL(string: path, relativeTo: base) else {
            done?(.failure(APIError(message: t("Server chưa sẵn sàng."))))
            return
        }
        var req = URLRequest(url: url, timeoutInterval: 60)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: req) { data, _, error in
            let result: Result<[String: Any], Error>
            if let error {
                result = .failure(error)
            } else if let data, let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] {
                if let message = json["error"] as? String {
                    result = .failure(APIError(message: message))
                } else {
                    result = .success(json)
                }
            } else {
                result = .failure(APIError(message: t("Server trả về dữ liệu không hợp lệ.")))
            }
            DispatchQueue.main.async { done?(result) }
        }.resume()
    }
}
