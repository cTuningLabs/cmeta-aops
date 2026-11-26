"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/hipcc: the hipcc of the ROCm selected before it (tool rocm, the first of its uses:), as clang-cpp takes the clang++
beside the clang selected - so several ROCm side by side (cx tool setup rocm --install --version=<v>, AMD's Python
distribution in the cache) each compile with their own hipcc. Seen on an MI300X (2026-11-26): a program run with
--use.rocm.version=10.1.0 compiled with the system ROCm 10.2's hipcc (HIP 7.17) - the first hipcc on the PATH, and a
cache entry of hipcc that did not depend on the ROCm.
"""

import glob
import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

NAME = 'hipcc'


def link_chain(path, limit = 16):
    """A path and every path its symbolic links lead to, one link at a time (/usr/bin/rocm-smi ->
    /etc/alternatives/rocm-smi -> /opt/rocm/core-10.2/bin/rocm-smi -> ...), the given path first."""
    chain = [path]
    while os.path.islink(path) and len(chain) <= limit:
        target = os.readlink(path)
        path = target if os.path.isabs(target) else os.path.normpath(os.path.join(os.path.dirname(path), target))
        chain.append(path)
    return chain


def hipcc_of_rocm(rocm_path, rocm_bin = '', name = NAME):
    """
    The hipcc of one ROCm installation, or '': the hipcc in the folder its features name (paths.bin: the venv's bin of
    an SDK of AMD's Python distribution, AMD's /opt/rocm/bin), else beside the tool rocm found or beside a path its
    links lead to (a system ROCm found as /usr/bin/rocm-smi lives in /opt/rocm/core-<version>/bin).
    """
    folders = [rocm_bin] if rocm_bin else []
    if rocm_path:
        folders += [os.path.dirname(p) for p in link_chain(rocm_path)]
    for folder in folders:
        candidate = os.path.join(folder, name)
        if folder and os.path.isfile(candidate):
            return candidate
    return ''


def searched(paths, extra_globs, name = NAME):
    """The hipcc found the way a tool is searched without a hook, in that order: the PATH's folders, then the
    declared folders (globs) - each existing file once."""
    found = []
    for folder in list(paths or []) + [g for pattern in (extra_globs or []) for g in sorted(glob.glob(pattern))]:
        candidate = os.path.join(folder, name)
        if folder and os.path.isfile(candidate) and candidate not in found:
            found.append(candidate)
    return found


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def find_paths(self,
                   ctx: dict,
                   params: dict = {},
    ):
        """
        The hipcc of the ROCm selected before it (deterministic: the ROCm decides); only when that ROCm has none
        beside it, the search of before - the PATH, then the folders of extra_paths in _desc.yaml.
        """
        rocm = ctx['tasks']['global'].get('rocm') or {}
        rocm_path = str(rocm.get('path') or '').strip('"')
        rocm_bin = str(((rocm.get('features') or {}).get('paths') or {}).get('bin') or '').strip('"')

        own = hipcc_of_rocm(rocm_path, rocm_bin)
        if own:
            return {'return': 0, 'found_paths': [own]}

        extra = (self.cdesc.get('extra_paths') or {}).get('linux') or []
        globs = [p for p in extra if '{{' not in str(p)]
        return {'return': 0, 'found_paths': searched(os.environ.get('PATH', '').split(os.pathsep), globs)}
