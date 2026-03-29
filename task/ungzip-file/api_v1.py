import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def init(self,
             ctx: dict,
             params: dict,
    ):
        """
        We need this function to resolve name if not provided,
        to be able to customize cache_artifact properly.

        We can also add extra checks on unified params here.
        """

        result = {'return':0}

        filename = params.get('filename')
 
        if not filename:
            return self.cm.error(f'filename is not defined in "{__file__}" ({__name__})')

        if not os.path.isfile(filename):
            return self.cm.error(f'filename "{filename}" not found in "{__file__}" ({__name__})')

        return result


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

        # It's dangerous because filenames can contain weird characters
        # Either clean it or rely on manually added cache_extra_alias

#        filename = params['filename']
#
#        if cache_extra_alias is None: 
#            cache_extra_alias = ''
#
#        if cache_extra_alias !='':
#            cache_extra_alias += self.cache_sep
#        cache_extra_alias += filename
#
#        result['cache_extra_alias'] = cache_extra_alias


        return result

    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            filename: str = None,
            env: dict = {},
            directory: str = None,
            clean_after_ungzip: bool = False,
            timeout: int = None,
            fail_if_nonzero_return_code: bool = True,
    ):

        """
        Untar file.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK untar-file run api_v1")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''
        clean = ctx['tasks']['run_control'].get('clean', False)
        update = ctx['tasks']['run_control'].get('update', False)

        uname = ctx['tasks']['global']['host']['os']['uname']

        _local = {}

        ungzip_path = ctx['tasks']['global']['gzip']['qpath']

        if not directory:
            directory = os.getcwd()

        path = os.path.abspath(directory)
        qpath = self.cm.utils.files.quote_path(path)

        if not os.path.exists(path):
            os.makedirs(path)
 
        cmd = f'{ungzip_path} {filename} -d {qpath}'

        ii = {'category': self.category_alias + ',' + self.category_uid,
              'command': 'run',
              'ctx': ctx,
              'arg1': 'cmd,c9ba0a88df394d7f',
              'cmd': cmd,
              'env': env,
              'con': con, 
              'quiet': quiet,
              'verbose': verbose, 
              'quiet': quiet,
              'text_cmd': 'RUN:',
#              'print_env_keys': [], 
              'print_extra_line': True,
              'fail_if_nonzero_return_code': fail_if_nonzero_return_code,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        if clean_after_ungzip and os.path.isfile(filename):
            if verbose:
                print (f'{space}RUN: rm {filename}')

            os.remove(filename)

        return {'return':0, 'path':path, 'qpath':qpath}

