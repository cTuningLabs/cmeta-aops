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
            self.logger.debug("RUNNING TOOL llvm api_v1 install")

        ctx_tasks = ctx['tasks']

        _global = ctx['tasks']['global']

        uname = _global['host']['os']['uname']
        uarch = _global['host']['os']['uarch']

        version_simple = params.get('version_simple')

        if not version_simple:
            return {
                'return': 16, 
                'error': f'custom install for LLVM can use only exact/simple versions in "{__file__}"',
                'install_cmd': cmd, # this is needed to proceed with the main installation routine !
            }

        con = params.get('control', {}).get('con', False)
        quiet = params.get('control', {}).get('quiet', False)
        verbose = params.get('control', {}).get('verbose', False)
        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        env = params.get('env')
        timeout = params.get('timeout')

        version_major = int(params.get('version_major'))

        url = None
        filename = None

        if uname == 'windows':
            if uarch == 'amd64':
                uarch2 = 'x86_64'
                filename = f'clang+llvm-{version_simple}-{uarch2}-pc-windows-msvc.tar.xz'
        elif uname == 'linux':
            if uarch == 'amd64':
                uarch2 = 'X64'
                filename = f'LLVM-{version_simple}-Linux-{uarch2}.tar.xz'
        elif uname == 'darwin':
            if uarch == 'arm64':
                uarch2 = 'ARM64'
                filename = f'LLVM-{version_simple}-macOS-{uarch2}.tar.xz'

        if not filename:
            return {
                'return': 16, 
                'error': f'custom install for LLVM could not create download URL',
                'install_cmd': cmd, # this is needed to proceed with the main installation routine !
            }

        url = f'https://github.com/llvm/llvm-project/releases/download/llvmorg-{version_simple}/{filename}'

        path_to_clang = os.path.join(os.getcwd(), 'content', 'bin', 'clang' + _global['host']['vars']['file_ext_exe'])

        if con:
            cur_dir = os.getcwd()
            print ('')
            print (f'{space}INFO: Current path: {cur_dir}')
            print (f'{space}INFO: LLVM download URL: {url}')
            print (f'{space}INFO: Check file: {path_to_clang}')

        ###########################################################################################
        # Attempt to download file

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'arg1': 'download-file,03fed13e2e0447cf',
              'ctx': ctx,
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
              'check_file': path_to_clang,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        return {'return':0, 'found_path': path_to_clang}

