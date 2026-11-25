"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import re
import subprocess

from task_c36be4b9314a45e0.api.ctask import InitCTask

# Names a Windows checkout cannot hold, or that git refuses there as NTFS tricks: characters NTFS refuses (":" opens an
# alternate data stream), a trailing dot or space, a reserved device name, ".git" and its 8.3 short forms
WINDOWS_BAD_CHARS = set(':*?"<>|\\')
WINDOWS_RESERVED = {'CON', 'PRN', 'AUX', 'NUL'} | {f'COM{i}' for i in range(1, 10)} | {f'LPT{i}' for i in range(1, 10)}


# Git for Windows refuses a git folder (a repository's .git, a submodule's folder under .git/modules) longer than this:
# "fatal: '$GIT_DIR' too big". The limit is built into Git (its PATH_MAX of 260 less 40) - neither Windows' long paths
# (LongPathsEnabled) nor core.longpaths lifts it; work-tree files may be longer. Measured with Git 2.53: 220 works,
# 221 is refused.
WINDOWS_GIT_DIR_LIMIT = 220

# How a command goes into a folder: cmd.exe's "cd <path>" stays on the current drive when the path is on another one
# (a clone in a file cache on D:, a run that stands on C: - every git command then ran in the wrong folder: "not a git
# repository"); "cd /d" changes the drive too
CD = 'cd /d' if os.name == 'nt' else 'cd'


