"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup lib-zstd": Zstandard as a static library (libzstd.a) built from its pinned source
release with the C compiler of cMeta, into the tool's cache entry
(category/tool/api/common_static_lib.py). It is what a distribution's static OpenSSL refers to when
the system has no static zstd (tool/lib-openssl).
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_static_lib import install_static_lib, detect_static_lib

# The SHA-256 digest is the one of the release's .sha256 file
SPEC = {
    'name': 'zstd',
    'lib': 'zstd',
    'default_version': '1.5.7',
    'url': 'https://github.com/facebook/zstd/releases/download/v{version}/zstd-{version}.tar.gz',
    'sha256': {
        '1.5.7': 'eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3',
    },
    'src_dir': 'zstd-{version}/lib',
    # The library's compression, decompression and dictionary builder (no legacy formats)
    'sources': ['common/*.c', 'compress/*.c', 'decompress/*.c', 'dictBuilder/*.c'],
    'include_dirs': ['.', 'common'],
    # As zstd's own lib/Makefile builds libzstd.a: its xxhash under the ZSTD_ prefix, single-threaded;
    # the C decoder instead of the x86-64 assembly one, so every system builds the same sources
    'defines': ['XXH_NAMESPACE=ZSTD_', 'ZSTD_LEGACY_SUPPORT=0', 'ZSTD_DISABLE_ASM', 'DEBUGLEVEL=0'],
    'cflags': ['-O3'],
    'headers': ['zstd.h', 'zstd_errors.h', 'zdict.h'],
    'version': ('zstd.h', ['ZSTD_VERSION_MAJOR', 'ZSTD_VERSION_MINOR', 'ZSTD_VERSION_RELEASE']),
    'windows': 'lib-zstd builds the static library on Linux and macOS; on Windows the static libraries '
               'of OpenSSL (tool/lib-openssl) do not need zstd',
}


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
                *misc: dict,
    ):
        """
        Build libzstd.a from the pinned source release (common_static_lib.py).
        """
        return install_static_lib(self, ctx, params, cmd, SPEC)

    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        The version (zstd.h), include and lib folders of the installed library.
        """
        return detect_static_lib(self, ctx, paths, params, SPEC)
