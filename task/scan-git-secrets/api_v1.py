"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Scan a git history or a folder for secrets with gitleaks and report where they are, never the values.
"""

import collections
import json
import os
import subprocess
import tempfile

from task_c36be4b9314a45e0.api.ctask import InitCTask

# Fields of a gitleaks finding that are kept - "Secret", "Match" and "Email" never leave this task
KEEP = ['RuleID', 'Description', 'File', 'StartLine', 'EndLine', 'Commit', 'Date', 'Fingerprint', 'Entropy']


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            path: str = '',
            files: bool = False,
            report: str = '',
            baseline: str = '',
            config: str = '',
            no_fail: bool = False,
            install: bool = None,
    ):
        """
        Scan a repository's history (or, with "files", only its current files) or a folder for secrets.

        Args:
            path (str): Repository or folder to scan (default: the current folder).
            files (bool): Scan only the files as they are now, not the git history.
            report (str): Also write the findings (without any secret value) to this JSON file.
            baseline (str): A gitleaks JSON report of accepted findings to ignore.
            config (str): A gitleaks configuration (.toml) with extra rules or allow-lists.
            no_fail (bool): Return 0 even when secrets are found.

        Returns:
            dict: return (0 = clean or --no_fail), findings (list without values), by_rule (counts),
                  mode ("git history" or "files"), path.
        """
        con = ctx['control'].get('con', False)
        gitleaks = ctx['tasks']['global'].get('gitleaks', {}).get('path', '')
        if not gitleaks:
            return self.cm.error('the "gitleaks" tool was not set up (no path in the global context)', 1)

        path = os.path.abspath(os.path.expanduser(path or os.getcwd()))
        if not os.path.exists(path):
            return self.cm.error(f'nothing to scan at {path}', 1)
        history = (not files) and os.path.isdir(os.path.join(path, '.git'))
        mode = 'git history' if history else 'files'

        fd, tmp = tempfile.mkstemp(prefix='cmeta-gitleaks-', suffix='.json')
        os.close(fd)
        cmd = [gitleaks, 'git' if history else 'dir', path, '--redact', '--no-banner',
               '--report-format', 'json', '--report-path', tmp, '--exit-code', '0']
        # The baseline is matched here, by gitleaks' fingerprint (commit:file:rule:line), so that a report
        # of this task (which holds no values) works as a baseline - as well as a native gitleaks report
        accepted = set()
        if baseline:
            baseline = os.path.abspath(os.path.expanduser(baseline))
            try:
                with open(baseline, encoding='utf-8') as f:
                    b = json.load(f)
            except Exception as e:
                return self.cm.error(f'cannot read the baseline {baseline}: {e}', 1)
            items = b.get('findings', []) if isinstance(b, dict) else b if isinstance(b, list) else []
            accepted = {x.get('Fingerprint') for x in items if isinstance(x, dict) and x.get('Fingerprint')}
        if config:
            cmd += ['--config', os.path.abspath(os.path.expanduser(config))]
        if con:
            print('')
            print(f'INFO: scanning the {mode} of {path} with gitleaks (values are redacted)')

        # A list, no shell: paths with spaces or special characters need no quoting
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
            r = {'stdout': p.stdout, 'stderr': p.stderr}
        except OSError as e:
            r = {'stdout': '', 'stderr': str(e)}
        try:
            with open(tmp, encoding='utf-8') as f:
                raw = json.load(f) or []
        except Exception:
            raw = None
        finally:
            if os.path.isfile(tmp):
                os.remove(tmp)
        if raw is None:
            tail = ((r.get('stderr') or '') + (r.get('stdout') or '')).strip().splitlines()[-3:]
            return self.cm.error('gitleaks produced no report: ' + ' | '.join(tail), 1)

        findings = []
        skipped = 0
        for x in raw:
            if x.get('Fingerprint') in accepted:
                skipped += 1
                continue
            item = {k: x.get(k) for k in KEEP if k in x}
            if item.get('File'):
                try:
                    item['File'] = os.path.relpath(item['File'], path) if os.path.isabs(item['File']) else item['File']
                except ValueError:
                    pass
            if item.get('Commit'):
                item['Commit'] = item['Commit'][:12]
            findings.append(item)
        by_rule = dict(collections.Counter(f.get('RuleID', '?') for f in findings).most_common())

        if report:
            report = os.path.abspath(os.path.expanduser(report))
            rr = self.cm.utils.files.write_file(report, {'path': path, 'mode': mode, 'findings': findings, 'by_rule': by_rule},
                                                file_format='json', sort_keys=False)
            if self.cm.catch_error(rr): return rr

        if con:
            if skipped:
                print(f'INFO: {skipped} finding(s) accepted by the baseline {baseline}')
            if not findings:
                print(f'OK: no secrets found in the {mode} of {path}')
            else:
                print(f'FOUND: {len(findings)} possible secret(s) in the {mode} of {path}:')
                by_file = collections.defaultdict(list)
                for f in findings:
                    by_file[f.get('File', '?')].append(f)
                for name in sorted(by_file):
                    for f in sorted(by_file[name], key=lambda z: z.get('StartLine') or 0):
                        where = f'{name}:{f.get("StartLine", "?")}'
                        commit = f'  commit {f["Commit"]}' if f.get('Commit') else ''
                        print(f'  {where:60s} {f.get("RuleID", "?")}{commit}')
                print('By rule: ' + ', '.join(f'{k} {v}' for k, v in by_rule.items()))
                print('Values are never shown. To accept known findings, save a report and pass it as --baseline.')
            if report:
                print(f'Report (no values): {report}')

        result = {'return': 0, 'path': path, 'mode': mode, 'findings': findings, 'by_rule': by_rule,
                  'report': report or ''}
        if findings and not no_fail:
            result.update({'return': 1, 'error': f'{len(findings)} possible secret(s) found in the {mode} of {path}'})
        return result
