// Vẽ biểu tượng ứng dụng (AppIcon.iconset) khi đóng gói; macos/build.sh gọi rồi chuyển sang .icns bằng iconutil.
//     xcrun swift macos/make_icon.swift <thư mục .iconset>
// Hình giống logo trong giao diện web: vòng tay màu bạc hà trên nền tối.

import AppKit

func color(_ r: Int, _ g: Int, _ b: Int) -> NSColor {
    NSColor(srgbRed: CGFloat(r) / 255, green: CGFloat(g) / 255, blue: CGFloat(b) / 255, alpha: 1)
}

func render(_ px: Int) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = NSSize(width: px, height: px)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSGraphicsContext.current!.cgContext.scaleBy(x: CGFloat(px) / 1024, y: CGFloat(px) / 1024)

    // nền: ô vuông bo góc theo khung biểu tượng macOS (824 trên 1024, bo 185), có bóng nhẹ
    let shape = NSBezierPath(roundedRect: NSRect(x: 100, y: 100, width: 824, height: 824), xRadius: 185, yRadius: 185)
    NSGraphicsContext.saveGraphicsState()
    let shadow = NSShadow()
    shadow.shadowColor = NSColor.black.withAlphaComponent(0.3)
    shadow.shadowOffset = NSSize(width: 0, height: -8)
    shadow.shadowBlurRadius = 20
    shadow.set()
    color(0x10, 0x16, 0x15).setFill()
    shape.fill()
    NSGraphicsContext.restoreGraphicsState()
    NSGradient(starting: color(0x26, 0x34, 0x31), ending: color(0x0e, 0x14, 0x13))!.draw(in: shape, angle: -90)

    // vòng tay: logo viewBox 24 (rect x7 y2 w10 h20 rx5, chấm cx12 cy13 r2.4) phóng 28 lần quanh tâm
    let mint = color(0x46, 0xe0, 0xa4)
    let band = NSBezierPath(roundedRect: NSRect(x: 372, y: 232, width: 280, height: 560), xRadius: 140, yRadius: 140)
    band.lineWidth = 46
    mint.setStroke()
    band.stroke()
    mint.setFill()
    NSBezierPath(ovalIn: NSRect(x: 512 - 67, y: 484 - 67, width: 134, height: 134)).fill()

    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

let out = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
for size in [16, 32, 128, 256, 512] {
    try render(size).write(to: out.appendingPathComponent("icon_\(size)x\(size).png"))
    try render(size * 2).write(to: out.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}
