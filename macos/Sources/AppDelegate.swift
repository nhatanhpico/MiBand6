import AppKit
import ServiceManagement
import UserNotifications

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate, UNUserNotificationCenterDelegate {
    private let server = ServerProcess()
    private let events = BandEvents()
    private var window: WebWindowController!
    private var statusItem: NSStatusItem!
    private var baseURL: URL?
    private var serverProblem: String?
    private var activity: NSObjectProtocol?
    private var launchedAtLogin = false
    // thông báo khi mất kết nối lâu: chỉ báo nếu sau 60 giây vẫn chưa nối lại được
    private var lostAt: Date?
    private var notifiedLost = false
    private var wasConnected = false

    private var canNotify: Bool { Bundle.main.bundleIdentifier != nil }

    // MARK: vòng đời ứng dụng

    func applicationWillFinishLaunching(_ notification: Notification) {
        if let event = NSAppleEventManager.shared().currentAppleEvent,
           event.eventID == AEEventID(kAEOpenApplication),
           event.paramDescriptor(forKeyword: AEKeyword(keyAEPropData))?.enumCodeValue == OSType(keyAELaunchedAsLogInItem) {
            launchedAtLogin = true
        }
        // mở cùng macOS: chỉ hiện trên thanh menu, không hiện cửa sổ và biểu tượng Dock
        NSApp.setActivationPolicy(launchedAtLogin ? .accessory : .regular)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // không để App Nap làm chậm việc nhận dữ liệu từ vòng tay khi ứng dụng chạy nền
        activity = ProcessInfo.processInfo.beginActivity(
            options: [.userInitiatedAllowingIdleSystemSleep, .suddenTerminationDisabled],
            reason: "Giữ kết nối Bluetooth với Mi Band 6")
        L10n.lang = Self.savedLanguage() ?? L10n.lang
        buildMainMenu()

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.imagePosition = .imageLeft
        statusItem.button?.font = NSFont.monospacedDigitSystemFont(ofSize: NSFont.systemFontSize, weight: .regular)
        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu
        updateStatusButton()

        window = WebWindowController()
        window.onClose = { [weak self] in self?.windowDidClose() }

        events.onChange = { [weak self] snap in self?.bandChanged(snap) }
        events.onEvent = { [weak self] kind, data in self?.bandEvent(kind, data) }
        server.onReady = { [weak self] url in self?.serverReady(url) }
        server.onStopped = { [weak self] code in
            guard let self else { return }
            self.serverProblem = t("Server đã dừng (mã {code}), đang chạy lại…", ["code": code])
            self.updateStatusButton()
        }
        server.start()

        NSWorkspace.shared.notificationCenter.addObserver(
            self, selector: #selector(systemDidWake), name: NSWorkspace.didWakeNotification, object: nil)
        if canNotify {
            UNUserNotificationCenter.current().delegate = self
            UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
        }
        if !launchedAtLogin { showWindow() }
    }

    /// Liên kết miband6://open?page=… (nút "Mở trong ứng dụng" của bản web): mở cửa sổ ở đúng trang.
    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls where url.scheme?.lowercased() == "miband6" {
            showWindow()
            let page = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                .queryItems?.first { $0.name == "page" }?.value
            if let page, !page.isEmpty { window.open(page: page) }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()   // bấm biểu tượng Dock hoặc mở lại ứng dụng từ Finder
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        server.stop { NSApp.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }

    // MARK: server

    private func serverReady(_ url: URL) {
        let changed = url != baseURL
        baseURL = url
        serverProblem = nil
        events.connect(to: url)
        window.load(url)
        if changed {
            L10n.load(from: url) { [weak self] in self?.languageChanged() }
        }
        updateStatusButton()
    }

    @objc private func systemDidWake(_ note: Notification) {
        // máy vừa thức dậy: vòng tay thường đã rớt kết nối; nhờ server thử nối lại ngay thay vì chờ hết lượt
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
            self?.events.post("/api/reconnect")
        }
    }

    // MARK: trạng thái vòng tay

    private func bandChanged(_ snap: BandSnapshot) {
        if snap.lang != L10n.lang {
            L10n.lang = snap.lang
            languageChanged()
        }
        if snap.connected && !wasConnected {
            if notifiedLost {
                notify(id: "connection", title: t("Đã kết nối lại với vòng tay"), body: snap.name)
            }
            lostAt = nil
            notifiedLost = false
        }
        wasConnected = snap.connected
        updateStatusButton()
    }

    private func bandEvent(_ kind: String, _ data: Any?) {
        switch kind {
        case "disconnected":
            let reconnecting = data as? Bool ?? false
            let at = Date()
            lostAt = at
            DispatchQueue.main.asyncAfter(deadline: .now() + 60) { [weak self] in
                guard let self, self.lostAt == at, !self.events.snapshot.connected else { return }
                self.notifiedLost = true
                self.notify(id: "connection", title: t("Mất kết nối với vòng tay"),
                            body: reconnecting ? t("Ứng dụng vẫn đang tự kết nối lại.") : "")
            }
        case "device_event":
            if data as? Int == 0x08 {   // vòng tay bấm "Tìm điện thoại": server đang phát âm thanh
                notify(id: "find-phone", title: t("Vòng tay đang tìm máy Mac"),
                       body: t("Bấm vào thông báo này để tắt âm thanh."))
            }
        default:
            break
        }
    }

    private func updateStatusButton() {
        guard let button = statusItem?.button else { return }
        let snap = events.snapshot
        let connected = events.online && snap.connected
        button.image = Icons.band(connected: connected)
        button.appearsDisabled = !(connected || (events.online && (snap.busy || snap.reconnectAttempt != nil)))
        if connected, let battery = snap.battery {
            button.title = " \(battery)%"
        } else if events.online && (snap.busy || snap.reconnectAttempt != nil) {
            button.title = " …"
        } else {
            button.title = ""
        }
        button.toolTip = statusLine()
    }

    private func statusLine() -> String {
        let snap = events.snapshot
        if let serverProblem { return serverProblem }
        if !events.online { return t("Đang khởi động…") }
        if snap.connected { return t("{name}: đã kết nối", ["name": snap.name.isEmpty ? "Mi Band 6" : snap.name]) }
        if snap.busy { return t("Đang kết nối…") }
        if let n = snap.reconnectAttempt { return t("Đang chờ kết nối lại (lần {n})…", ["n": n]) }
        return t("Chưa kết nối")
    }

    private func detailLine() -> String? {
        let snap = events.snapshot
        guard events.online, snap.connected else { return nil }
        var parts: [String] = []
        if let b = snap.battery { parts.append(t("Pin {n}%", ["n": b]) + (snap.charging ? " ⚡" : "")) }
        if let s = snap.steps {
            let f = NumberFormatter()
            f.numberStyle = .decimal
            f.locale = L10n.locale
            parts.append(t("{n} bước", ["n": f.string(from: NSNumber(value: s)) ?? "\(s)"]))
        }
        if let hr = snap.heartRate { parts.append("♥ \(hr)") }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    // MARK: menu trên thanh menu

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        let snap = events.snapshot
        let online = events.online

        menu.addItem(disabledItem(statusLine()))
        if let detail = detailLine() { menu.addItem(disabledItem(detail)) }
        menu.addItem(.separator())
        menu.addItem(item(t("Mở cửa sổ Mi Band 6"), #selector(openWindow), key: "o"))
        menu.addItem(item(t("Mở trong trình duyệt"), #selector(openInBrowser), enabled: baseURL != nil))
        menu.addItem(.separator())

        if online && !snap.connected && !snap.busy {
            if snap.reconnectAttempt != nil {
                menu.addItem(item(t("Thử kết nối lại ngay"), #selector(reconnectNow)))
            } else if snap.lastDevice != nil {
                menu.addItem(item(t("Kết nối"), #selector(connectLast)))
            }
        }
        if online && (snap.connected || snap.reconnectAttempt != nil) {
            menu.addItem(item(t("Ngắt kết nối"), #selector(disconnectBand)))
        }
        if online && snap.connected {
            menu.addItem(item(t("Rung vòng tay"), #selector(findBand)))
            menu.addItem(item(t("Đồng bộ dữ liệu sức khỏe"), #selector(syncHealth)))
        }
        if menu.items.last?.isSeparatorItem == false { menu.addItem(.separator()) }

        let keep = item(t("Giữ kết nối (tự kết nối lại)"), #selector(toggleKeepConnected), enabled: online)
        keep.state = snap.keepConnected ? .on : .off
        menu.addItem(keep)
        if #available(macOS 13, *) {
            let login = item(t("Mở cùng macOS"), #selector(toggleLaunchAtLogin))
            login.state = SMAppService.mainApp.status == .enabled ? .on : .off
            menu.addItem(login)
        }
        menu.addItem(.separator())
        menu.addItem(item(t("Mở nhật ký server"), #selector(openServerLog)))
        menu.addItem(item(t("Thoát Mi Band 6"), #selector(NSApplication.terminate(_:)), key: "q", target: NSApp))
    }

    private func item(_ title: String, _ action: Selector, key: String = "", enabled: Bool = true,
                      target: AnyObject? = nil) -> NSMenuItem {
        let it = NSMenuItem(title: title, action: enabled ? action : nil, keyEquivalent: key)
        it.target = target ?? self
        return it
    }

    private func disabledItem(_ title: String) -> NSMenuItem {
        let it = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        it.isEnabled = false
        return it
    }

    @objc private func openWindow() { showWindow() }

    @objc private func openInBrowser() {
        guard let port = baseURL?.port, let url = URL(string: "http://localhost:\(port)/") else { return }
        NSWorkspace.shared.open(url)
    }

    @objc private func reconnectNow() { events.post("/api/reconnect", done: reportError) }

    @objc private func connectLast() {
        guard let d = events.snapshot.lastDevice else { return }
        events.post("/api/connect", ["address": d.address, "key": d.key, "protocol": d.proto], done: reportError)
    }

    @objc private func disconnectBand() { events.post("/api/disconnect", done: reportError) }

    @objc private func findBand() { events.post("/api/find", ["on": true], done: reportError) }

    @objc private func syncHealth() { events.post("/api/health/sync", done: reportError) }

    @objc private func toggleKeepConnected() {
        events.post("/api/prefs", ["keep_connected": !events.snapshot.keepConnected], done: reportError)
    }

    @objc private func toggleLaunchAtLogin() {
        guard #available(macOS 13, *) else { return }
        let service = SMAppService.mainApp
        do {
            if service.status == .enabled {
                try service.unregister()
            } else {
                try service.register()
                if service.status == .requiresApproval { SMAppService.openSystemSettingsLoginItems() }
            }
        } catch {
            showError(t("Không đổi được tùy chọn mở cùng macOS: {error}", ["error": error.localizedDescription]))
        }
    }

    @objc private func openServerLog() { NSWorkspace.shared.open(server.logURL) }

    @objc private func reloadPage() { window.reload() }

    private func reportError(_ result: Result<[String: Any], Error>) {
        if case .failure(let error) = result { showError(error.localizedDescription) }
    }

    private func showError(_ message: String) {
        activate()
        let alert = NSAlert()
        alert.messageText = "Mi Band 6"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.runModal()
    }

    // MARK: cửa sổ và Dock

    private func showWindow() {
        NSApp.setActivationPolicy(.regular)
        window.showWindow(nil)
        window.window?.makeKeyAndOrderFront(nil)
        activate()
    }

    private func windowDidClose() {
        // chỉ còn biểu tượng trên thanh menu; server và kết nối Bluetooth vẫn chạy
        NSApp.setActivationPolicy(.accessory)
    }

    private func activate() {
        if #available(macOS 14, *) {
            NSApp.activate()
        } else {
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    // MARK: menu chính (khi cửa sổ đang mở)

    private func languageChanged() {
        buildMainMenu()
        updateStatusButton()
    }

    private func buildMainMenu() {
        let main = NSMenu()

        let appMenu = NSMenu()
        appMenu.addItem(withTitle: t("Giới thiệu Mi Band 6"), action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: t("Ẩn Mi Band 6"), action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: t("Thoát Mi Band 6"), action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        main.addItem(submenu(appMenu, title: "Mi Band 6"))

        // menu Sửa: để Cmd+C / Cmd+V / Cmd+A hoạt động trong các ô nhập của trang web
        let edit = NSMenu(title: t("Sửa"))
        edit.addItem(withTitle: t("Hoàn tác"), action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: t("Làm lại"), action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: t("Cắt"), action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: t("Sao chép"), action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: t("Dán"), action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: t("Chọn tất cả"), action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        main.addItem(submenu(edit, title: edit.title))

        let view = NSMenu(title: t("Xem"))
        view.addItem(item(t("Tải lại trang"), #selector(reloadPage), key: "r"))
        view.addItem(item(t("Mở trong trình duyệt"), #selector(openInBrowser)))
        main.addItem(submenu(view, title: view.title))

        let windowMenu = NSMenu(title: t("Cửa sổ"))
        windowMenu.addItem(withTitle: t("Thu nhỏ"), action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: t("Đóng"), action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        main.addItem(submenu(windowMenu, title: windowMenu.title))

        NSApp.mainMenu = main
        NSApp.windowsMenu = windowMenu
    }

    private func submenu(_ menu: NSMenu, title: String) -> NSMenuItem {
        let it = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        it.submenu = menu
        return it
    }

    /// Ngôn ngữ đã chọn trong giao diện web (lưu trong config.json), để menu đúng ngôn ngữ ngay từ đầu.
    private static func savedLanguage() -> String? {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/MiBand6Manager/config.json")
        guard let data = try? Data(contentsOf: url),
              let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
        return (json["settings"] as? [String: Any])?["ui_lang"] as? String
    }

    // MARK: thông báo macOS

    private func notify(id: String, title: String, body: String) {
        guard canNotify else { return }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: id, content: content, trigger: nil))
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let id = response.notification.request.identifier
        DispatchQueue.main.async { [weak self] in
            if id == "find-phone" {
                self?.events.post("/api/find-phone/stop")
            } else {
                self?.showWindow()
            }
        }
        completionHandler()
    }
}
