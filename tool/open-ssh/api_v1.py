"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

open-ssh: the OpenSSH client found on the host (see _desc.yaml for which one, and why that matters). Its sibling
programs - ssh-keygen, ssh-keyscan, ssh-add, ssh-agent, scp, sftp - are reported as features (features.paths) from
the folder of the ssh that was found: the same build, so a task takes "ssh-keygen" from here instead of looking for
it by name or by a fixed path (2026-11-22, make-slurm-cluster's cluster key).
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool


# the programs of an OpenSSH client next to ssh; on Windows each with .exe
SIBLINGS = ('ssh-keygen', 'ssh-keyscan', 'ssh-add', 'ssh-agent', 'scp', 'sftp')


class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def check_features(self,
                       ctx: dict,
                       paths: list,
                       params: dict,
    ):
        """
        The folder of each ssh found, and the sibling programs present in it (features.paths.<name>); a program
        that is not there is not reported (some builds ship without ssh-agent or sftp).
        """
        ext = '.exe' if ctx['tasks']['global']['host']['os']['uname'] == 'windows' else ''
        for p in paths:
            folder = os.path.dirname(p['path'])
            found = p.setdefault('features', {}).setdefault('paths', {})
            found['bin'] = folder
            for name in SIBLINGS:
                candidate = os.path.join(folder, name + ext)
                if os.path.isfile(candidate):
                    found[name] = candidate
        return {'return': 0, 'paths': paths}
