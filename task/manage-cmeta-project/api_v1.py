"""

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

from task_c36be4b9314a45e0.api.ctask import InitCTask


class CTask(InitCTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def project_path(self, value):
        """Resolve a deployment directory from an ordinary path or an artifact cRef."""
        if '::' not in value:
            return Path(os.path.expanduser(value)).resolve()
        reference, _, suffix = value.replace('\\', '/').partition('/')
        category, _, alias = reference.partition('::')
        parts = suffix.split('/') if suffix else []
        if any(p in ('', '.', '..') or ':' in p for p in parts):
            raise ValueError('Project-home cRef subpaths must not contain .. or absolute paths')
        result = self.cm.access(dict(category=category, command='find', arg1=alias, con=False))
        if result.get('return') or len(result.get('artifacts', [])) != 1:
            raise ValueError('Project-home cRef must resolve to exactly one existing artifact')
        base = Path(result['artifacts'][0]['path']).resolve()
        resolved = base.joinpath(*parts).resolve()
        try:
            resolved.relative_to(base)
        except ValueError:
            raise ValueError('Project-home subpath escapes its artifact')
        return resolved

    def run(self, ctx, action: str = 'info', project_home: str = '', definition: str = '', current: bool = False,
            current_env: bool = False, venv: bool = False, mode: str = 'native', params: dict = None, profile: dict = None,
            generate_scripts: bool = True, **options):
        """Run shared project automation in a child; never change the caller's home/interpreter."""
        try:
            if current and project_home:
                raise ValueError('Select --current or --project-home, not both')
            if not current and not project_home:
                raise ValueError('Specify --project-home, or --current to use the active cMeta home')
            root = Path(self.cm.home_path).resolve() if current else self.project_path(project_home)
            saved = root / 'project.yaml'
            data = copy.deepcopy(profile or {})
            if definition:
                category, separator, reference = definition.partition('::')
                if not separator:
                    category, reference = 'website', definition
                key = category.split(',')[0]
                if key not in ('website', 'task'):
                    raise ValueError('Definition must reference a website or task artifact')
                result = self.cm.access(dict(category=self.cmeta['uses_categories'][key], command='find',
                                             arg1=reference, con=False))
                if self.cm.catch_error(result, fail16=True):
                    return result
                if len(result['artifacts']) != 1:
                    raise ValueError('Select exactly one project definition')
                artifact = result['artifacts'][0]
                loaded = self.cm.utils.files.safe_read_yaml_or_json(str(Path(artifact['path']) / '_desc'))
                if self.cm.catch_error(loaded, fail16=True):
                    return loaded
                data = copy.deepcopy(loaded['data'].get('project') or {})
                if not data:
                    raise ValueError('Definition needs a project block in _desc.yaml')
                data['definition'] = definition
            if not current and saved.is_file():
                loaded = self.cm.utils.files.safe_read_file(str(saved))
                if self.cm.catch_error(loaded, fail16=True):
                    return loaded
                existing = loaded['data']
                if data and existing.get('task') != data.get('task'):
                    raise ValueError('This project already belongs to another task')
                data = existing  # Repeated bootstrap preserves local deployment choices.
            if not data:
                raise ValueError('Provide --definition=website::<name> or an existing project.yaml')
            request = dict(action=action, root=str(root), home=str(self.cm.home_path), profile=data, current=bool(current),
                           current_env=bool(current_env), venv=bool(venv), mode=mode,
                           params=params or {}, options=options, generate_scripts=bool(generate_scripts),
                           use=copy.deepcopy(ctx.get('tasks', {}).get('use') or {}),
                           categories=self.cmeta['uses_categories'], dependencies=self.cdesc['dependencies'])
            # Exact argv + stdin JSON avoids shell quoting and leaves credentials out of command lines.
            child = subprocess.Popen([sys.executable, '-u', str(Path(__file__).with_name('runtime.py'))],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=None, text=True, encoding='utf-8', errors='replace')
            child.stdin.write(json.dumps(request))
            child.stdin.close()
            result = None
            for line in child.stdout:
                if line.startswith('CMETA_PROJECT_RESULT='):
                    result = json.loads(line.partition('=')[2])
                else:
                    print(line, end='', flush=True)
            code = child.wait()
            return result or dict(return_code=code, **{'return': code or 1,
                'error': 'Project worker did not return a result; see output above'})
        except (OSError, ValueError) as exc:
            return self.cm.error(str(exc))
