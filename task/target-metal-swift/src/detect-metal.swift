import Foundation
import Metal

func boolDict(_ device: MTLDevice) -> [String: Bool] {
    var out: [String: Bool] = [:]
    if #available(macOS 10.15, *) {
        out["mac2"] = device.supportsFamily(.mac2)
    }
    out["mac1"] = device.supportsFamily(.mac1)
    return out
}

if let device = MTLCreateSystemDefaultDevice() {
    let info: [String: Any] = [
        "available": true,
        "name": device.name,
        "isLowPower": device.isLowPower,
        "isHeadless": device.isHeadless,
        "hasUnifiedMemory": {
            if #available(macOS 10.15, *) { return device.hasUnifiedMemory }
            return false
        }(),
        "supportsRaytracing": {
            if #available(macOS 11.0, *) { return device.supportsRaytracing }
            return false
        }(),
        "families": boolDict(device)
    ]

    let data = try JSONSerialization.data(withJSONObject: info, options: [.prettyPrinted])
    print(String(data: data, encoding: .utf8)!)
} else {
    print("{\"available\":false}")
}
