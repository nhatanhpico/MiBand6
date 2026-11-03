import AppKit
import MapKit
import WebKit

/// Bản đồ Apple Maps (MapKit) gắn ngay trong cửa sổ chính: một MKMapView nằm đúng chỗ khung bản đồ của hộp thoại
/// lộ trình trong trang web (không mở cửa sổ mới). Trang web gửi vị trí khung và các lộ trình qua
/// window.webkit.messageHandlers.nativeMap; bấm vào một lộ trình thì gọi lại window.nativeMapClick(id).
/// Bản web chạy trong trình duyệt vẫn dùng bản đồ OpenStreetMap của trang.
final class NativeMapController: NSObject, WKScriptMessageHandler, MKMapViewDelegate {
    private weak var webView: WKWebView?
    let mapView = RouteMapView()
    private let fitBox = NSVisualEffectView()
    private var routes: [RoutePolyline] = []
    private var mode = "one"

    private static let colors: [String: NSColor] = [
        "run": NSColor(srgbRed: 1.0, green: 0.71, blue: 0.28, alpha: 1),      // #ffb547, như màu cam của giao diện
        "walk": NSColor(srgbRed: 0.27, green: 0.88, blue: 0.64, alpha: 1),    // #46e0a4
        "ride": NSColor(srgbRed: 0.42, green: 0.66, blue: 1.0, alpha: 1),     // #6aa8ff
    ]

    init(webView: WKWebView) {
        self.webView = webView
        super.init()
        mapView.delegate = self
        mapView.isHidden = true
        mapView.wantsLayer = true
        mapView.layer?.cornerRadius = 14   // như khung bản đồ trong trang
        mapView.layer?.masksToBounds = true
        mapView.appearance = NSAppearance(named: .darkAqua)
        mapView.showsZoomControls = true
        mapView.showsCompass = true
        mapView.showsScale = true
        if #available(macOS 13.0, *) {
            mapView.preferredConfiguration = MKStandardMapConfiguration(elevationStyle: .flat, emphasisStyle: .muted)
        }
        mapView.onEscape = { [weak self] in self?.closeDialog() }
        let click = NSClickGestureRecognizer(target: self, action: #selector(mapClicked(_:)))
        click.delaysPrimaryMouseButtonEvents = false
        mapView.addGestureRecognizer(click)

        // nút "vừa lộ trình" ở góc trên trái
        fitBox.material = .hudWindow
        fitBox.blendingMode = .withinWindow
        fitBox.state = .active
        fitBox.wantsLayer = true
        fitBox.layer?.cornerRadius = 8
        fitBox.frame = NSRect(x: 0, y: 0, width: 34, height: 34)
        let fit = NSButton(frame: fitBox.bounds)
        fit.isBordered = false
        fit.image = NSImage(systemSymbolName: "arrow.up.left.and.arrow.down.right", accessibilityDescription: t("Vừa lộ trình"))
        fit.toolTip = t("Vừa lộ trình")
        fit.contentTintColor = .white
        fit.target = self
        fit.action = #selector(fitPressed)
        fit.autoresizingMask = [.width, .height]
        fitBox.addSubview(fit)
        fitBox.autoresizingMask = [.maxXMargin, .minYMargin]
        mapView.addSubview(fitBox)
        webView.addSubview(mapView)
    }

    // MARK: tin nhắn từ trang web

