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

    // MARK: - Texture Capabilities
    var textureCapabilities: [String: Any] = [:]
    
    if #available(macOS 10.15, *) {
        textureCapabilities["max_texture_width"] = device.maxTextureWidth
        textureCapabilities["max_texture_height"] = device.maxTextureHeight
    }
    
    if #available(macOS 10.15, *) {
        textureCapabilities["max_texture_depth"] = device.maxTextureDepth
    }
    
    if #available(macOS 11.0, *) {
        textureCapabilities["max_texture_buffer_width"] = device.maxTextureBufferWidth
    }
    
    info["texture_capabilities"] = textureCapabilities

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
        families["mac1"] = device.supportsFamily(.mac1)
        families["mac2"] = device.supportsFamily(.mac2)
    }

    // Apple GPU families (iPhone/iPad)
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

    // MARK: - Feature Detection (Ray Tracing & Rendering)
    if #available(macOS 11.0, *) {
        info["supports_raytracing"] = device.supportsRaytracing
        info["supports_pull_model_interpolation"] = device.supportsPullModelInterpolation
    }

    // MARK: - Shader & Memory Features
    var shaderFeatures: [String: Bool] = [:]
    
    if #available(macOS 13.0, *) {
        shaderFeatures["supports_dynamic_library_compilation"] = device.supportsDynamicLibraryCompilation
        shaderFeatures["supports_function_pointers"] = device.supportsFunctionPointers
        shaderFeatures["supports_function_pointer_from_render_command_encoder"] = device.supportsFunctionPointerFromRenderCommandEncoder
    }
    
    if #available(macOS 14.0, *) {
        shaderFeatures["supports_binary_library_compilation"] = device.supportsBinaryLibraryCompilation
    }
    
    if #available(macOS 15.0, *) {
        shaderFeatures["supports_gpu_kernel_work_groups"] = true // GPU kernel work groups
    }
    
    info["shader_features"] = shaderFeatures

    // MARK: - Advanced Rendering Features
    var advancedFeatures: [String: Bool] = [:]
    
    let supportsMac2 = families["mac2"] ?? false
    let supportsApple7 = families["apple7"] ?? false
    let supportsApple9 = families["apple9"] ?? false
    let supportsApple10 = families["apple10"] ?? false

    advancedFeatures["supports_mesh_shading"] = supportsMac2 || supportsApple7
    advancedFeatures["supports_indirect_mesh_draw_arguments"] = supportsApple9
    advancedFeatures["supports_icb_mesh_draws"] = supportsApple9
    
    if #available(macOS 11.0, *) {
        advancedFeatures["supports_barycentric_coordinates"] = device.supportsBarycentricCoordinates
    }
    
    if #available(macOS 13.0, *) {
        advancedFeatures["supports_quadgroup"] = device.supportsQuadGroup
    }
    
    if #available(macOS 14.0, *) {
        advancedFeatures["supports_simdgroup_matrix"] = true
        advancedFeatures["supports_texture_swizzle"] = true
    }
    
    if #available(macOS 15.0, *) {
        advancedFeatures["supports_minimal_bvh_stride"] = true
        advancedFeatures["supports_gpu_driven_rasterization"] = true
    }
    
    if #available(macOS 16.0, *) {
        advancedFeatures["supports_advanced_ray_tracing"] = true
    }
    
    info["advanced_rendering_features"] = advancedFeatures

    // MARK: - Argument Buffer Support
    var argumentBufferSupport: [String: Bool] = [:]
    if #available(macOS 10.13, *) {
        argumentBufferSupport["supports_argument_buffers"] = device.supportsArgumentBuffers
    }
    if #available(macOS 13.0, *) {
        argumentBufferSupport["supports_extended_argument_buffer"] = true
    }
    info["argument_buffer_support"] = argumentBufferSupport

    // MARK: - Sparse Resources & Memory Features
    var memoryFeatures: [String: Bool] = [:]
    if #available(macOS 13.0, *) {
        memoryFeatures["supports_sparse_resources"] = device.supportsSparseTiling
    }
    if #available(macOS 11.0, *) {
        memoryFeatures["has_unified_memory"] = device.hasUnifiedMemory
    }
    info["memory_features"] = memoryFeatures

    // MARK: - Concurrent Encoding
    if #available(macOS 13.0, *) {
        info["supports_concurrent_compilation"] = device.supportsDynamicLibraryCompilation
    }

    // MARK: - Version & Metal Standards
    var metalStandards: [String: Any] = [:]
    if #available(macOS 10.15, *) {
        metalStandards["metal_version"] = "Metal 3.0+"
    }
    if #available(macOS 13.0, *) {
        metalStandards["metal_version"] = "Metal 3.1+"
    }
    if #available(macOS 14.0, *) {
        metalStandards["metal_version"] = "Metal 3.2+"
    }
    if #available(macOS 15.0, *) {
        metalStandards["metal_version"] = "Metal 3.3+"
    }
    if #available(macOS 16.0, *) {
        metalStandards["metal_version"] = "Metal 3.4+"
    }
    info["metal_standards"] = metalStandards

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
