"""

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Extracted from the standalone project helpers by Grigori Fursin.
The original notices are retained in the dated project archive.
"""

import argparse
from pathlib import Path
import re
import shutil
import subprocess

def git_command(directory, args, env, check=True):
    result = subprocess.run(['git', '-C', str(directory)] + list(args), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and result.returncode:
        detail = re.sub(r'https?://\S+', '<remote>', result.stderr.strip())
        raise RuntimeError('Git {} failed for {} (exit {}): {}'.format(
                           args[0], directory.name, result.returncode, detail[:600]))
    return result


def update_git_repos(argv, python, env):
    parser = argparse.ArgumentParser(description='Update only Git repositories immediately under this project/repos.')
    parser.add_argument('--repo', action='append', default=[], help='Select a repository folder; repeat for several')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--checkout', help='Select an origin branch or tag for one repository')
    selection.add_argument('--branch', help='Select an origin branch for one repository')
    selection.add_argument('--release', help='Select an exact release tag for one repository')
    parser.add_argument('--status', '--dry-run', action='store_true', help='Show local state without fetching or updating')
    options = parser.parse_args(argv)
    if not shutil.which('git', path=env.get('PATH')):
        raise RuntimeError('Git is required. Install it or run __cx tool setup git first.')
    base = ROOT / 'repos'
    candidates = sorted(p for p in base.iterdir() if p.is_dir() and (p / '.git').exists()
                        and any((p / name).is_file() for name in ('_cmr.yaml', '_cmr.json')))
    wanted = {name for item in options.repo for name in item.split(',') if name}
    unknown = wanted - {p.name for p in candidates}
    if unknown:
        raise RuntimeError('No project-owned Git repository: ' + ', '.join(sorted(unknown)))
    candidates = [p for p in candidates if not wanted or p.name in wanted]
    explicit = options.checkout or options.branch or options.release
    if explicit and len(candidates) != 1:
        raise RuntimeError('A branch/release override needs exactly one Git repository; select it with --repo.')
    if explicit and (explicit.startswith('-') or '\n' in explicit):
        raise RuntimeError('Invalid branch/tag name')

    # Check all selected trees before changing any of them. Never walk into an enclosing Git repository.
    for directory in candidates:
        actual = Path(git_command(directory, ['rev-parse', '--show-toplevel'], env).stdout.strip()).resolve()
        if actual != directory.resolve() or not actual.is_relative_to(ROOT):
            raise RuntimeError('Git working tree is outside this project repository: ' + directory.name)
        dirty = git_command(directory, ['status', '--porcelain'], env).stdout.strip()
        if dirty and not options.status:
            raise RuntimeError('Uncommitted/untracked files in {}. Commit or stash them before updating.'.format(directory.name))

    try:
        for directory in candidates:
            branch = git_command(directory, ['symbolic-ref', '--quiet', '--short', 'HEAD'], env, check=False).stdout.strip()
            before = git_command(directory, ['rev-parse', '--short', 'HEAD'], env).stdout.strip()
            tag = git_command(directory, ['describe', '--tags', '--exact-match'], env, check=False).stdout.strip()
            label = branch or tag or 'detached'
            print('{}: {} ({})'.format(directory.name, label, before), flush=True)
            if explicit:
                ref = explicit
            else:
                symbolic = git_command(directory, ['ls-remote', '--symref', 'origin', 'HEAD'], env).stdout
                match = re.search(r'^ref: refs/heads/(.+)\s+HEAD$', symbolic, re.MULTILINE)
                if not match:
                    raise RuntimeError('Cannot determine the origin default branch for ' + directory.name)
                ref = match.group(1).strip()
            if options.status:
                print('  Would update to {}: {}'.format('release tag' if options.release else 'origin branch/tag', ref), flush=True)
                continue

            is_branch = not options.release and bool(git_command(directory, ['ls-remote', '--heads', 'origin', 'refs/heads/' + ref], env).stdout.strip())
            if options.branch and not is_branch:
                raise RuntimeError('No origin branch named ' + ref)

            if is_branch:
                # Preserve the existing shallow boundary: a repeated --depth=1 can
                # cut off the current local head and prevent a fast-forward pull.
                git_command(directory, ['fetch', 'origin', 'refs/heads/' + ref + ':refs/remotes/origin/' + ref], env)
                fetch_specs = git_command(directory, ['config', '--get-all', 'remote.origin.fetch'], env, check=False).stdout
                wanted_spec = 'refs/heads/' + ref + ':refs/remotes/origin/' + ref
                if wanted_spec not in fetch_specs and 'refs/heads/*:refs/remotes/origin/*' not in fetch_specs:
                    git_command(directory, ['remote', 'set-branches', '--add', 'origin', ref], env)
                exists = git_command(directory, ['show-ref', '--verify', '--quiet', 'refs/heads/' + ref], env, check=False).returncode == 0
                git_command(directory, ['checkout', ref] if exists else ['checkout', '-b', ref, '--track', 'origin/' + ref], env)
                git_command(directory, ['branch', '--set-upstream-to=origin/' + ref, ref], env)
                branch = ref
            else:
                if not git_command(directory, ['ls-remote', '--tags', 'origin', 'refs/tags/' + ref], env).stdout.strip():
                    raise RuntimeError('No origin branch or tag named ' + ref)
                git_command(directory, ['fetch', 'origin', 'refs/tags/' + ref + ':refs/tags/' + ref], env)
                git_command(directory, ['checkout', '--detach', ref], env)
                branch = ''

            if branch:
                upstream = git_command(directory, ['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}'], env, check=False)
                if upstream.returncode:
                    raise RuntimeError('{} has no upstream. Select its origin branch explicitly with --checkout.'.format(directory.name))
                # The older supported engine's repo pull can report success after a failed Git pull.
                # Check Git's exit code directly and allow only fast-forward updates.
                git_command(directory, ['-c', 'pull.rebase=false', 'pull', '--ff-only'], env)
            after = git_command(directory, ['rev-parse', '--short', 'HEAD'], env).stdout.strip()
            print('  {} -> {}'.format(before, after), flush=True)
    finally:
        if candidates and not options.status:
            reindex(python, env)
    if not candidates:
        print('No Git repositories selected; local and snapshot repositories are unchanged.', flush=True)
    print('Git status complete.' if options.status else 'Git repository update complete.', flush=True)


