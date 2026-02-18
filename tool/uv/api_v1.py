import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def install(self,
                state: dict,
                params: dict,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL uv api_v1 install")

        # Can be current dir or cache!
        working_dir = os.getcwd()

        result = {'return':0}

        con = params.get('con')
        quiet = params.get('quiet')
        verbose = params.get('verbose')

        env = params.get('env')
        version = params.get('version')
        timeout = params.get('timeout')

        cmd = 'winget install --id=astral-sh.uv -e'

        if version:
            cmd +=f' --version {version}'

        ii = {'category': 'task,c36be4b9314a45e0',
              'command': 'run',
              'state': state,
              'arg1': 'cmd,c9ba0a88df394d7f',
              'cmd': cmd,
              'env': env,
              'timeout': timeout,
              'con': con, 
              'verbose': verbose, 
              'text_cmd': 'RUN:', 
        }

        rx = self.cm.access(ii)
        if rx['return']>0: return self.cm._error2(rx, self.cm)

        returncode = rx['returncode']
        if returncode>0:
            result['failed'] = True

        result['found_paths'] = None

        return result
