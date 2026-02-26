import os
import platform
import sys
import struct
import copy

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
    ):
        r = self.cm.check_params(params, ['env','bits','timeout','extra'], __name__)
        if self.cm.catch_error(r): return r

        return {'return':0}


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            env: dict = {},
            bits: int = None,
            timeout: int = 10,
            extra: bool = False,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call']

        env_os = os.environ

        # Convert +keys to lists
        _env = env.copy()
        self.cm.utils.sys.plus_env(_env)

        result = {'return':0, 
                  'os_env':env_os.copy()
        }

        ##################################################################
        # Check various platform info
        pbits = 8 * struct.calcsize("P")

        if not bits:
            bits = 32
            if os.name == 'nt':
                # Trying to get fast way to detect bits
                if os.environ.get('ProgramW6432', '') != '' or os.environ.get('ProgramFiles(x86)', '') != '':  # pragma: no cover
                    bits = 64
            else:
                # On Linux use first getconf LONG_BIT and if doesn't work use python bits
                bits = pbits

                cmd = 'getconf LONG_BIT'

                r = self.cm.utils.sys.run(cmd, env = env, genv = env_os, timeout = timeout, capture_output = True,
                                          con = False, verbose = verbose, text_cmd = 'RUN', space = space)
                if self.cm.catch_error(r): return r
                if r['returncode'] == 0:
                    s = r['stdout'].strip()
                    if len(s) > 0 and len(s) < 4:
                        try:
                            bits = int(s)
                        except:
                            pass

        host_os = {}

        host_os['python_bits'] = pbits
        host_os['bits'] = bits

        host_os['python_platform_architecture'] = platform.architecture()
        host_os['python_platform_machine'] = platform.machine()
        host_os['python_platform_node'] = platform.node()
        host_os['python_platform_system'] = platform.system()
        host_os['python_platform_release'] = platform.release()
        host_os['python_platform_version'] = platform.version()
        host_os['python_platform'] = platform.platform()
        host_os['python_platform_terse'] = platform.platform(terse = True)
        host_os['python_platform_aliased'] = platform.platform(aliased = True)
        host_os['python_platform_uname'] = platform.uname()
        host_os['python_os_name'] = os.name
        host_os['python_os_cpu_count'] = os.cpu_count()
        host_os['python_sys_platform'] = sys.platform
        host_os['python_platform_processor'] = platform.processor()

        # OS name
        uname = ''

        if os.name == 'nt':
            uname = 'windows'
        else:
            uname = None
            cmd = 'uname'

            r = self.cm.utils.sys.run(cmd, env = env, genv = env_os, timeout = timeout, capture_output = True,
                                      con = False, verbose = verbose, text_cmd = 'RUN', space = space)
            if self.cm.catch_error(r): return r
            if r['returncode'] == 0:
                uname = r['stdout'].strip().lower()

        host_os['uname'] = uname

        # OS arch
        uarch = ''

        if os.name == 'nt':
            uarch = platform.machine().lower()
        else:
            # https://stackoverflow.com/questions/45125516/possible-values-for-uname-m

            cmd = 'uname -m'

            uarch = None

            r = self.cm.utils.sys.run(cmd, env = env, genv = env_os, timeout = timeout, capture_output = True,
                                      con = False, verbose = verbose, text_cmd = 'RUN', space = space)
            if self.cm.catch_error(r): return r
            if r['returncode'] == 0:
                uarch = r['stdout'].strip().lower()

            os_release = ''
            if os.path.isfile('/etc/os-release'):
                os_release_dict = {}
                try:
                    with open("/etc/os-release") as f:
                       os_release_dict = dict(line.strip().split("=", 1) for line in f if "=" in line)
                except:
                    pass

                host_os['release_name'] = f"{os_release_dict.get('PRETTY_NAME', 'Unknown')}".replace('"', '')

                kernel_version = os.uname().release

                host_os['release_name_with_kernel'] = f"{host_os['release_name']} ({kernel_version})"

        if uarch == 'x86_64': uarch = 'amd64'

        # May have armv6l, aarch64, riscv64 ...

        host_os['uarch'] = uarch

        # Finish automation
        result['os'] = host_os

        # Common vars
        all_vars = {
          'windows':{
            'file_ext_exe': '.exe',
            'file_ext_exe_search': '.exe',
            'file_ext_bat': '.bat',
            'call_script': 'call',
            'cmd_sep': '&&',
          },
          'linux':{
            'file_ext_exe': '',
            'file_ext_exe_search': '.',
            'file_ext_bat': '.sh',
            'call_script': '.',
            'cmd_sep': '&&',
          },
          'macos':{
            'file_ext_exe': '',
            'file_ext_exe_search': '.',
            'file_ext_bat': '.sh',
            'call_script': '.',
            'cmd_sep': '&&',
          },
        }

        vars_os = uname if uname in all_vars else 'linux'
        
        result['vars'] = all_vars[vars_os]

        # Initialize for global use !
        result['_aggregate'] = {'env':_env}

        # Check if not Windows and ~/.local/bin exists but not in PATH:
        home = os.path.expanduser("~")

        host_os['home_path'] = home

        if os.name != 'nt':
            path_local_bin = os.path.join(home, '.local', 'bin')
            if os.path.isdir(path_local_bin) and path_local_bin not in os.environ.get('PATH',''):
                _path = _env.setdefault('+PATH', [])
                _path.append(path_local_bin)

        return result
