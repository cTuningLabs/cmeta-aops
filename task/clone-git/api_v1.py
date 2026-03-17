import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

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

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK clone-git-repo run")

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''
        clean = ctx_tasks['control'].get('clean', False)
        update = ctx_tasks['control'].get('update', False)

        _params = {}

        if url is None or url == '':
            return self.cm.error(f'URL is not defined in {__name__}')

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

        if not os.path.isdir(path_to_git_repo):
            cmd = f'git clone {url} {directory}{xdepth}'

            r = self.cm.utils.sys.run(cmd, env = env, timeout = timeout, con = con, verbose = verbose, text_cmd = 'RUN', space = space)
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
                    cmd += ' && git fetch --all --tags --prune'
                    if fetch:
                        cmd += ' ' + fetch
                elif fetch:
                    cmd += ' && git fetch ' + fetch

                if branch or checkout:
                    cmd += ' && git checkout'

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
                cmds.append(f'cd {directory} && git submodule sync')
                cmds.append(f'cd {directory} && git submodule update --init --recursive')

            ###################################################################
            # TBD: add detect current git checkout and branch
            r = self.cm.utils.files.gen_temp_filepath()
            if r['return']>0: return r
            temp_file_branch = r['filepath']

            cmds.append(f'cd {directory} && git rev-parse --abbrev-ref HEAD > {temp_file_branch}')

            r = self.cm.utils.files.gen_temp_filepath()
            if r['return']>0: return r
            temp_file_checkout = r['filepath']

            cmds.append(f'cd {directory} && git rev-parse HEAD > {temp_file_checkout}')

            r = self.cm.utils.files.gen_temp_filepath()
            if r['return']>0: return r
            temp_file_tag = r['filepath']

            cmds.append(f'cd {directory} && git describe --tags --dirty --always > {temp_file_tag}')

            ###################################################################
            # Run commands
            fail = False

            if len(cmds)>0:
                for cmd in cmds:
                    rx = self.cm.utils.sys.run(cmd, env = env, timeout = timeout, con = con, verbose = verbose, text_cmd = 'RUN', space = space)
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
        # Prepare result
        result = {'return':0,
                  'url': url,
                  'path_to_git_repo': path_to_git_repo,
                  'branch': branch,
                  'checkout': checkout}

        ###################################################################
        # Check size and time ...
        r = self.cm.utils.sys.get_dir_size(path_to_git_repo, unit='MB', skip_datetime=True)
        if self.cm.catch_error(r): return r
        del(r['return'])

        result['_impact'] = {'dir_size':r}

        if checkout is not None and len(checkout)>7:
            checkout_short = checkout[:7]
            result['checkout_short'] = checkout_short

        if len(_params)>0:
            result['_update_params'] = _params    

        return result