def remote_has_ref(git_bin, url, ref, timeout = 60):
    """Whether the remote has this ref as a tag or a branch (git ls-remote): what a shallow clone takes with --branch.
    A commit, or a remote that does not answer, is no."""
    try:
        p = subprocess.run([git_bin, 'ls-remote', '--exit-code', url, 'refs/tags/' + ref, 'refs/heads/' + ref],
                           stdin = subprocess.DEVNULL, stdout = subprocess.PIPE, stderr = subprocess.PIPE, timeout = timeout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return p.returncode == 0 and bool(p.stdout.strip())


def submodule_paths(git_bin, folder):
    """The submodules a work tree declares (its .gitmodules, read by git itself): [(name, path)], [] without one."""
    gitmodules = os.path.join(folder, '.gitmodules')
    if not os.path.isfile(gitmodules):
        return []
    p = subprocess.run([git_bin, 'config', '-f', gitmodules, '--get-regexp', r'^submodule\..*\.path$'],
                       stdout = subprocess.PIPE, stderr = subprocess.PIPE, stdin = subprocess.DEVNULL)
    out = []
    for line in p.stdout.decode('utf-8', 'replace').splitlines():
        key, _, path = line.partition(' ')
        if key.startswith('submodule.') and key.endswith('.path') and path.strip():
            out.append((key[len('submodule.'):-len('.path')], path.strip()))
    return out


def literal_prefix(pattern):
    """The part of a file pattern before its first segment with a wildcard: 'a/b/*.txt' -> 'a/b', 'a/LICENSE' ->
    'a/LICENSE' (forward slashes, no slash at the ends)."""
    parts = []
    for segment in str(pattern).replace(chr(92), '/').strip('/').split('/'):
        if any(c in segment for c in '*?['):
            break
        parts.append(segment)
    return '/'.join(parts)


def submodule_git_dirs(git_bin, repo):
    """
    The git folders the submodules of a clone need, nested ones included, as Git lays them out -
    <repo>/.git/modules/<name>[/modules/<name> ...] - as far as the work tree is checked out (a submodule that was
    not fetched does not show its own). -> [(git folder, the submodule's path in the clone)], the longest first.
    """
    top = os.path.join(repo, '.git')
    if os.path.isfile(top):                       # a clone with a separate git folder: its .git file names it
        with open(top, encoding = 'utf-8', errors = 'replace') as f:
            text = f.read().strip()
        if text.startswith('gitdir:'):
            top = os.path.normpath(os.path.join(repo, text[len('gitdir:'):].strip()))
    found = []

    def walk(work, git_dir, shown):
        for name, path in submodule_paths(git_bin, work):
            sub_git = os.path.join(git_dir, 'modules', *name.split('/'))
            sub_shown = f'{shown}/{path}' if shown else path
            found.append((sub_git, sub_shown))
            walk(os.path.join(work, *path.split('/')), sub_git, sub_shown)

    walk(repo, top, '')
    return sorted(found, key = lambda x: -len(x[0]))


def windows_git_dir_problem(git_bin, repo):
    """
    Why a submodule update failed on Windows when it is Git's limit of a git folder: the text for the error, or ''
    when no git folder of this clone is over the limit (the failure has another cause).
    """
    dirs = submodule_git_dirs(git_bin, repo)
    over = [(d, s) for d, s in dirs if len(d) > WINDOWS_GIT_DIR_LIMIT]
    if not over:
        return ''
    longest, sub = over[0]
    excess = len(longest) - WINDOWS_GIT_DIR_LIMIT
    return (f'Git for Windows refuses a git folder longer than {WINDOWS_GIT_DIR_LIMIT} characters ("\'$GIT_DIR\' too big"; a limit '
            f'built into Git, which Windows\' long paths and core.longpaths do not lift), and {len(over)} submodule'
            f'{"s" if len(over) != 1 else ""} of this clone need{"" if len(over) != 1 else "s"} a longer one - the longest, '
            f'{len(longest)} characters, for {sub}. The clone is in {repo} ({len(repo)} characters): {excess} character'
            f'{"s" if excess != 1 else ""} too deep for this repository. Give it a shorter place - the file cache keeps clones '
            f'outside the cache entries: "cx config set task --meta.file_cache=<a short folder>" for this machine, or '
            f'"--use.init.file_cache=<a short folder>" for one run')


def windows_refuses(path):
    """Whether a path of a repository cannot be checked out on Windows (any of its parts)."""
    for part in path.split('/'):
        if not part:
            continue
        if any(ch in WINDOWS_BAD_CHARS or ord(ch) < 32 for ch in part):
            return True
        if part[-1] in '. ':
            return True
        if part.split('.')[0].upper() in WINDOWS_RESERVED:
            return True
        low = part.lower()
        if low == '.git' or re.match(r'^\.?git[a-z]*~\d', low):
            return True
    return False


def sparse_pattern(path):
    """A path as a pattern of a non-cone sparse checkout (gitignore syntax), its special characters escaped."""
    out = ''.join('\\' + ch if ch in '\\*?[' else ch for ch in path)
    if out.endswith(' '):
        out = out[:-1] + '\\ '
    return '!/' + out


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def customize_cache_artifact(self,
                                 ctx,
                                 cache_alias_template,
                                 cache_extra_alias,
                                 cache_meta,
                                 cache_tags,
                                 cache_params,
                                 params,
                                 **extra,
        ):

        result = {'return':0}

        url = params.get('url')

        if cache_extra_alias is None: 
            cache_extra_alias = ''

        if url is not None and url != '':
            if url.endswith('.git'):
                url = url[:-4]

            j = url.rfind('/')
            if j>0:
                x1 = url[j+1:]
                url = url[:j]

                j2 = url.rfind('/')
                j3 = url.rfind(':')

                j4 = max(j2,j3)

                if j4>0:
                    x2 = url[j4+1:]
                    if cache_extra_alias !='':
                        cache_extra_alias += self.cache_sep
                    cache_extra_alias = x2 + '@' + x1

        tag = params.get('tag')
        if tag:
            if cache_extra_alias !='':
                cache_extra_alias += self.cache_sep
            cache_extra_alias += tag

        if cache_extra_alias != '':
            result['cache_extra_alias'] = cache_extra_alias

        return result

    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            url: str = None,    
            directory: str = None,
            depth: int = None,
            filter: str = None,
            branch: str = None,
            new_branch: str = None,
            fetch: str = None,
            tag: str = None,
            checkout: str = None,
            update_submodules: bool = False,
            submodules_depth: int = None,         # with update_submodules: shallow submodules (git submodule update --depth)
            submodules_not_recursive: list = None,  # ... these submodules (paths of the clone) without their own submodules
            submodules_files: list = None,        # ... but with the nested submodules that hold these files of the clone
            repo: str = None,                     # an existing clone to work in (its submodules, a checkout): nothing is cloned
            env: dict = {},
            timeout: int = None,
            force: bool = False,
    ):

        """
        Clone git repo.

        Args:
            depth (int): shallow clone with this history depth (`git clone --depth`); checking out
                         a commit older than the fetched history then fails.
            update_submodules (bool): `git submodule update --init --recursive` after the checkout.
            submodules_depth (int): fetch the submodules shallow (`--depth`): the commit each one is pinned
                         to, without its history.
            submodules_not_recursive (list): submodules of the clone, by their paths, that are fetched without
                         their own submodules - the parts a build does not use (their folders are there, as
                         a superproject's own checks expect; what is under them is not). The other submodules
                         are fetched with everything under them.
            submodules_files (list): files of the clone (paths, or patterns: read up to their first wildcard)
                         that a build names inside a submodule of submodules_not_recursive - a licence text
                         its package's metadata lists: the nested submodule that holds each one is fetched
                         (and the ones on the way to it), the others under the named submodule are not.
            repo (str): the folder of a clone made before: this run works in it (its submodules, a checkout)
                         and clones nothing.
            filter (str): partial clone filter (`git clone --filter`), e.g. "blob:none": the full
                          history is fetched but file contents only for the commits checked out.
                          Old blobs stay remote only while nothing reads them: `git show <old>`,
                          `git log -p`, `git blame` and `git cat-file` fetch a missing blob on
                          demand (set GIT_NO_LAZY_FETCH=1 to refuse). For a checkout with no
                          history at all use depth=1 plus fetch="--depth 1 origin <commit>".

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK clone-git run")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''
        clean = ctx_tasks['run_control'].get('clean', False)
        update = ctx_tasks['run_control'].get('update', False)

        print_extra_line = True if con and verbose else False

        _params = {}

        if url is None or url == '':
            return self.cm.error(f'URL is not defined in "{__file__}" ({__name__})')

        path_to_git_bin = ctx_tasks['global']['git']['qpath']

        if tag and not checkout:
            checkout = tag

        if directory is None or directory == '':
            url1 = url
            if url1.endswith('.git'):
                url1 = url1[:-4]

            directory = os.path.basename(url1)

        if timeout == '': 
            timeout = None

        new = False
        if new_branch is not None and new_branch != '':
            branch = new_branch
            new = True


        ###################################################################
        workdir = os.getcwd()

        if con and verbose:
            print ('')
            print (f'{space}INFO: current directory "{workdir}"')

        path_to_git_repo = os.path.join(workdir, directory)

        # --repo: a clone made before (by clone-git-to-cache in a build's pipeline) - worked in where it is
        if repo:
            path_to_git_repo = os.path.abspath(str(repo))
            if not os.path.exists(os.path.join(path_to_git_repo, '.git')):
                return self.cm.error(f'--repo: no git clone in "{path_to_git_repo}"')
            directory = self.cm.q(path_to_git_repo) if hasattr(self.cm, 'q') else f'"{path_to_git_repo}"'
            clean = False

        if isinstance(submodules_not_recursive, str):
            submodules_not_recursive = [x.strip() for x in submodules_not_recursive.split(',') if x.strip()]
        submodules_not_recursive = [str(x).strip().strip('/') for x in (submodules_not_recursive or []) if str(x).strip()]
        if isinstance(submodules_files, str):
            submodules_files = [x.strip() for x in submodules_files.split(',') if x.strip()]
        submodules_files = [str(x).strip() for x in (submodules_files or []) if str(x).strip()]
        sub_depth = f' --depth {int(submodules_depth)}' if submodules_depth not in (None, '', 0, '0') else ''

        if os.path.isdir(path_to_git_repo):
            if clean:
                r = self.cm.utils.files.ask_to_delete(con, force, path_to_git_repo, name='repo', space=True)
                if r['return']>0: return r
                if r['confirmed']: 

                    if verbose:
                        print ('')
                        print (f'{space}RUN rm {path_to_git_repo}')

                    r = self.cm.utils.files.safe_delete_directory(path_to_git_repo, fail_on_error=self.cm.fail_on_error, logger=self.logger)
                    if r['return']>0: return r


        ########\###########################################################
        # Prepare CMDs
        xdepth = f' --depth {depth}' if depth != None and depth != '' else ''

        # Windows: Git checks out no path over 260 characters without its own long paths, whatever Windows allows
        # (a deep cache folder plus llama.cpp's swiftui example: "Filename too long", 2026-10-30) - set in the
        # clone's config, and given to the commands on a clone made before
        git = f'{path_to_git_bin} -c core.longpaths=true' if os.name == 'nt' else path_to_git_bin
        clone_options = ' -c core.longpaths=true' if os.name == 'nt' else ''
        if filter != None and filter != '':
            xdepth += f' --filter={filter}'

        if not os.path.isdir(path_to_git_repo):
            # a shallow clone holds the history of one ref: of the one to check out, when the remote has it as a tag or a
            # branch (--branch), so that the checkout after it finds it; a commit goes through fetch (see depth above)
            ref = branch or checkout
            if depth not in (None, '') and ref and not new:
                git_path = (ctx_tasks['global']['git'].get('path') or path_to_git_bin).strip('"')
                if remote_has_ref(git_path, url, ref):
                    clone_options += f' --branch {ref}'
            cmd = f'{path_to_git_bin} clone{clone_options} {url} {directory}{xdepth}'

            r = self.cm.utils.sys.run(
                    cmd, 
                    env = env, 
                    timeout = timeout, 
                    con = con, 
                    verbose = verbose, 
                    text_cmd = 'RUN', 
                    space = space, 
                    print_extra_line = print_extra_line,
            )
            if self.cm.catch_error(r): return r

            ###################################################################
            # Prepare output
            if not os.path.isdir(path_to_git_repo):
                return self.cm.error(f'Git repo directory was not created: {path_to_git_repo}')

        if os.path.isdir(path_to_git_repo):

            ###################################################################
            # Fetch, branch and checkout
            cmds = []

            if update or fetch or branch or checkout:
                cmd = f'{CD} {directory}'

                if update:
                    cmd += f' && {git} fetch --all --tags --prune'
                    if fetch:
                        cmd += ' ' + fetch
                    if branch or checkout:
                        cmd += f' && {git} pull'
                elif fetch:
                    cmd += f' && {git} fetch ' + fetch

                if branch or checkout:
                    cmd += f' && {git} checkout'

                    if new:
                        cmd +=' -b'

                    if branch:
                        cmd += ' ' + branch

                    if checkout:
                        cmd += ' ' + checkout

                cmds.append(cmd)

            ###################################################################
            # Submodules update

            # (all of them with everything under them - or, with submodules_not_recursive, the clone's own submodules
            # first and then, one by one, what is under each of the others: see _submodules_under)
            submodule_cmd = None
            if update_submodules:
                cmds.append(f'{CD} {directory} && {git} submodule sync')
                submodule_cmd = f'{CD} {directory} && {git} submodule update --init' + ('' if submodules_not_recursive else ' --recursive') + sub_depth
                cmds.append(submodule_cmd)

            ###################################################################
            # TBD: add detect current git checkout and branch
            r = self.cm.utils.files.gen_temp_filepath()
            if r['return']>0: return r
            temp_file_branch = r['filepath']

            cmds.append(f'{CD} {directory} && {path_to_git_bin} rev-parse --abbrev-ref HEAD > {temp_file_branch}')

            r = self.cm.utils.files.gen_temp_filepath()
            if r['return']>0: return r
            temp_file_checkout = r['filepath']

            cmds.append(f'{CD} {directory} && {path_to_git_bin} rev-parse HEAD > {temp_file_checkout}')

            r = self.cm.utils.files.gen_temp_filepath()
            if r['return']>0: return r
            temp_file_tag = r['filepath']

            cmds.append(f'{CD} {directory} && {path_to_git_bin} describe --tags --dirty --always > {temp_file_tag}')

            ###################################################################
            # Run commands
            fail = False

            if len(cmds)>0:
                for cmd in cmds:
                    rx = self.cm.utils.sys.run(
                           cmd, 
                           env = env, 
                           timeout = timeout, 
                           con = con, 
                           verbose = verbose, 
                           text_cmd = 'RUN', 
                           space = space, 
                           print_extra_line = print_extra_line,
                    )
                    if rx['return']>0: 
                        fail = True
                        break

                    returncode = rx['returncode']
                    if returncode>0:
                        rx['return'] = 99
                        rx['error'] = f'CMD "{cmd}" failed with return code {returncode}'
                        if cmd == submodule_cmd and os.name == 'nt':
                            # Git's own limit of a git folder on Windows: said with the folder and the way out
                            why = windows_git_dir_problem(path_to_git_bin.strip('"'), path_to_git_repo)
                            if why:
                                rx['error'] = why
                                rx['git_dir_too_long'] = True
                        fail = True
                        break

                    if cmd == submodule_cmd and submodules_not_recursive:
                        rx = self._submodules_under(git, path_to_git_bin.strip('"'), path_to_git_repo, submodules_not_recursive,
                                                    sub_depth, env, timeout, con, verbose, space, print_extra_line)
                        if rx['return'] > 0:
                            fail = True
                            break
                        if submodules_files:
                            rx = self._submodule_files(git, path_to_git_bin.strip('"'), path_to_git_repo, submodules_files,
                                                       submodules_not_recursive, sub_depth, env, timeout, con, verbose, space,
                                                       print_extra_line)
                            if rx['return'] > 0:
                                fail = True
                                break

            if not fail:
                # Read text files
                r = self.cm.utils.files.safe_read_file(temp_file_branch, retry_if_not_found=1)
                if self.cm.catch_error(r): return r
                branch = r['data'].strip()
                _params['branch'] = branch

                r = self.cm.utils.files.safe_read_file(temp_file_checkout, retry_if_not_found=1)
                if self.cm.catch_error(r): return r
                checkout = r['data'].strip()
                _params['checkout'] = checkout

                r = self.cm.utils.files.safe_read_file(temp_file_tag, retry_if_not_found=1)
                if self.cm.catch_error(r): return r
                tag = r['data'].strip()
                _params['tag'] = tag

            # Clean temp files
            if os.path.isfile(temp_file_branch): os.remove(temp_file_branch)
            if os.path.isfile(temp_file_checkout): os.remove(temp_file_checkout)
            if os.path.isfile(temp_file_tag): os.remove(temp_file_tag)

            # Quit if fail
            if fail:
                self.cm.catch_error(rx)
                return rx


        ###################################################################
        # Windows: a repository with names Windows refuses was cloned with an empty work tree (git refuses the whole
        # checkout: "invalid path"; MLPerf Inference v6.0 has three names with ":") - checked out without them
        windows_skipped = []
        if os.name == 'nt' and os.path.isdir(path_to_git_repo):
            git_path = ctx_tasks['global']['git'].get('path') or path_to_git_bin.strip('"')
            r = self._windows_checkout(git_path, path_to_git_repo, con, space)
            if self.cm.catch_error(r): return r
            windows_skipped = r['skipped']

        ###################################################################
        # Prepare result
        result = {'return':0,
                  'url': url,
                  'path_to_git_repo': path_to_git_repo,
                  'branch': branch,
                  'checkout': checkout}

        _params['git_path'] = path_to_git_repo

        ###################################################################
        # Check size and time ...
        # (--repo: a clone made before, with what a build left in it - not measured again on every run)
        if not repo:
            r = self.cm.utils.sys.get_dir_size(path_to_git_repo, unit='MB', skip_datetime=True)
            if self.cm.catch_error(r): return r
            del(r['return'])

            result['_impact'] = {'dir_size':r}

        if checkout is not None and len(checkout)>7:
            checkout_short = checkout[:7]
            result['checkout_short'] = checkout_short

        if windows_skipped:
            result['windows_skipped_paths'] = windows_skipped

        if len(_params)>0:
            result['_update_params'] = _params

        return result

    ############################################################
    def _submodules_under(self, git, git_bin, repo, not_recursive, sub_depth, env, timeout, con, verbose, space, print_extra_line):
        """
        The plan of submodules_not_recursive, after the clone's own submodules were fetched: every submodule that is
        not named gets what is under it (git submodule update --init --recursive in it); a named one stays as it is.
        A name that is no submodule of the clone is an error (a plan that names nothing would fetch everything).
        """
        declared = [path for _, path in submodule_paths(git_bin, repo)]
        unknown = [x for x in not_recursive if x not in declared]
        if unknown:
            return self.cm.error(f'submodules_not_recursive names no submodule of {repo}: {", ".join(unknown)} (its submodules: '
                                 f'{", ".join(declared) or "none"})')
        for path in declared:
            folder = os.path.join(repo, *path.split('/'))
            if path in not_recursive or not os.path.isfile(os.path.join(folder, '.gitmodules')):
                continue
            cmd = f'{CD} {self.cm.q(folder) if hasattr(self.cm, "q") else chr(34) + folder + chr(34)} && {git} submodule update --init --recursive{sub_depth}'
            rx = self.cm.utils.sys.run(cmd, env = env, timeout = timeout, con = con, verbose = verbose, text_cmd = 'RUN',
                                       space = space, print_extra_line = print_extra_line)
            if rx['return'] > 0:
                return rx
            if rx['returncode'] > 0:
                rx['return'] = 99
                rx['error'] = f'CMD "{cmd}" failed with return code {rx["returncode"]}'
                if os.name == 'nt':
                    why = windows_git_dir_problem(git_bin, repo)
                    if why:
                        rx['error'] = why
                        rx['git_dir_too_long'] = True
                return rx
        if con and verbose:
            print('')
            print(f'{space}INFO: the submodules fetched without their own: {", ".join(not_recursive)}')
        return {'return': 0}

    ############################################################
    def _submodule_files(self, git, git_bin, repo, files, not_recursive, sub_depth, env, timeout, con, verbose, space, print_extra_line):
        """
        submodules_files, after the plan of submodules_not_recursive: a file the build names inside a submodule that
        was fetched without its own is in one of its nested submodules - that one is fetched (and the ones on the way
        to it), nothing else under the named submodule. A file that is the clone's own, or under a submodule that is
        whole, or the named submodule's own, asks for nothing. -> {'return': 0, 'fetched': [paths in the clone]}
        """
        fetched = []
        for wanted in files:
            path = literal_prefix(wanted)
            top = next((s for s in not_recursive if path.startswith(s + '/')), None)
            if not top:
                continue
            current, rest = top, path[len(top) + 1:]
            while rest:
                folder = os.path.join(repo, *current.split('/'))
                nested = next((p for _, p in submodule_paths(git_bin, folder) if rest == p or rest.startswith(p + '/')), None)
                if nested is None:
                    break                                           # the rest is this submodule's own tree
                target = current + '/' + nested
                if not os.path.exists(os.path.join(repo, *target.split('/'), '.git')):
                    quoted = self.cm.q(folder) if hasattr(self.cm, 'q') else chr(34) + folder + chr(34)
                    cmd = f'{CD} {quoted} && {git} submodule update --init{sub_depth} -- "{nested}"'
                    rx = self.cm.utils.sys.run(cmd, env = env, timeout = timeout, con = con, verbose = verbose, text_cmd = 'RUN',
                                               space = space, print_extra_line = print_extra_line)
                    if rx['return'] > 0:
                        return rx
                    if rx['returncode'] > 0:
                        rx['return'] = 99
                        rx['error'] = f'CMD "{cmd}" failed with return code {rx["returncode"]}'
                        if os.name == 'nt':
                            why = windows_git_dir_problem(git_bin, repo)
                            if why:
                                rx['error'] = why
                                rx['git_dir_too_long'] = True
                        return rx
                    fetched.append(target)
                current, rest = target, rest[len(nested) + 1:]
        if con and verbose and fetched:
            print('')
            print(f'{space}INFO: fetched for the files the build names in them: {", ".join(fetched)}')
        return {'return': 0, 'fetched': fetched}

    ############################################################
    def _windows_checkout(self, git_bin, repo, con, space):
        """
        Windows: a clone whose HEAD holds names Windows refuses (windows_refuses) and whose checkout git therefore never
        made (an empty index): a non-cone sparse checkout of everything but those paths, then the files of HEAD. Git's
        NTFS protection is lifted for that one command only: every name it would refuse is outside the checkout, so
        none is written. Returns the paths left out ([] when the clone did not need it).
        """
        def git(args, data = None):
            p = subprocess.run([git_bin, '-C', repo, '-c', 'core.longpaths=true'] + args, input = data,
                               stdout = subprocess.PIPE, stderr = subprocess.PIPE)
            return p.returncode, p.stdout.decode('utf-8', 'replace'), p.stderr.decode('utf-8', 'replace')

        rc, tree, _ = git(['ls-tree', '-r', '-z', '--name-only', 'HEAD'])
        names = [x for x in tree.split('\0') if x] if rc == 0 else []
        if not names:
            return {'return': 0, 'skipped': []}

        rc, files, _ = git(['ls-files', '-z'])
        if rc == 0 and files.strip('\0'):
            return {'return': 0, 'skipped': []}             # checked out (or a sparse checkout chosen before)

        refused = [x for x in names if windows_refuses(x)]
        if not refused:
            return {'return': 0, 'skipped': []}             # empty for another reason: left as it is

        if con:
            print('')
            print(f'{space}INFO: {len(refused)} of {len(names)} paths of this repository have names Windows refuses '
                  f'(first: {refused[0]}): checking out the others')

        patterns = '/*\n' + ''.join(sparse_pattern(x) + '\n' for x in refused)
        rc, _, err = git(['sparse-checkout', 'set', '--no-cone', '--stdin'], data = patterns.encode('utf-8'))
        if rc != 0:
            return self.cm.error(f'git sparse-checkout failed in {repo}: {err.strip()}')

        rc, _, err = git(['-c', 'core.protectNTFS=false', 'reset', '-q', '--hard', 'HEAD'])
        if rc != 0:
            return self.cm.error(f'the checkout without the {len(refused)} names Windows refuses failed in {repo}: '
                                 f'{err.strip()}')

        rc, files, _ = git(['ls-files', '-z'])
        if rc != 0 or not files.strip('\0'):
            return self.cm.error(f'the checkout without the names Windows refuses left no files in {repo}')

        return {'return': 0, 'skipped': refused}

