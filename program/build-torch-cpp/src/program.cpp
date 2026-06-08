/*
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.

Simple sanity-check for the LibTorch C++ API (libtorch).
Prints version info, device availability, and runs a small matmul.
*/

#include <fstream>
#include <iostream>

#include <torch/torch.h>

int main()
{
    // ------------------------------------------------------------------
    // Version
    std::cout << "================================================================\n";
    std::cout << "LibTorch C++ API sanity check\n";
    std::cout << "================================================================\n";
    std::cout << "LibTorch version : "
              << TORCH_VERSION_MAJOR << "."
              << TORCH_VERSION_MINOR << "."
              << TORCH_VERSION_PATCH << "\n";

    // ------------------------------------------------------------------
    // Device selection
    torch::DeviceType device_type = torch::kCPU;
    std::string device_name = "cpu";

    if (torch::cuda::is_available()) {
        device_type = torch::kCUDA;
        device_name = "cuda";
        std::cout << "CUDA             : available (" << torch::cuda::device_count() << " device(s))\n";
    } else {
        std::cout << "CUDA             : not available\n";
    }

    std::cout << "Selected device  : " << device_name << "\n\n";

    // ------------------------------------------------------------------
    // Simple matmul: (4x4 ones) * (4x4 ones) = 4x4 fours  → sum = 64
    torch::Device device(device_type);

    auto a = torch::ones({4, 4}, device);
    auto b = torch::ones({4, 4}, device);
    auto c = torch::matmul(a, b);

    float matmul_sum = c.sum().item<float>();
    std::cout << "Matmul (4x4 ones) sum : " << matmul_sum << "  (expected 64)\n\n";

    bool ok = (matmul_sum == 64.0f);
    std::cout << "Result : " << (ok ? "PASSED" : "FAILED") << "\n";

    // ------------------------------------------------------------------
    // Write output.txt for cMeta result capture
    std::ofstream out("output.txt");
    if (!out) {
        std::cerr << "Warning: could not write output.txt\n";
    } else {
        out << "LibTorch version: "
            << TORCH_VERSION_MAJOR << "."
            << TORCH_VERSION_MINOR << "."
            << TORCH_VERSION_PATCH << "\n";
        out << "Device: " << device_name << "\n";
        out << "Matmul sum: " << matmul_sum << "\n";
        out << "Result: " << (ok ? "PASSED" : "FAILED") << "\n";
        out.close();
    }

    return ok ? 0 : 1;
}
