"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

upload-to-pypi: the wheel and the sdist of a dist folder checked with "twine check" and uploaded with "twine upload
--non-interactive", the API token of a cMeta secret in the environment of twine alone (the variables of secret_env
in _desc.yaml), through "cx secret run" - which asks for the password of a password-protected secret, on Windows in a
console window of its own when the caller has no terminal.
"""

import glob
import os
import subprocess

from task_c36be4b9314a45e0.api.ctask import InitCTask

SECRET_CATEGORY = 'secret,9d63451ea1f14010'
VALUE_MARK = '{secret}'


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,                 # cMeta context
            dist: str = 'dist',        # the folder with the wheel and the sdist
            secret: str = '',          # the secret that holds the API token (cx secret ls)
            repository: str = 'pypi',  # pypi, testpypi or the URL of another index
            check: bool = True,        # twine check before the upload
            window: bool = False,      # on Windows: the password and the upload in a console window of their own
            dry_run: bool = False,     # twine check and the command; nothing uploaded
    ):
        """
        Upload the wheel and the sdist of a dist folder to PyPI with twine, the API token from a cMeta secret:

            cxt upload-to-pypi <dist folder>                          # the token secret with "service: pypi"
            cxt upload-to-pypi <dist folder> --secret=<alias>
            cxt upload-to-pypi <dist folder> --repository=testpypi    # the one with "service: testpypi"
            cxt upload-to-pypi <dist folder> --dry_run

        "twine check" first (--check=no skips it); then "twine upload --non-interactive" with the variables of
        secret_env (_desc.yaml) in its environment alone - TWINE_PASSWORD gets the token. The token comes from the
        secret --secret names, else from the one token secret whose _desc.yaml declares "service: <repository>"
        (a URL repository needs --secret). A password-protected secret asks for its password; on Windows, without a
        terminal (an AI agent) or with --window, in a console window that shows SUCCESS or FAILED until Enter.

        Returns:
            dict: return 0 with the files and the repository, or return > 0 and the error (nothing uploaded when
                  the check fails).
        """
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)

        folder = os.path.abspath(os.path.expanduser(dist or 'dist'))
        if not os.path.isdir(folder):
            return self.cm.error(f'there is no folder {folder}: name the dist folder (cxt upload-to-pypi <folder>)')
        files = sorted(glob.glob(os.path.join(folder, '*.whl')) + glob.glob(os.path.join(folder, '*.tar.gz')))
        if not files:
            return self.cm.error(f'no wheel (.whl) or sdist (.tar.gz) in {folder}')

        twine = (ctx['tasks']['global'].get('twine') or {}).get('path')
        if not twine:
            return self.cm.error('twine was not set up (cx tool setup twine)')

        if con:
            print('')
            print(f'cMeta info: {len(files)} file(s) in {folder}:')
            for f in files:
                print(f'  {os.path.basename(f)}  ({os.path.getsize(f):,} bytes)')

        if check:
            p = subprocess.run([twine, 'check'] + files, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            decode = getattr(self.cm.utils.sys, 'decode_output', None) or (lambda b: b.decode('utf-8', 'replace'))
            if con:
                print(decode(p.stdout).rstrip())
            if p.returncode != 0:
                return self.cm.error('twine check failed: nothing was uploaded')

        # The variables twine gets, from _desc.yaml (the facts a user asks about live there)
        rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(self.module_path, '_desc'))
        secret_env = ((rd.get('data') or {}) if rd['return'] == 0 else {}).get('secret_env') or {}
        names = [k for k, v in secret_env.items() if VALUE_MARK in str(v)]
        if not names:
            return self.cm.error(f'secret_env of {self.module_path}/_desc.yaml names no variable for the token ({VALUE_MARK})')

        repo = (repository or 'pypi').strip()
        where = ['--repository-url', repo] if repo.startswith(('http://', 'https://')) else ([] if repo == 'pypi' else ['--repository', repo])
        cmd = [twine, 'upload', '--non-interactive', '--verbose'] + where + files

        if not secret:
            rs = self._service_secret(repo)
            if rs['return'] > 0 and not dry_run:
                return rs
            secret = rs.get('secret', '')
            if con:
                print(f'cMeta info: ' + (f'the secret {secret} (service: {repo})' if secret else rs.get('error', '')))

        if dry_run:
            if con:
                print(f'cMeta info: --dry_run - nothing uploaded; the command (the token in {", ".join(names)}):')
                print('  ' + ' '.join(cmd))
            return {'return': 0, 'files': files, 'repository': repo, 'secret': secret, 'cmd': cmd, 'dry_run': True}

        r = self.cm.access({'category': SECRET_CATEGORY, 'command': 'run', 'arg1': secret, 'env': secret_env, 'cmd': cmd,
                            'window': window, 'con': con, 'quiet': quiet})
        if r['return'] > 0:
            return r

        if con:
            print(f'cMeta info: {len(files)} file(s) uploaded to {repo}')
        return {'return': 0, 'files': files, 'repository': repo, 'secret': secret}

    ############################################################
    def _service_secret(self, repo):
        """
        The token secret for this repository when --secret names none: the one whose _desc.yaml declares
        "service: <repository>" (service: pypi, service: testpypi). None or several: an error that says what to do.
        """
        r = self.cm.access({'category': SECRET_CATEGORY, 'command': 'find', 'arg1': '*', 'con': False})
        if r['return'] > 0 and r['return'] != 16:
            # 16: no secret artifact at all - the same answer as none for this service
            return r
        found = []
        for a in r.get('artifacts', []):
            rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(a['path'], '_desc'))
            d = (rd.get('data') or {}) if rd['return'] == 0 else {}
            if str(d.get('kind') or '') == 'token' and str(d.get('service') or '') == repo:
                found.append(a['cmeta_ref_parts']['artifact_alias'])
        if len(found) == 1:
            return {'return': 0, 'secret': found[0]}
        if not found:
            return self.cm.error(f'name the secret that holds the API token: --secret=<alias> (cx secret ls), or declare '
                                 f'"service: {repo}" in the _desc.yaml of one token secret')
        return self.cm.error(f'{len(found)} token secrets declare "service: {repo}" ({", ".join(found)}): name one with --secret=<alias>')
