"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

"cx tool setup lib-jitterentropy": the Jitter RNG (jitterentropy-library) as a static library
(libjitterentropy.a) built from its pinned source release with the C compiler of cMeta, into the
tool's cache entry (category/tool/api/common_static_lib.py). OpenSSL 3.5 and newer can seed its
random generator from it, and the static OpenSSL of some distributions (Ubuntu 26.04) refers to it
(tool/lib-openssl).
"""

from tool_c393ba5c6fa14f66.api.ctool import InitCTool
from tool_c393ba5c6fa14f66.api.common_static_lib import install_static_lib, detect_static_lib

# The release is GitHub's archive of the tag (the project publishes no release files or digests)
SPEC = {
    'name': 'jitterentropy',
    'lib': 'jitterentropy',
    'default_version': '3.7.0',
    'url': 'https://github.com/smuellerDD/jitterentropy-library/archive/refs/tags/v{version}.tar.gz',
    'file': 'jitterentropy-library-{version}.tar.gz',
    'sha256': {
        '3.7.0': 'f5eaccc9d2977c83308651be9379f09f34348398f419e8f8b5bbd95928c777ed',
    },
    'src_dir': 'jitterentropy-library-{version}',
    'sources': ['src/*.c'],
    'include_dirs': ['.', 'src'],
    # As the project's Makefile builds it: with its internal timer (it needs pthreads) and without
    # optimization, which jitterentropy-base.c requires (the noise source depends on it)
    'defines': ['JENT_CONF_ENABLE_INTERNAL_TIMER'],
    'cflags': ['-O0', '-fwrapv', '-std=c11'],
    'headers': ['jitterentropy.h', 'jitterentropy-base-user.h'],
    'version': ('jitterentropy.h', ['JENT_MAJVERSION', 'JENT_MINVERSION', 'JENT_PATCHLEVEL']),
    'windows': 'lib-jitterentropy builds the static library on Linux and macOS; on Windows the static '
               'libraries of OpenSSL (tool/lib-openssl) do not need it',
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
        Build libjitterentropy.a from the pinned source release (common_static_lib.py).
        """
        return install_static_lib(self, ctx, params, cmd, SPEC)

    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        The version (jitterentropy.h), include and lib folders of the installed library.
        """
        return detect_static_lib(self, ctx, paths, params, SPEC)
