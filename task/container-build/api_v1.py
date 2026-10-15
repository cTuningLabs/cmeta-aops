"""
Licensed under the Apache License, Version 2.0.
Authors: Grigori Fursin. See LICENSE in the project root for details.

task/container-build: build one image with docker or podman from a rendered build context.

The task runs inside its cache entry (the task engine chdir's there): the rendered files land in context/,
secrets in secrets/ (0600, deleted after the build), the exact build command in build-container.<sh|bat>
(save_script of the cmd task, secret values are never on the command line) and the result in record.json.
"""

import datetime
import json
import os
import shutil
import stat

from task_c36be4b9314a45e0.api.ctask import InitCTask

TASK_CMD = 'cmd,c9ba0a88df394d7f'


class CTask(InitCTask):
    """Build a container image from rendered files."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            engine: str = 'docker',        # docker | podman
            image: str = '',               # tag of the image to build
            params_hash: str = '',         # identity of the rendered inputs (recorded)
            files: dict = None,            # {name: content} written into the build context (LF line endings)
            copy: list = None,             # [{'src': host path, 'dst': name in the context}] copied as they are
            build_args: list = None,       # extra flags for "<engine> build" (--pull, --build-arg K=V, ...)
            secrets: dict = None,          # {NAME: value} -> --secret id=NAME,src=<temp file>; deleted after the build
            platform: str = '',            # --platform linux/amd64 | linux/arm64
            no_cache: bool = False,        # --no-cache
            labels: dict = None,           # {key: value} -> --label key=value
            timeout: int = None,
    ):
        """
        Build one container image.

        Args:
            ctx (dict): The cMeta context.
            engine (str): docker or podman.
            image (str): Image tag.
            params_hash (str): Identity of the rendered inputs, recorded next to the image id.
            files (dict): Rendered files for the build context ({name: content}).
            copy (list): Files to copy into the context ([{'src': path, 'dst': name}]).
            build_args (list): Extra flags for the build command.
            secrets (dict): Build secrets ({NAME: value}) exposed as secret mounts only.
            platform (str): Target platform.
            no_cache (bool): Build without the layer cache.
            labels (dict): Image labels.
            timeout (int): Timeout of the build in seconds.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **image** (str): The tag.
                - **image_id** (str): The image id reported by the engine.
                - **context_path** (str): The build context that was used.
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks'].get('nested_call', 0) if verbose else ''

        _global = ctx['tasks']['global']
        files = files or {}
        copy = copy or []
        build_args = build_args or []
        secrets = secrets or {}
        labels = labels or {}

        if engine not in ('docker', 'podman'):
            return {'return': 1, 'error': f'engine must be docker or podman, got "{engine}"'}
        if not image:
            return {'return': 1, 'error': 'image (tag) is required'}
        if 'Containerfile' not in files and not any(c.get('dst') == 'Containerfile' for c in copy):
            return {'return': 1, 'error': 'files must contain a Containerfile'}

        tool = _global.get(engine) or {}
        qengine = tool.get('qpath') or engine
        ext = _global['host']['vars'].get('file_ext_bat', '.sh')

        work = os.getcwd()
        context = os.path.join(work, 'context')
        if os.path.isdir(context):
            shutil.rmtree(context, ignore_errors=True)
        os.makedirs(context, exist_ok=True)
        for name, content in files.items():
            p = os.path.join(context, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w', encoding='utf-8', newline='\n') as f:
                f.write(str(content).replace('\r\n', '\n'))
        for c in copy:
            src, dst = c.get('src'), c.get('dst')
            if not src or not dst:
                continue
            p = os.path.join(context, dst)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            if os.path.isdir(src):
                shutil.copytree(src, p, dirs_exist_ok=True)
            else:
                shutil.copy2(src, p)

        secrets_dir = os.path.join(work, 'secrets')
        if os.path.isdir(secrets_dir):
            shutil.rmtree(secrets_dir, ignore_errors=True)
        secret_flags = []
        if secrets:
            os.makedirs(secrets_dir, exist_ok=True)
            for name, value in secrets.items():
                p = os.path.join(secrets_dir, name)
                with open(p, 'w', encoding='utf-8', newline='\n') as f:
                    f.write(str(value))
                try:
                    os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
                except Exception:
                    pass
                secret_flags += [f'--secret id={name},src={self.cm.q(p)}']

        parts = [qengine, 'build', '--file', self.cm.q(os.path.join(context, 'Containerfile')), '--tag', image]
        for k, v in labels.items():
            parts.append(f'--label {self.cm.q(f"{k}={v}")}')
        parts += [str(x) for x in build_args]
        parts += secret_flags
        if platform:
            parts += ['--platform', platform]
        if no_cache:
            parts.append('--no-cache')
        parts.append(self.cm.q(context))
        cmd = ' '.join(parts)

        env = {'DOCKER_BUILDKIT': '1'} if engine == 'docker' else {}

        if con:
            print('')
            print(f'{space}INFO: building {image} with {engine} (context: {context})')

        try:
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': TASK_CMD, 'ctx': ctx,
                                'cmd': cmd, 'env': env, 'timeout': timeout, 'con': con, 'verbose': verbose,
                                'text_cmd': 'RUN:', 'fail_if_nonzero_return_code': False, 'capture_output': False,
                                'save_script': os.path.join(work, 'build-container' + ext)})
        finally:
            shutil.rmtree(secrets_dir, ignore_errors=True)
        if self.cm.catch_error(r):
            return r
        rc = r.get('returncode', 1)
        if rc != 0:
            return {'return': 1, 'error': f'{engine} build failed with code {rc} for {image} - see the engine output above '
                                          f'(the rendered context is kept in {context})'}

        rr = self.cm.utils.sys.run(f'{qengine} image inspect {image} --format "{{{{.Id}}}}"', capture_output=True)
        image_id = (rr.get('stdout') or '').strip() if rr.get('return', 1) == 0 else ''

        record = {'image': image, 'image_id': image_id, 'engine': engine, 'engine_path': tool.get('path', ''),
                  'engine_version': tool.get('version', ''), 'params_hash': params_hash, 'platform': platform,
                  'labels': labels, 'built': datetime.datetime.now().isoformat(timespec='seconds'),
                  'context': context, 'files': sorted(files.keys()) + [c.get('dst') for c in copy if c.get('dst')]}
        with open(os.path.join(work, 'record.json'), 'w', encoding='utf-8') as f:
            json.dump(record, f, indent=2)

        if con:
            print('')
            print(f'{space}INFO: built {image}' + (f' ({image_id[:19]})' if image_id else ''))

        return {'return': 0, 'image': image, 'image_id': image_id, 'context_path': context, 'record': record}
