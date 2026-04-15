import Foundation
import Metal

func getMetalInfo() -> [String: Any] {
    guard let device = MTLCreateSystemDefaultDevice() else {
        return [
            "available": false,
            "error": "No Metal device found"
        ]
    }

    var info: [String: Any] = [
        "available": true,
        "name": device.name,
        "is_low_power": device.isLowPower,
        "is_headless": device.isHeadless,
        "is_removable": device.isRemovable
    ]

    // MARK: - Basic Device Capabilities
    if #available(macOS 10.15, *) {
        info["has_unified_memory"] = device.hasUnifiedMemory
    }

    // MARK: - Memory Information
    info["recommended_max_working_set_size"] = device.recommendedMaxWorkingSetSize
    
    if #available(macOS 10.13, *) {
        info["max_buffer_length"] = device.maxBufferLength
    }
    
    if #available(macOS 11.0, *) {
        info["current_allocated_size"] = device.currentAllocatedSize
        info["max_threadgroup_memory_length"] = device.maxThreadgroupMemoryLength
    }

    // MARK: - Compute Capabilities
    let tg = device.maxThreadsPerThreadgroup
    info["max_threads_per_threadgroup"] = [
        "width": tg.width,
        "height": tg.height,
        "depth": tg.depth
    ]

    // MARK: - GPU Families
    var families: [String: Bool] = [:]

    // Mac GPU families
    if #available(macOS 10.15, *) {
        families["mac2"] = device.supportsFamily(.mac2)
    }

    // Apple GPU families
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

    if #available(macOS 16.0, *) {
        families["apple10"] = device.supportsFamily(.apple10)
    }

    info["gpu_families"] = families

    // MARK: - Feature Detection
    if #available(macOS 11.0, *) {
        info["supports_raytracing"] = device.supportsRaytracing
        info["supports_pull_model_interpolation"] = device.supportsPullModelInterpolation
    }

    // MARK: - Rendering Features (inferred from family support)
    var renderingFeatures: [String: Bool] = [:]
    
    let supportsMac2 = families["mac2"] ?? false
    let supportsApple7 = families["apple7"] ?? false
    let supportsApple9 = families["apple9"] ?? false

    renderingFeatures["supports_mesh_shading"] = supportsMac2 || supportsApple7
    renderingFeatures["supports_indirect_mesh_draw_arguments"] = supportsApple9
    renderingFeatures["supports_icb_mesh_draws"] = supportsApple9
    
    info["rendering_features"] = renderingFeatures

    // MARK: - Metal Version Detection
    var metalVersion: String = "Metal 3.0+"
    if #available(macOS 13.0, *) {
        metalVersion = "Metal 3.1+"
    }
    if #available(macOS 14.0, *) {
        metalVersion = "Metal 3.2+"
    }
    if #available(macOS 15.0, *) {
        metalVersion = "Metal 3.3+"
    }
    if #available(macOS 16.0, *) {
        metalVersion = "Metal 3.4+"
    }
    info["metal_version"] = metalVersion

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
