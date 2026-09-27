"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Detect the Slurm client commands (sinfo, srun, sbatch, squeue, scontrol).

Every Slurm command reads the cluster configuration before doing anything, even
"sinfo --version": without a slurm.conf (or DNS SRV records pointing at a controller)
it only prints "fatal: Could not establish a configuration source". So the version is
taken from "sinfo --version" when the cluster is configured (a login node), and
otherwise from the package that installed the binary (dpkg or rpm) - the client is
found either way, and a task can check "global.slurm.configured" before submitting.
"""

import os
import re
import subprocess

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

VERSION = re.compile(r'slurm(?:-wlm)?\s+(\d+\.\d+(?:\.\d+)?)')


def _run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def detect_versions(self,
                        ctx: dict,
                        paths: dict,
                        params: dict = {},
    ):
        """
        The version of each found sinfo: from the cluster when it is configured, else from its package.
        """
        found = {}
        for xpath in paths:
            path = xpath[1:] if str(xpath).startswith('!') else xpath
            rc, out = _run([path, '--version'])
            m = VERSION.search(out) if rc == 0 else None
            configured = bool(m)
            version = m.group(1) if m else None
            source = 'sinfo --version'
            if not version:
                real = os.path.realpath(path)
                rc, out = _run(['dpkg-query', '-S', real])
                pkg = out.split(':', 1)[0].strip() if rc == 0 and ':' in out else ''
                if pkg:
                    rc, out = _run(['dpkg-query', '-W', '-f=${Version}', pkg])
                    version = re.match(r'(\d+\.\d+(?:\.\d+)?)', out.strip()).group(1) if rc == 0 and re.match(r'\d', out.strip()) else None
                    source = f'package {pkg} (dpkg)'
                if not version:
                    rc, out = _run(['rpm', '-qf', '--qf', '%{VERSION}', real])
                    version = out.strip() if rc == 0 and re.match(r'\d+\.\d+', out.strip()) else None
                    source = 'package (rpm)'
            if version:
                found[xpath] = {'output': f'slurm {version}',
                                'features': {'configured': configured, 'version_source': source}}
        return {'return': 0, 'found_paths_with_versions': found}
