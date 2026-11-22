"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The published MLPerf Endpoints results, cloned into the cache:

  - a fixed round (0.7): its own repository mlcommons/endpoints_results_v<round>, as before;
  - the rolling rounds (1.0 and later): one repository, mlcommons/endpoints_results, where each cohort of results (two a
    month, named <year>-<month>-C<n>) is a branch of its own - --cohort=<name> clones that one, --cohort=all every
    cohort (one cache entry each), and without --cohort the newest cohort by its name.
"""

import re
import subprocess

from task_c36be4b9314a45e0.api.ctask import InitCTask

# The round taken when --version names none: the newest published (rolling since 2026-10)
DEFAULT_ROUND = '1.0'

# Rounds before the rolling submissions: one repository each
FIXED_ROUNDS = ('0.5', '0.7')

ROLLING_URL = 'https://github.com/mlcommons/endpoints_results'

# A cohort branch: <year>-<month>-C<n> (2026-11-C0, 2026-11-C1)
COHORT = re.compile(r'^(\d{4})-(\d{2})-C(\d+)$')


def cohort_key(name):
    """(year, month, n) of a cohort name - the order MLCommons publishes them in."""
    m = COHORT.match(name)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def _cohorts(self, ctx, url, con, quiet, verbose):
        """The cohort branches of the rolling repository (git ls-remote with cMeta's git), oldest first."""
        r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                            'ctx': ctx, 'name': 'git,959d8c0fbc004bd0', 'con': con, 'quiet': quiet, 'verbose': verbose})
        if self.cm.catch_error(r, fail16 = True): return r
        git = r.get('path') or 'git'
        p = subprocess.run([git, 'ls-remote', '--heads', url], stdin = subprocess.DEVNULL, stdout = subprocess.PIPE,
                           stderr = subprocess.PIPE)
        if p.returncode != 0:
            return self.cm.error(f'could not list the branches of {url}: {p.stderr.decode("utf-8", "replace").strip()}')
        names = []
        for line in p.stdout.decode('utf-8', 'replace').splitlines():
            ref = line.split('\t')[-1].strip()
            if ref.startswith('refs/heads/'):
                name = ref[len('refs/heads/'):]
                if COHORT.match(name):
                    names.append(name)
        return {'return': 0, 'cohorts': sorted(names, key = cohort_key)}

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict,
                     cparams: dict,
    ):
        """
        """

        c = ctx.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)

        version = str(params.get('version') or DEFAULT_ROUND)
        _local = ctx['tasks']['local']

        extra_tags = params.get('extra_tags')
        if not extra_tags:
            params['extra_tags'] = 'mlcommons'

        if version in FIXED_ROUNDS:
            # As before 2026-11-21: the round's own repository, its default branch (or --checkout)
            if params.get('cohort'):
                return self.cm.error(f'round {version} has no cohorts (--cohort is for the rolling rounds, 1.0 and later)')
            url = params.get('url') or f'https://github.com/mlcommons/endpoints_results_v{version}'
            _local['url'] = url
            _local['version'] = version
            _local['name'] = f'mlperf-endpoints-results-{version}'
            _local['checkout'] = params.get('checkout')
            return {'return': 0}

        # A rolling round: the cohort branches of one repository
        url = params.get('url') or ROLLING_URL
        cohort = str(params.get('cohort') or params.get('checkout') or '').strip()

        r = self._cohorts(ctx, url, con, quiet, verbose)
        if r['return'] > 0: return r
        available = r['cohorts']

        # The nested setup of git ran with this ctx: the task's local context is taken again after it
        _local = ctx['tasks']['local']

        if cohort.lower() == 'all':
            if not available:
                return self.cm.error(f'no cohort branch (<year>-<month>-C<n>) in {url}')
            wanted = available
        elif cohort:
            if cohort not in available and COHORT.match(cohort):
                return self.cm.error(f'no cohort "{cohort}" in {url} (cohorts: {", ".join(available) or "none"})')
            wanted = [cohort]
        else:
            if not available:
                return self.cm.error(f'no cohort branch (<year>-<month>-C<n>) in {url}: name a branch with --cohort')
            wanted = [available[-1]]
            if con:
                print(f'INFO: the newest cohort of {url} by its name: {wanted[0]} (cohorts: {", ".join(available)}; '
                      f'--cohort=<name> or --cohort=all for others)')

        _local['url'] = url
        _local['version'] = version
        _local['cohorts_available'] = available
        _local['cohorts_wanted'] = wanted
        _local['cohort'] = wanted[-1]
        # The name in lower case: the engine makes the alias of a cache entry and the key of its stored result from
        # it in lower case (2026-11-C1 -> ...-2026-11-c1)
        _local['name'] = f'mlperf-endpoints-results-{version}-{wanted[-1]}'.lower()
        _local['checkout'] = wanted[-1]

        return {'return': 0}

    ############################################################
    def _result(self, result_from_git, version):
        path = result_from_git['path_to_git_repo']
        result = {'return': 0, 'path': path, 'qpath': self.cm.q(path), 'result_from_git': result_from_git,
                  'version': version}
        for k in ['checkout', 'checkout_short', 'url']:
            if k in result_from_git:
                result[k] = result_from_git[k]
        return result

    ############################################################
    def run(self,
            ctx,
            **params,
    ):
        """
        Clone (or reuse) the published MLPerf Endpoints results.

        Args:
          version (str): the round - 1.0 (default; the rolling results, by cohort) or 0.7 (a fixed round)
          cohort (str): a cohort of a rolling round (2026-11-C1), "all", or none for the newest by its name
          checkout (str): a branch, tag or commit (a fixed round), or the cohort (a rolling round)
          url (str): another repository (a fork)
          root_dir (str): the folder of the clone inside the cache entry
          extra_tags (str): extra tags of the cache entry (default mlcommons)

        Returns:
          path, qpath, version, url, checkout, checkout_short, result_from_git; for a rolling round also cohort,
          cohorts_available and cohorts ([{cohort, path, checkout_short}], several with --cohort=all)
        """

        c = ctx.get('control', {})
        con, quiet, verbose = c.get('con', False), c.get('quiet', False), c.get('verbose', False)

        _local = ctx['tasks']['local']
        _global = ctx['tasks']['global']

        version = _local['version']
        key = 'clone-git-to-cache-' + _local['name'].replace('.', '-')

        result = self._result(_global[key], version)

        if 'cohort' not in _local:
            return result

        # A rolling round: the cohort cloned by the pipeline, and the others asked for (--cohort=all)
        cohorts = []
        for cohort in _local['cohorts_wanted']:
            if cohort == _local['cohort']:
                one = result
            else:
                r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run',
                                    'arg1': 'clone-git-to-cache,86919b3cfdd443d2', 'ctx': ctx,
                                    'name': f'mlperf-endpoints-results-{version}-{cohort}'.lower(), 'url': _local['url'],
                                    'checkout': cohort, 'version': version, 'root_dir': params.get('root_dir'),
                                    'cache_extra_tags': params.get('extra_tags'), 'con': con, 'quiet': quiet,
                                    'verbose': verbose})
                if self.cm.catch_error(r): return r
                one = self._result(r, version)
            cohorts.append({'cohort': cohort, 'path': one['path'], 'checkout_short': one.get('checkout_short')})

        result['cohort'] = _local['cohort']
        result['cohorts_available'] = _local['cohorts_available']
        result['cohorts'] = cohorts

        if con and len(cohorts) > 1:
            print('')
            for x in cohorts:
                print(f'  {x["cohort"]}: {x["path"]} ({x.get("checkout_short")})')

        return result
