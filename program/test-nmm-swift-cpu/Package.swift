// swift-tools-version: 5.9
/*
Copyright (C) 2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Developed with the help of ChatGPT and Claude.
*/

import PackageDescription

// CryptoKit is built-in on Apple platforms (macOS 10.15+, iOS 13+, …).
// On Linux, swift-crypto provides the same API under `import Crypto`.
#if os(Linux)
let cryptoDependencies: [Target.Dependency] = [
    .product(name: "Crypto", package: "swift-crypto"),
]
let packageDependencies: [Package.Dependency] = [
    .package(url: "https://github.com/apple/swift-crypto.git", from: "3.0.0"),
]
#else
let cryptoDependencies: [Target.Dependency] = []
let packageDependencies: [Package.Dependency] = []
#endif

let package = Package(
    name: "test-cpu-swift",
    platforms: [
        .macOS(.v10_15),
    ],
    dependencies: packageDependencies,
    targets: [
        .executableTarget(
            name: "test-cpu-swift",
            dependencies: cryptoDependencies,
            path: "src",
            // Exclude C++ sources so SPM only compiles the Swift file.
            exclude: [
                "matmul.cpp",
                "matmul.h",
                "program.cpp",
            ]
        ),
    ]
)
