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
            env: dict = {},
            timeout: int = None,
            force: bool = False,
    ):

        """
        Clone git repo.

        Args:
            depth (int): shallow clone with this history depth (`git clone --depth`); checking out
                         a commit older than the fetched history then fails.
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
                cmd = f'cd {directory}'

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

            if update_submodules:
                cmds.append(f'cd {directory} && {git} submodule sync')
                cmds.append(f'cd {directory} && {git} submodule update --init --recursive')

            ###################################################################
            # TBD: add detect current git checkout and branch
            r = self.cm.utils.files.gen_temp_filepath()
            if r['return']>0: return r
            temp_file_branch = r['filepath']

            cmds.append(f'cd {directory} && {path_to_git_bin} rev-parse --abbrev-ref HEAD > {temp_file_branch}')

            r = self.cm.utils.files.gen_temp_filepath()
            if r['return']>0: return r
            temp_file_checkout = r['filepath']

            cmds.append(f'cd {directory} && {path_to_git_bin} rev-parse HEAD > {temp_file_checkout}')

            r = self.cm.utils.files.gen_temp_filepath()
            if r['return']>0: return r
            temp_file_tag = r['filepath']

            cmds.append(f'cd {directory} && {path_to_git_bin} describe --tags --dirty --always > {temp_file_tag}')

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