    /// {action: "show" | "rect" | "routes" | "fit" | "hide", rect: {x, y, width, height} (px CSS),
    ///  mode: "one" | "all", routes: [{id, kind, points: [[vĩ độ, kinh độ]]}], fit: bool}
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any], let action = body["action"] as? String else { return }
        switch action {
        case "show":
            place(body["rect"])
            setRoutes(body)
            mapView.isHidden = false
            if body["fit"] as? Bool ?? true { fitAll(animated: false) }
        case "rect":
            place(body["rect"])
        case "routes":
            setRoutes(body)
            if body["fit"] as? Bool ?? false { fitAll(animated: true) }
        case "fit":
            fitAll(animated: true)
        case "export":
            exportImage(body)
        default:
            hide()
        }
    }

    // MARK: xuất ảnh để chia sẻ

    /// Chụp bản đồ đang xem (MKMapSnapshotter), vẽ lộ trình, thêm phần chân (tiêu đề, ngày, số liệu), lưu PNG vào
    /// thư mục Tải về rồi mở bảng chia sẻ của macOS. body: {title, subtitle, stats: [[nhãn, giá trị, đơn vị]],
    /// legend: [[tên, loại]], anchor: {x, y, width, height}}
    private func exportImage(_ body: [String: Any]) {
        guard !mapView.isHidden, mapView.bounds.width > 10, let webView else { return }
        let options = MKMapSnapshotter.Options()
        options.region = mapView.region
        options.size = mapView.bounds.size
        options.appearance = NSAppearance(named: .darkAqua)
        if #available(macOS 14.0, *) {
            options.preferredConfiguration = MKStandardMapConfiguration(elevationStyle: .flat, emphasisStyle: .muted)
        }
        let lines = routes
        let mode = self.mode
        MKMapSnapshotter(options: options).start { [weak self] snapshot, error in
            guard let self else { return }
            guard let snapshot else {
                self.reportExport(nil, error: error?.localizedDescription ?? "snapshot")
                return
            }
            let image = Self.compose(snapshot, routes: lines, mode: mode, body: body)
            guard let tiff = image.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                  let png = rep.representation(using: .png, properties: [:]) else {
                self.reportExport(nil, error: "png")
                return
            }
            let url = Self.exportURL(title: body["title"] as? String ?? "Mi Band 6")
            do {
                try png.write(to: url)
            } catch {
                self.reportExport(nil, error: error.localizedDescription)
                return
            }
            self.reportExport(url, error: nil)
            var anchor = CGRect(x: webView.bounds.midX, y: 40, width: 1, height: 1)
            if let a = body["anchor"] as? [String: Any], let x = (a["x"] as? NSNumber)?.doubleValue,
               let y = (a["y"] as? NSNumber)?.doubleValue, let w = (a["width"] as? NSNumber)?.doubleValue,
               let h = (a["height"] as? NSNumber)?.doubleValue {
                let zoom = webView.pageZoom * webView.magnification
                anchor = CGRect(x: x * zoom, y: y * zoom, width: w * zoom, height: h * zoom)
                if !webView.isFlipped { anchor.origin.y = webView.bounds.height - anchor.origin.y - anchor.height }
            }
            NSSharingServicePicker(items: [url]).show(relativeTo: anchor, of: webView, preferredEdge: .minY)
        }
    }

    private func reportExport(_ url: URL?, error: String?) {
        let payload: [String: Any] = url.map { ["name": $0.lastPathComponent, "path": $0.path] } ?? ["error": error ?? ""]
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else { return }
        webView?.evaluateJavaScript("window.nativeMapExported && window.nativeMapExported(\(json))")
    }

    private static func exportURL(title: String) -> URL {
        let folder = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser
        let stamp = DateFormatter()
        stamp.dateFormat = "yyyy-MM-dd HH.mm"
        let clean = title.components(separatedBy: CharacterSet(charactersIn: "/:\\?%*|\"<>")).joined(separator: "-")
        var url = folder.appendingPathComponent("Mi Band 6 - \(clean) - \(stamp.string(from: Date())).png")
        var n = 2
        while FileManager.default.fileExists(atPath: url.path) {
            url = folder.appendingPathComponent("Mi Band 6 - \(clean) - \(stamp.string(from: Date())) (\(n)).png")
            n += 1
        }
        return url
    }

    /// Ảnh xuất: bản đồ + lộ trình ở trên, phần chân tối ở dưới (tiêu đề, ngày, số liệu, chú giải, nguồn bản đồ).
    static func compose(_ snapshot: MKMapSnapshotter.Snapshot, routes: [RoutePolyline], mode: String,
                                body: [String: Any]) -> NSImage {
        let mapSize = snapshot.image.size
        let stats = (body["stats"] as? [[String]] ?? []).filter { $0.count >= 2 }
        let legend = (body["legend"] as? [[String]] ?? []).filter { $0.count >= 2 }
        let footer: CGFloat = 92 + (stats.isEmpty ? 0 : 58) + (legend.isEmpty ? 0 : 26)
        let size = NSSize(width: mapSize.width, height: mapSize.height + footer)
        // snapshot.point(for:) tính từ góc dưới trái của ảnh (hệ tọa độ AppKit); vẽ ở đây tính từ góc trên trái
        func at(_ coord: CLLocationCoordinate2D) -> NSPoint {
            let p = snapshot.point(for: coord)
            return NSPoint(x: p.x, y: mapSize.height - p.y)
        }
        return NSImage(size: size, flipped: true) { _ in
            snapshot.image.draw(in: NSRect(origin: .zero, size: mapSize), from: .zero, operation: .copy,
                                fraction: 1, respectFlipped: true, hints: nil)
            for line in routes {   // lộ trình vẽ đè lên ảnh bản đồ, cùng màu với bản đồ trong ứng dụng
                let pts = line.points()
                let path = NSBezierPath()
                for i in 0..<line.pointCount {
                    let p = at(pts[i].coordinate)
                    if i == 0 { path.move(to: p) } else { path.line(to: p) }
                }
                path.lineCapStyle = .round
                path.lineJoinStyle = .round
                path.lineWidth = mode == "one" ? 7 : 5.5
                NSColor(srgbRed: 0.04, green: 0.06, blue: 0.055, alpha: 0.55).setStroke()
                path.stroke()
                path.lineWidth = mode == "one" ? 4.5 : 3.5
                (mode == "one" ? colors["run"]! : colors[line.kind] ?? colors["run"]!).setStroke()
                path.stroke()
                if mode == "one", line.pointCount > 1 {
                    for (coord, color) in [(pts[line.pointCount - 1].coordinate, NSColor(srgbRed: 1.0, green: 0.42, blue: 0.48, alpha: 1)),
                                           (pts[0].coordinate, colors["walk"]!)] {
                        let c = at(coord)
                        let dotRect = NSRect(x: c.x - 7, y: c.y - 7, width: 14, height: 14)
                        let dot = NSBezierPath(ovalIn: dotRect)
                        color.setFill()
                        dot.fill()
                        NSColor(srgbRed: 0.04, green: 0.06, blue: 0.055, alpha: 1).setStroke()
                        dot.lineWidth = 3
                        dot.stroke()
                    }
                }
            }
            let bg = NSColor(srgbRed: 0x10 / 255, green: 0x16 / 255, blue: 0x15 / 255, alpha: 1)
            bg.setFill()
            NSRect(x: 0, y: mapSize.height, width: size.width, height: footer).fill()
            let text = NSColor(srgbRed: 0.92, green: 0.95, blue: 0.94, alpha: 1)
            let muted = NSColor(srgbRed: 0.58, green: 0.65, blue: 0.63, alpha: 1)
            var y = mapSize.height + 22
            (body["title"] as? String ?? "").draw(at: NSPoint(x: 24, y: y), withAttributes: [
                .font: NSFont.systemFont(ofSize: 24, weight: .bold), .foregroundColor: text])
            y += 34
            (body["subtitle"] as? String ?? "").draw(at: NSPoint(x: 24, y: y), withAttributes: [
                .font: NSFont.systemFont(ofSize: 14), .foregroundColor: muted])
            y += 30
            var x: CGFloat = 24
            for item in stats {
                let value = item.count > 2 && !item[2].isEmpty ? "\(item[1]) \(item[2])" : item[1]
                let vAttr: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 20, weight: .bold), .foregroundColor: text]
                let lAttr: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 12), .foregroundColor: muted]
                value.draw(at: NSPoint(x: x, y: y), withAttributes: vAttr)
                item[0].draw(at: NSPoint(x: x, y: y + 28), withAttributes: lAttr)
                x += max((value as NSString).size(withAttributes: vAttr).width, (item[0] as NSString).size(withAttributes: lAttr).width) + 32
            }
            if !stats.isEmpty { y += 58 }
            x = 24
            for item in legend {
                (colors[item[1]] ?? colors["run"]!).setFill()
                NSBezierPath(roundedRect: NSRect(x: x, y: y + 6, width: 18, height: 5), xRadius: 2.5, yRadius: 2.5).fill()
                let attr: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 13), .foregroundColor: muted]
                item[0].draw(at: NSPoint(x: x + 26, y: y), withAttributes: attr)
                x += 26 + (item[0] as NSString).size(withAttributes: attr).width + 22
            }
            let credit = "Mi Band 6 · " + t("Bản đồ: Apple Maps")
            let cAttr: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 11), .foregroundColor: muted]
            let cw = (credit as NSString).size(withAttributes: cAttr).width
            credit.draw(at: NSPoint(x: size.width - cw - 20, y: size.height - 24), withAttributes: cAttr)
            return true
        }
    }

    func hide() {
        mapView.isHidden = true
        if let webView, webView.window?.firstResponder === mapView { webView.window?.makeFirstResponder(webView) }
    }

    /// Đặt bản đồ đúng chỗ khung trong trang (tọa độ CSS tính từ góc trên trái của vùng hiển thị).
    private func place(_ value: Any?) {
        guard let webView, let r = value as? [String: Any],
              let x = (r["x"] as? NSNumber)?.doubleValue, let y = (r["y"] as? NSNumber)?.doubleValue,
              let w = (r["width"] as? NSNumber)?.doubleValue, let h = (r["height"] as? NSNumber)?.doubleValue else { return }
        let zoom = webView.pageZoom * webView.magnification
        var frame = CGRect(x: x * zoom, y: y * zoom, width: max(0, w * zoom), height: max(0, h * zoom))
        if !webView.isFlipped { frame.origin.y = webView.bounds.height - frame.origin.y - frame.height }
        mapView.frame = frame.integral
        fitBox.frame.origin = NSPoint(x: 10, y: mapView.bounds.height - fitBox.frame.height - 10)
    }

    private func setRoutes(_ body: [String: Any]) {
        mode = body["mode"] as? String ?? "one"
        mapView.removeOverlays(mapView.overlays)
        mapView.removeAnnotations(mapView.annotations)
        routes = (body["routes"] as? [[String: Any]] ?? []).compactMap { item in
            let coords: [CLLocationCoordinate2D] = (item["points"] as? [[Any]] ?? []).compactMap { p in
                guard p.count >= 2, let lat = (p[0] as? NSNumber)?.doubleValue, let lon = (p[1] as? NSNumber)?.doubleValue
                else { return nil }
                return CLLocationCoordinate2D(latitude: lat, longitude: lon)
            }
            guard coords.count >= 2 else { return nil }
            let line = RoutePolyline(coordinates: coords, count: coords.count)
            line.routeID = (item["id"] as? NSNumber)?.intValue ?? 0
            line.kind = item["kind"] as? String ?? "run"
            return line
        }
        mapView.addOverlays(routes, level: .aboveRoads)
        if mode == "one", let line = routes.first {
            let points = line.points()
            mapView.addAnnotations([RouteEnd(coordinate: points[line.pointCount - 1].coordinate, isStart: false),
                                    RouteEnd(coordinate: points[0].coordinate, isStart: true)])
        }
    }

    private func fitAll(animated: Bool) {
        guard let first = routes.first else { return }
        var rect = routes.dropFirst().reduce(first.boundingMapRect) { $0.union($1.boundingMapRect) }
        let minSize = 2000.0   // điểm bản đồ: tránh phóng to quá mức với lộ trình rất ngắn
        if rect.size.width < minSize { rect = rect.insetBy(dx: -(minSize - rect.size.width) / 2, dy: 0) }
        if rect.size.height < minSize { rect = rect.insetBy(dx: 0, dy: -(minSize - rect.size.height) / 2) }
        mapView.setVisibleMapRect(rect, edgePadding: NSEdgeInsets(top: 48, left: 48, bottom: 48, right: 48), animated: animated)
    }

    @objc private func fitPressed() { fitAll(animated: true) }

    private func closeDialog() {
        webView?.evaluateJavaScript("document.querySelector('#mapDialog')?.close()")
        hide()
    }

    /// Bản đồ tổng: bấm (không kéo) gần một lộ trình thì mở buổi tập đó trong trang.
    @objc private func mapClicked(_ recognizer: NSClickGestureRecognizer) {
        guard mode == "all", let id = routeID(at: recognizer.location(in: mapView)) else { return }
        webView?.evaluateJavaScript("window.nativeMapClick && window.nativeMapClick(\(id))")
    }

    /// Lộ trình gần điểm p (trong mapView) nhất, nếu cách không quá 12 điểm.
    func routeID(at p: CGPoint) -> Int? {
        var best: (id: Int, distance: CGFloat)?
        for line in routes {
            let pts = line.points()
            var prev = mapView.convert(pts[0].coordinate, toPointTo: mapView)
            for i in 1..<line.pointCount {
                let cur = mapView.convert(pts[i].coordinate, toPointTo: mapView)
                let d = distance(p, prev, cur)
                if d < (best?.distance ?? 12) { best = (line.routeID, d) }
                prev = cur
            }
        }
        return best?.id
    }

    private func distance(_ p: CGPoint, _ a: CGPoint, _ b: CGPoint) -> CGFloat {
        let dx = b.x - a.x, dy = b.y - a.y
        let len = dx * dx + dy * dy
        let tt = len > 0 ? max(0, min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len)) : 0
        return hypot(p.x - (a.x + tt * dx), p.y - (a.y + tt * dy))
    }

    // MARK: MKMapViewDelegate

    func mapView(_ mapView: MKMapView, rendererFor overlay: MKOverlay) -> MKOverlayRenderer {
        guard let line = overlay as? RoutePolyline else { return MKOverlayRenderer(overlay: overlay) }
        let renderer = MKPolylineRenderer(polyline: line)
        renderer.strokeColor = mode == "one" ? Self.colors["run"] : Self.colors[line.kind] ?? Self.colors["run"]
        renderer.lineWidth = mode == "one" ? 5 : 3.5
        renderer.lineCap = .round
        renderer.lineJoin = .round
        return renderer
    }

    func mapView(_ mapView: MKMapView, viewFor annotation: MKAnnotation) -> MKAnnotationView? {
        guard let end = annotation as? RouteEnd else { return nil }
        let id = end.isStart ? "route-start" : "route-end"
        let view = mapView.dequeueReusableAnnotationView(withIdentifier: id) ?? MKAnnotationView(annotation: end, reuseIdentifier: id)
        view.annotation = end
        view.image = Self.dot(end.isStart ? Self.colors["walk"]! : NSColor(srgbRed: 1.0, green: 0.42, blue: 0.48, alpha: 1))
        view.displayPriority = .required
        view.canShowCallout = false
        return view
    }

    /// Chấm tròn có viền tối, giống chấm bắt đầu / kết thúc của bản đồ trong trang.
    private static func dot(_ color: NSColor) -> NSImage {
        NSImage(size: NSSize(width: 18, height: 18), flipped: false) { rect in
            let path = NSBezierPath(ovalIn: rect.insetBy(dx: 2, dy: 2))
            color.setFill()
            path.fill()
            NSColor(srgbRed: 0.04, green: 0.06, blue: 0.055, alpha: 1).setStroke()
            path.lineWidth = 3
            path.stroke()
            return true
        }
    }
}

final class RoutePolyline: MKPolyline {
    var routeID = 0
    var kind = "run"
}

final class RouteEnd: NSObject, MKAnnotation {
    let coordinate: CLLocationCoordinate2D
    let isStart: Bool

    init(coordinate: CLLocationCoordinate2D, isStart: Bool) {
        self.coordinate = coordinate
        self.isStart = isStart
    }
}

/// MKMapView bắt phím Esc để đóng hộp thoại bản đồ (khi bản đồ đang giữ bàn phím, trang web không nhận phím).
final class RouteMapView: MKMapView {
    var onEscape: (() -> Void)?

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 53 { onEscape?() } else { super.keyDown(with: event) }
    }
}

/// WKUserContentController giữ handler bằng tham chiếu mạnh; lớp trung gian này tránh vòng tham chiếu.
final class WeakMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: WKScriptMessageHandler?

    init(_ target: WKScriptMessageHandler) {
        self.target = target
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.userContentController(controller, didReceive: message)
    }
}
