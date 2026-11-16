"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

upload-to-hf: a folder or a file uploaded to a repository of the Hugging Face Hub (a dataset, a model) with the hf
CLI - the repository made when it does not exist, the files uploaded, the gating set - every command with the access
token of a cMeta secret in its environment alone (the variables of secret_env in _desc.yaml), through "cx secret
run", which asks for the password of a password-protected secret, on Windows in a console window of its own when
the caller has no terminal.
"""

import os
import re

from task_c36be4b9314a45e0.api.ctask import InitCTask

SECRET_CATEGORY = 'secret,9d63451ea1f14010'
VALUE_MARK = '{secret}'
SERVICE = 'huggingface'
TYPES = ('dataset', 'model', 'space')
GATED = ('auto', 'manual', 'no')


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,                  # cMeta context
            path: str = '',             # the folder or the file to upload
            repo: str = '',             # the repository: <owner>/<name> (ctuning/cTuning-MiDataSets)
            type: str = 'dataset',      # dataset, model or space
            path_in_repo: str = '',     # where in the repository (default: the root for a folder, the file's name for a file)
            secret: str = '',           # the secret that holds the access token (cx secret ls)
            message: str = '',          # the commit message (default: "upload <folder or file name>")
            include: str = '',          # glob patterns of the files to upload, comma-separated
            exclude: str = '',          # glob patterns of files to leave out, comma-separated
            delete: str = '',           # glob patterns of files of the repository to delete in the same commit
            create: bool = True,        # make the repository when it does not exist (--create=no: refuse instead)
            private: bool = False,      # a private repository (when made; also set when --gated is given)
            gated: str = '',            # auto, manual or no: the gating of the repository, set after the upload
            window: bool = False,       # on Windows: the password and the commands in a console window of their own
            dry_run: bool = False,      # the commands; nothing made or uploaded
    ):
        """
        Upload a folder or a file to a Hugging Face Hub repository, the access token from a cMeta secret:

            cxt upload-to-hf <folder> ctuning/<name>                          # the token secret with "service: huggingface"
            cxt upload-to-hf <folder> ctuning/<name> --secret=<alias> --gated=manual --message="first upload"
            cxt upload-to-hf <folder> ctuning/<name> --type=model --private
            cxt upload-to-hf <folder> ctuning/<name> --dry_run

        Three hf commands, each with the variables of secret_env (_desc.yaml) in its environment alone - HF_TOKEN
        gets the token: "hf repos create ... --exist-ok" (unless --create=no), "hf upload" (a folder goes up in
        several commits; the same command again resumes an interrupted upload) and, with --gated, "hf repos
        settings --gated". The token comes from the secret --secret names, else from the one token secret whose
        _desc.yaml declares "service: huggingface". A password-protected secret asks for its password at each
        command; on Windows, without a terminal (an AI agent) or with --window, in a console window that shows
        SUCCESS or FAILED until Enter.

        Returns:
            dict: return 0 with the repository, its URL and the commands, or return > 0 and the error.
        """
        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)

        what = os.path.abspath(os.path.expanduser(path or ''))
        if not path or not os.path.exists(what):
            return self.cm.error(f'name the folder or the file to upload (cxt upload-to-hf <folder or file> <owner>/<name>): "{path}" is not there')
        repo = (repo or '').strip()
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
            return self.cm.error(f'name the repository as <owner>/<name> (ctuning/cTuning-MiDataSets): "{repo}"')
        type = (type or 'dataset').strip().lower()
        if type not in TYPES:
            return self.cm.error(f'--type must be one of {", ".join(TYPES)}: "{type}"')
        gated = (gated or '').strip().lower()
        if gated and gated not in GATED:
            return self.cm.error(f'--gated must be one of {", ".join(GATED)}: "{gated}"')

        hf = (ctx['tasks']['global'].get('hf') or {}).get('path')
        if not hf:
            return self.cm.error('the hf CLI was not set up (cx tool setup hf)')

        # The variables hf gets, from _desc.yaml (the facts a user asks about live there)
        rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(self.module_path, '_desc'))
        secret_env = ((rd.get('data') or {}) if rd['return'] == 0 else {}).get('secret_env') or {}
        names = [k for k, v in secret_env.items() if VALUE_MARK in str(v)]
        if not names:
            return self.cm.error(f'secret_env of {self.module_path}/_desc.yaml names no variable for the token ({VALUE_MARK})')

        is_folder = os.path.isdir(what)
        where = path_in_repo.strip() if path_in_repo else ('.' if is_folder else os.path.basename(what))
        message = message.strip() if message else f'upload {os.path.basename(what.rstrip(os.sep)) or what}'
        includes = [x.strip() for x in (include or '').split(',') if x.strip()]
        excludes = [x.strip() for x in (exclude or '').split(',') if x.strip()]
        deletes = [x.strip() for x in (delete or '').split(',') if x.strip()]

        commands = []
        if create:
            commands.append(('create', [hf, 'repos', 'create', repo, '--type', type, '--exist-ok'] +
                             (['--private'] if private or gated in ('auto', 'manual') else ['--public'])))
        # A .gitattributes of the folder goes up first, alone: the Hub stores the files that follow as it says
        # (LFS for the binary kinds it names) instead of guessing from their first bytes - a guess the commit
        # of a binary file stored as text is rejected for
        if is_folder and os.path.isfile(os.path.join(what, '.gitattributes')) and where == '.':
            commands.append(('attributes', [hf, 'upload', repo, os.path.join(what, '.gitattributes'), '.gitattributes',
                                            '--type', type, '--commit-message', 'the attributes: which files are stored as LFS']))
        upload = [hf, 'upload', repo, what, where, '--type', type, '--commit-message', message]
        for x in includes:
            upload += ['--include', x]
        for x in excludes:
            upload += ['--exclude', x]
        for x in deletes:
            upload += ['--delete', x]
        commands.append(('upload', upload))
        if gated:
            # Made private, filled, then gated and public in one step: nothing is public in between
            commands.append(('settings', [hf, 'repos', 'settings', repo, '--type', type,
                                          '--gated', 'false' if gated == 'no' else gated] +
                                         ([] if private else ['--public'])))

        if not secret:
            rs = self._service_secret()
            if rs['return'] > 0 and not dry_run:
                return rs
            secret = rs.get('secret', '')
            if con:
                print('cMeta info: ' + (f'the secret {secret} (service: {SERVICE})' if secret else rs.get('error', '')))

        url = f'https://huggingface.co/{"" if type == "model" else type + "s/"}{repo}'
        if con:
            print('')
            print(f'cMeta info: {"the folder" if is_folder else "the file"} {what} -> {url} ({where})')

        if dry_run:
            if con:
                print(f'cMeta info: --dry_run - nothing made or uploaded; the commands (the token in {", ".join(names)}):')
                for step, cmd in commands:
                    print(f'  {step}: ' + ' '.join(self.cm.q(x) for x in cmd))
            return {'return': 0, 'repo': repo, 'url': url, 'secret': secret, 'commands': [c for _, c in commands], 'dry_run': True}

        for step, cmd in commands:
            if con:
                print('')
                print(f'cMeta info: {step} ...')
            # --window asks for the console window: a quiet run (-q, no selection asked) may still want it for the password
            r = self.cm.access({'category': SECRET_CATEGORY, 'command': 'run', 'arg1': secret, 'env': secret_env, 'cmd': cmd,
                                'window': window, 'con': con, 'quiet': False if window else quiet})
            if r['return'] > 0:
                r['error'] = f'{step} failed: {r.get("error")}'
                return r

        if con:
            print('')
            print(f'cMeta info: uploaded to {url}' + (f', gated: {gated}' if gated else ''))
        return {'return': 0, 'repo': repo, 'url': url, 'secret': secret, 'commands': [c for _, c in commands]}

    ############################################################
    def _service_secret(self):
        """
        The token secret for the Hub when --secret names none: the one whose _desc.yaml declares
        "service: huggingface". None or several: an error that says what to do.
        """
        r = self.cm.access({'category': SECRET_CATEGORY, 'command': 'find', 'arg1': '*', 'con': False})
        if r['return'] > 0 and r['return'] != 16:
            # 16: no secret artifact at all - the same answer as none for this service
            return r
        found = []
        for a in r.get('artifacts', []):
            rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(a['path'], '_desc'))
            d = (rd.get('data') or {}) if rd['return'] == 0 else {}
            if str(d.get('kind') or '') == 'token' and str(d.get('service') or '') == SERVICE:
                found.append(a['cmeta_ref_parts']['artifact_alias'])
        if len(found) == 1:
            return {'return': 0, 'secret': found[0]}
        if not found:
            return self.cm.error(f'name the secret that holds the access token: --secret=<alias> (cx secret ls), or declare '
                                 f'"service: {SERVICE}" in the _desc.yaml of one token secret')
        return self.cm.error(f'{len(found)} token secrets declare "service: {SERVICE}" ({", ".join(found)}): name one with --secret=<alias>')
