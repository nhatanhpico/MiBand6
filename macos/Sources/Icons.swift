import AppKit

enum Icons {
    /// Biểu tượng vòng tay cho thanh menu (cùng hình với logo trong giao diện web: viewBox 24, thu về 18 pt).
    /// connected: chấm màn hình tô đặc; chưa kết nối: chỉ viền.
    static func band(connected: Bool) -> NSImage {
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: true) { _ in
            NSColor.black.set()
            let body = NSBezierPath(roundedRect: NSRect(x: 5.25, y: 1.5, width: 7.5, height: 15), xRadius: 3.75, yRadius: 3.75)
            body.lineWidth = 1.5
            body.stroke()
            let screen = NSBezierPath(ovalIn: NSRect(x: 9 - 1.8, y: 9.75 - 1.8, width: 3.6, height: 3.6))
            if connected {
                screen.fill()
            } else {
                screen.lineWidth = 1.1
                screen.stroke()
            }
            return true
        }
        image.isTemplate = true
        return image
    }
}
