"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

# Rust's target for each Android ABI (ro.product.cpu.abi)
RUST_TARGETS = {
    'arm64-v8a': 'aarch64-linux-android',
    'armeabi-v7a': 'armv7-linux-androideabi',
    'x86_64': 'x86_64-linux-android',
    'x86': 'i686-linux-android',
}


def target_flags(rust_target, linker, clang_target, quote):
    """rustc's flags for an Android target: its standard library, and the NDK's clang (a path,
    quoted by quote()) linking for the clang target of the device's API level."""
    return f'--target {rust_target} -C linker={quote(linker)} -C link-arg=--target={clang_target}'


def target_installed(sysroot, rust_target):
    """Whether the toolchain at sysroot has the standard library of rust_target."""
    return os.path.isdir(os.path.join(sysroot, 'lib', 'rustlib', rust_target, 'lib'))


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        The target of the Android device that target--android-cpu selected (also for a cached
        result, so another device gets its own ABI and API level): rustc's --target, the
        standard library of that target, and the NDK's clang as the linker.
        """

        _global = ctx['tasks']['global']

        target_android = _global.get('target--android-cpu')
        if not target_android:
            return {'return': 0}

        abi = target_android['features']['ro.product.cpu.abi']

        rust_target = RUST_TARGETS.get(abi)
        if not rust_target:
            return self.cm.error(f'no Rust target for the Android ABI "{abi}"')

        clang = _global.get('android-ndk-clang', {})
        clang_arch = clang.get('features', {}).get('target_arch', {})
        clang_target = clang_arch.get('clang_target')
        if not clang_target or not clang.get('path'):
            return self.cm.error('the Android NDK\'s clang has no target for the device: '
                                 'tool "rustc-android" links with it')

        r = self.add_target(ctx, result['path'], rust_target)
        if self.cm.catch_error(r): return r

        features = result.setdefault('features', {})
        features['target_arch'] = {
          'abi': abi,
          'rust_target': rust_target,
          'clang_target': clang_target,
          'api_level': clang_arch.get('api_level'),
          'sysroot': r['sysroot'],
          'flags': target_flags(rust_target, clang['path'], clang_target, self.cm.q),
        }

        return {'return': 0}

    ############################################################
    def add_target(self,
                   ctx: dict,
                   rustc: str,
                   rust_target: str,
    ):
        """
        Adds the standard library of rust_target to the toolchain of rustc with rustup when it is
        missing. The commands run in the environment that tool/rustup and tool/rustc set up
        (RUSTUP_HOME, CARGO_HOME), like the compile command.
        """

        con = ctx['control'].get('con', False)

        _global = ctx['tasks']['global']
        envs = ctx['tasks']['aggregated'].get('env', {})
        os_env = _global['host']['os_env']

        r = self.cm.utils.sys.run(f'{self.cm.q(rustc)} --print sysroot', envs = envs, os_env = os_env,
                                  capture_output = True)
        if self.cm.catch_error(r): return r

        sysroot = (r.get('stdout') or '').strip()
        if r.get('returncode') != 0 or not sysroot:
            return self.cm.error(f'"rustc --print sysroot" failed: {(r.get("stderr") or "").strip()[-300:]}')

        if not target_installed(sysroot, rust_target):
            rustup = _global.get('rustup', {}).get('path')
            if not rustup:
                return self.cm.error(f'the Rust standard library for "{rust_target}" is missing and rustup '
                                     'is not set up to add it')

            toolchain = os.path.basename(sysroot)
            if con:
                print('')
                print(f'INFO: adding the Rust standard library for {rust_target} to the toolchain '
                      f'{toolchain} (rustup target add)')

            r = self.cm.utils.sys.run(f'{self.cm.q(rustup)} target add {rust_target} --toolchain {toolchain}',
                                      envs = envs, os_env = os_env, capture_output = True)
            if self.cm.catch_error(r): return r

            if r.get('returncode') != 0 or not target_installed(sysroot, rust_target):
                return self.cm.error(f'"rustup target add {rust_target}" failed: '
                                     f'{(r.get("stderr") or "").strip()[-300:]}')

        return {'return': 0, 'sysroot': sysroot}
