"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup lib-zlib": zlib as a static library (libz.a) built from its pinned source release with
the C compiler of cMeta, into the tool's cache entry (category/tool/api/common_static_lib.py). It is
what a distribution's static OpenSSL refers to when the system has no static zlib (tool/lib-openssl).
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_static_lib import install_static_lib, detect_static_lib

# The SHA-256 digests are those zlib.net publishes for the .tar.gz releases
SPEC = {
    'name': 'zlib',
    'lib': 'z',
    'default_version': '1.3.2',
    'url': ['https://github.com/madler/zlib/releases/download/v{version}/zlib-{version}.tar.gz',
            'https://zlib.net/fossils/zlib-{version}.tar.gz'],
    'sha256': {
        '1.3.2': 'bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16',
        '1.3.1': '9a93b2b7dfdac77ceba5a558a580e74667dd6fede4585b91eefb60f03b72df23',
    },
    'src_dir': 'zlib-{version}',
    'sources': ['adler32.c', 'compress.c', 'crc32.c', 'deflate.c', 'gzclose.c', 'gzlib.c', 'gzread.c',
                'gzwrite.c', 'infback.c', 'inffast.c', 'inflate.c', 'inftrees.c', 'trees.c', 'uncompr.c',
                'zutil.c'],
    # What zlib's configure sets on Linux and macOS (zconf.h: "#if HAVE_UNISTD_H-0")
    'defines': ['HAVE_UNISTD_H=1', 'HAVE_STDARG_H=1'],
    'headers': ['zlib.h', 'zconf.h'],
    'version': ('zlib.h', ['ZLIB_VERSION']),
    'windows': 'lib-zlib builds the static library on Linux and macOS; on Windows the static libraries '
               'of OpenSSL (tool/lib-openssl) do not need zlib',
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
        Build libz.a from the pinned source release (common_static_lib.py).
        """
        return install_static_lib(self, ctx, params, cmd, SPEC)

    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        The version (zlib.h), include and lib folders of the installed library.
        """
        return detect_static_lib(self, ctx, paths, params, SPEC)
