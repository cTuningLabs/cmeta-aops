import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def install(self,
                ctx: dict,
                params: dict,
                cmd: str = None,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL cmake api_v1 install")

        ctx_tasks = ctx['tasks']

        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        version = params.get('version')
        version_simple = params.get('version_simple')

        if not version:
            version = '4.3.1'
            version_simple = version

        if not version_simple:
            return {
                'return': 16, 
                'error': f'custom install for cMake can use only exact/simple versions in "{__file__}"',
                'install_cmd': cmd, # this is needed to proceed with the main installation routine !
            }

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env = params.get('env')
        timeout = params.get('timeout')

        url = None
        filename = None

        if uname == 'windows':
            uos = 'windows'
            uext = '.zip'
            udir = None
            if uarch == 'amd64':
                uarch2 = 'x86_64'
            elif uarch == 'arm64':
                uarch2 = 'arm64'
        elif uname == 'linux':
            uos = 'linux'
            uext = '.tar.gz'
            udir = None
            if uarch == 'amd64':
                uarch2 = 'x86_64'
            elif uarch == 'arm64':
                uarch2 = 'aarch64'
        elif uname == 'darwin':
            uos = 'macos'
            uarch2 = 'universal'
            uext = '.tar.gz'
            udir = 'CMake.app/Contents'

        if not uarch2:
            return {
                'return': 16, 
                'error': f'custom install for cMake could not create download URL',
            }

        filename = f'cmake-{version_simple}-{uos}-{uarch2}{uext}'

        url = f'https://github.com/Kitware/CMake/releases/download/v{version_simple}/{filename}'

        directory = 'content'

        ubin = 'bin'
        if udir:
            ubin = os.path.join(udir, ubin)

        path_to_cmake = os.path.join(os.getcwd(), directory, ubin, 'cmake' + _global['host']['vars']['file_ext_exe'])

        if con:
            cur_dir = os.getcwd()
            print ('')
            print (f'{space}INFO: Current path: {cur_dir}')
            print (f'{space}INFO: cMake download URL: {url}')
            print (f'{space}INFO: Check file: {path_to_cmake}')

        ###########################################################################################
        # Attempt to download file

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'arg1': 'download-file,03fed13e2e0447cf',
              'ctx': ctx,
              'directory': directory,
              'url': url,
              'env': env,
              'timeout': timeout,
              'con': con, 
              'quiet': quiet, 
              'verbose': verbose, 
              'unzip': True,
              'clean': True,
              'clean_after_unzip': True,
              'strip_folders': 1,
              'check_file': path_to_cmake,
              'make_check_file_executable': True,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        return {'return':0, 'found_path': path_to_cmake}

