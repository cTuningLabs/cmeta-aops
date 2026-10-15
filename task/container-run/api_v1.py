"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.

task/container-run: run one container with docker or podman.

Ports, volumes, environment, run flags and the command arrive resolved from the "container" category. Run-time
secrets go through a temporary --env-file (0600, deleted right after the engine returns - for a detached
container that is right after the start), so they are never on the command line or in the saved script.
"""

import os
import shutil
import stat
import tempfile

from task_c36be4b9314a45e0.api.ctask import InitCTask

TASK_CMD = 'cmd,c9ba0a88df394d7f'


class CTask(InitCTask):
    """Run a container."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            engine: str = 'docker',        # docker | podman
            image: str = '',               # image to run
            name: str = '',                # --name
            detach: bool = False,          # -d
            rm: bool = True,               # --rm
            interactive: bool = False,     # -it (needs a real terminal)
            ports: list = None,            # ["127.0.0.1:8004:8004", ...]
            volumes: list = None,          # ["<host path>:<container path>[:ro]", ...]
            env: dict = None,              # {K: V} -> -e K=V
            env_secrets: dict = None,      # {K: V} -> temporary --env-file
            run_flags: list = None,        # extra flags (--gpus all, --ipc=host, ...)
            cmd: list = None,              # command inside the container (list)
            workdir: str = '',             # -w
            user: str = '',                # --user
            labels: dict = None,           # --label key=value
            capture_output: bool = False,  # capture stdout/stderr instead of streaming them
            timeout: int = None,
            unparsed: list = None,         # everything after "--" on the command line = the command
    ):
        """
        Run one container.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **returncode** (int): Exit code of the engine (= of the container when not detached).
                - **stdout** (str), **stderr** (str): Captured output when capture_output is True.
                - **container_id** (str): The id printed by the engine when detached.
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

        _global = ctx['tasks']['global']
        ports = ports or []
        volumes = volumes or []
        env = env or {}
        env_secrets = env_secrets or {}
        run_flags = run_flags or []
        labels = labels or {}
        cmd = [str(x) for x in (unparsed or cmd or [])]

        if engine not in ('docker', 'podman'):
            return {'return': 1, 'error': f'engine must be docker or podman, got "{engine}"'}
        if not image:
            return {'return': 1, 'error': 'image is required'}

        tool = _global.get(engine) or {}
        qengine = tool.get('qpath') or engine

        def q(s):
            """Quote one command-line argument for the host shell (cmd.exe and sh): inner double quotes are escaped."""
            s = str(s)
            if s and not any(ch in s for ch in ' \t"\'&|<>()^;$`*?'):
                return s
            return '"' + s.replace('"', '\\"') + '"'

        parts = [qengine, 'run']
        if rm:
            parts.append('--rm')
        if detach:
            parts.append('-d')
        if interactive:
            parts.append('-it')
        if name:
            parts += ['--name', name]
        for k, v in labels.items():
            parts.append(f'--label {q(f"{k}={v}")}')
        for p in ports:
            parts += ['-p', str(p)]
        for v in volumes:
            parts += ['-v', q(str(v))]
        for k, v in env.items():
            parts += ['-e', q(f'{k}={v}')]
        env_file = None
        if env_secrets:
            fd, env_file = tempfile.mkstemp(prefix='cmeta-container-', suffix='.env')
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
                for k, v in env_secrets.items():
                    f.write(f'{k}={v}\n')
            try:
                os.chmod(env_file, stat.S_IRUSR | stat.S_IWUSR)
            except Exception:
                pass
            parts += ['--env-file', q(env_file)]
        if workdir:
            parts += ['-w', q(workdir)]
        if user:
            parts += ['--user', user]
        parts += [str(x) for x in run_flags]
        parts.append(image)
        parts += [q(x) for x in cmd]
        command = ' '.join(parts)

        if con and verbose:
            print(f'{space}INFO: {engine} run {image}' + (f' as {name}' if name else ''))

        try:
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': TASK_CMD, 'ctx': ctx,
                                'cmd': command, 'timeout': timeout, 'con': con, 'verbose': verbose,
                                'text_cmd': 'RUN:', 'fail_if_nonzero_return_code': False,
                                'capture_output': bool(capture_output)})
        finally:
            if env_file:
                try:
                    os.remove(env_file)
                except Exception:
                    pass
        if self.cm.catch_error(r):
            return r

        rc = r.get('returncode', 0)
        out = {'return': 0, 'returncode': rc, 'stdout': r.get('stdout', ''), 'stderr': r.get('stderr', ''),
               'image': image, 'engine': engine}
        if detach:
            out['container_id'] = (r.get('stdout') or '').strip().splitlines()[-1] if (r.get('stdout') or '').strip() else ''
            if rc != 0:
                return {'return': 1, 'error': f'{engine} run failed with code {rc}: {(r.get("stderr") or "").strip()[:400]}'}
        return out
