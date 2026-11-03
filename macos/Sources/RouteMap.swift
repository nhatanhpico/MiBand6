import AppKit
import MapKit

/// Cửa sổ bản đồ Apple Maps (MapKit) cho lộ trình GPS của một buổi tập. Trang web trong ứng dụng gửi lộ trình
/// qua window.webkit.messageHandlers.routeMap; bản web chạy trong trình duyệt vẫn dùng bản đồ OpenStreetMap.
final class RouteMapWindowController: NSWindowController, NSWindowDelegate, MKMapViewDelegate {
    var onClose: (() -> Void)?
    private let mapView = MKMapView()
    private var route: MKPolyline?

    /// body: {title, subtitle, points: [[ts, lat, lon]], stats: [[nhãn, giá trị, đơn vị]]}
    init?(body: [String: Any]) {
        let coords: [CLLocationCoordinate2D] = (body["points"] as? [[Any]] ?? []).compactMap { p in
            guard p.count >= 3, let lat = (p[1] as? NSNumber)?.doubleValue, let lon = (p[2] as? NSNumber)?.doubleValue
            else { return nil }
            return CLLocationCoordinate2D(latitude: lat, longitude: lon)
        }
        guard coords.count >= 2 else { return nil }

        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 960, height: 680),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        let title = body["title"] as? String ?? "Mi Band 6"
        let subtitle = body["subtitle"] as? String ?? ""
        window.title = subtitle.isEmpty ? title : "\(title) · \(subtitle)"
        window.minSize = NSSize(width: 480, height: 400)
        window.appearance = NSAppearance(named: .darkAqua)
        window.isReleasedWhenClosed = false
        window.center()
        super.init(window: window)
        window.delegate = self

        mapView.delegate = self
        mapView.showsCompass = true
        mapView.showsScale = true
        mapView.showsZoomControls = true
        mapView.translatesAutoresizingMaskIntoConstraints = false

        let polyline = MKPolyline(coordinates: coords, count: coords.count)
        route = polyline
        mapView.addOverlay(polyline)
        let start = MKPointAnnotation()
        start.coordinate = coords[0]
        start.title = t("Bắt đầu")
        let end = MKPointAnnotation()
        end.coordinate = coords[coords.count - 1]
        end.title = t("Kết thúc")
        mapView.addAnnotations([start, end])

        let stats = NSStackView()
        stats.orientation = .horizontal
        stats.spacing = 28
        stats.edgeInsets = NSEdgeInsets(top: 12, left: 20, bottom: 14, right: 20)
        stats.translatesAutoresizingMaskIntoConstraints = false
        for item in body["stats"] as? [[String]] ?? [] where item.count >= 2 {
            let value = NSTextField(labelWithString: item.count > 2 && !item[2].isEmpty ? "\(item[1]) \(item[2])" : item[1])
            value.font = .systemFont(ofSize: 18, weight: .bold)
            let label = NSTextField(labelWithString: item[0])
            label.font = .systemFont(ofSize: 11.5)
            label.textColor = .secondaryLabelColor
            let column = NSStackView(views: [value, label])
            column.orientation = .vertical
            column.alignment = .leading
            column.spacing = 2
            stats.addArrangedSubview(column)
        }

        let content = NSView()
        content.addSubview(mapView)
        content.addSubview(stats)
        NSLayoutConstraint.activate([
            mapView.topAnchor.constraint(equalTo: content.topAnchor),
            mapView.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            mapView.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            mapView.bottomAnchor.constraint(equalTo: stats.topAnchor),
            stats.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            stats.trailingAnchor.constraint(lessThanOrEqualTo: content.trailingAnchor),
            stats.bottomAnchor.constraint(equalTo: content.bottomAnchor),
        ])
        window.contentView = content
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) không dùng") }

    func show() {
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
        if let route {   // vừa khung với lộ trình, chừa lề
            mapView.setVisibleMapRect(route.boundingMapRect,
                                      edgePadding: NSEdgeInsets(top: 60, left: 60, bottom: 60, right: 60), animated: false)
        }
    }

    func windowWillClose(_ notification: Notification) {
        onClose?()
    }

    // MARK: MKMapViewDelegate

    func mapView(_ mapView: MKMapView, rendererFor overlay: MKOverlay) -> MKOverlayRenderer {
        guard let line = overlay as? MKPolyline else { return MKOverlayRenderer(overlay: overlay) }
        let renderer = MKPolylineRenderer(polyline: line)
        renderer.strokeColor = NSColor(srgbRed: 1.0, green: 0.71, blue: 0.28, alpha: 1)   // cùng màu cam của giao diện
        renderer.lineWidth = 5
        renderer.lineCap = .round
        renderer.lineJoin = .round
        return renderer
    }

    func mapView(_ mapView: MKMapView, viewFor annotation: MKAnnotation) -> MKAnnotationView? {
        guard annotation is MKPointAnnotation else { return nil }
        let view = MKMarkerAnnotationView(annotation: annotation, reuseIdentifier: "route-point")
        let isStart = annotation.title == t("Bắt đầu")
        view.markerTintColor = isStart
            ? NSColor(srgbRed: 0.27, green: 0.88, blue: 0.64, alpha: 1)
            : NSColor(srgbRed: 1.0, green: 0.42, blue: 0.48, alpha: 1)
        view.glyphText = isStart ? "▶︎" : "■"
        view.displayPriority = .required
        return view
    }
}
