import Foundation
import Metal

func getMetalInfo() -> [String: Any] {
    guard let device = MTLCreateSystemDefaultDevice() else {
        return [
            "available": false
        ]
    }

    var info: [String: Any] = [
        "available": true,
        "name": device.name,
        "is_low_power": device.isLowPower,
        "is_headless": device.isHeadless,
        "is_removable": device.isRemovable
    ]

    if #available(macOS 10.15, *) {
        info["has_unified_memory"] = device.hasUnifiedMemory
    }

    if #available(macOS 11.0, *) {
        info["supports_raytracing"] = device.supportsRaytracing
    }

    if #available(macOS 11.0, *) {
        info["supports_pull_model_interpolation"] = device.supportsPullModelInterpolation
    }

    let tg = device.maxThreadsPerThreadgroup
    info["max_threads_per_threadgroup"] = [
        "width": tg.width,
        "height": tg.height,
        "depth": tg.depth
    ]

    info["recommended_max_working_set_size"] = device.recommendedMaxWorkingSetSize

    var families: [String: Bool] = [:]

    if #available(macOS 10.15, *) {
        families["mac2"] = device.supportsFamily(.mac2)
    }

    if #available(macOS 11.0, *) {
        families["apple1"] = device.supportsFamily(.apple1)
        families["apple2"] = device.supportsFamily(.apple2)
        families["apple3"] = device.supportsFamily(.apple3)
        families["apple4"] = device.supportsFamily(.apple4)
        families["apple5"] = device.supportsFamily(.apple5)
    }

    if #available(macOS 13.0, *) {
        families["apple6"] = device.supportsFamily(.apple6)
        families["apple7"] = device.supportsFamily(.apple7)
    }

    if #available(macOS 14.0, *) {
        families["apple8"] = device.supportsFamily(.apple8)
    }

    if #available(macOS 15.0, *) {
        families["apple9"] = device.supportsFamily(.apple9)
    }

    info["families"] = families

    // Infer higher-level features from family support where Apple documents
    // capability by GPU family in the Metal Feature Set Tables.
    let supportsMac2 = families["mac2"] ?? false
    let supportsApple7 = families["apple7"] ?? false
    let supportsApple9 = families["apple9"] ?? false

    info["supports_mesh_shading"] = supportsMac2 || supportsApple7
    info["supports_indirect_mesh_draw_arguments"] = supportsApple9
    info["supports_icb_mesh_draws"] = supportsApple9

    return info
}

// Main
let args = CommandLine.arguments
let outputPath = args.count > 1 ? args[1] : nil
let info = getMetalInfo()

do {
    let jsonData = try JSONSerialization.data(withJSONObject: info, options: [.prettyPrinted, .sortedKeys])

    if let path = outputPath, !path.isEmpty {
        let url = URL(fileURLWithPath: path)
        try jsonData.write(to: url, options: .atomic)
    } else {
        FileHandle.standardOutput.write(jsonData)
        FileHandle.standardOutput.write("\n".data(using: .utf8)!)
    }
} catch {
    fputs("Error: \(error)\n", stderr)
    exit(1)
}
