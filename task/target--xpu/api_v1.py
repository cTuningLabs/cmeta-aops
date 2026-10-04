import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

INTEL_GPU_RUNTIME = 'intel-gpu-runtime,1fce5a1fbba34a81'


def parse_gpus(data, uname):
    """
    The GPUs in the probe's output: lspci lines on Linux, and the Name/DriverVersion pairs
    that PowerShell prints for Win32_VideoController (Format-List) on Windows - and in WSL2,
    where lspci sees a virtual adapter and the probe asks Windows (powershell.exe).
    """
    devices = []
    for line in data.splitlines():
        key, sep, value = line.partition(':')
        key = key.strip()
        if sep and key == 'Name':
            devices.append({'name': value.strip()})
        elif sep and key == 'DriverVersion' and devices:
            devices[-1]['driver_version'] = value.strip()
        elif uname != 'windows':
            # 00:02.0 VGA compatible controller: Intel Corporation Arc A770 [8086:56a0]
            slot, _, rest = line.strip().partition(' ')
            pci_class, sep, name = rest.partition(': ')
            if sep and ':' in slot:
                devices.append({'pci_slot': slot, 'class': pci_class, 'name': name.strip()})
    return devices


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            **kwargs
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        r = self._detect(ctx)
        if self.cm.catch_error(r): return r

        # !FGG: just a prototype - can be extended

        result = {
          'return':0,
          'features': r['features']
        }

        return result

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        A cached target keeps the GPUs of the run that created the entry, possibly on another
        machine (a copied or shared CMETA_HOME). The probe ran again in this call ('uses'),
        so its output describes this machine now.

        On Linux x86_64 an Intel GPU computes only with the user-space compute runtime: set up
        tool/intel-gpu-runtime (the system's, else Intel's packages unpacked without root), whose
        result exports it to the steps that follow. Windows has it in the graphics driver.
        """

        temp_file = ctx['tasks']['local'].get('generate-temp-file-target-xpu', {}).get('temp_file')

        if temp_file and os.path.isfile(temp_file):
            r = self._detect(ctx)
            if self.cm.catch_error(r): return r

            result['features'] = r['features']

        os_info = ctx['tasks']['global']['host']['os']
        if os_info['uname'] == 'linux' and os_info.get('uarch') == 'amd64' and not params.get('skip_runtime'):
            c = ctx['control']
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'run', 'arg1': 'setup,a2f9b61079ce4333',
                                'ctx': ctx, 'name': INTEL_GPU_RUNTIME,
                                'con': c.get('con', False), 'quiet': c.get('quiet', False), 'verbose': c.get('verbose', False)})
            if self.cm.catch_error(r): return r
            runtime = ctx['tasks']['global'].get('intel-gpu-runtime', {})
            result.setdefault('features', {})['runtime'] = {
                'path': runtime.get('path'), 'version': runtime.get('version'),
                'kind': runtime.get('features', {}).get('kind')}

        return {'return': 0, 'result': result}

    ############################################################
    def _detect(self, ctx):
        """
        The Intel GPUs in the probe's output: lspci lines on Linux, or the Name/DriverVersion
        pairs of Win32_VideoController on Windows. Features: the raw output and the devices.
        """

        local = ctx['tasks']['local']
        temp_file = local['generate-temp-file-target-xpu']['temp_file']
        encoding = local.get('encoding')

        if not os.path.isfile(temp_file):
            return self.cm.error(f'temp file "{temp_file}" not found in "{__file__}" ({__name__})')

        r = self.cm.utils.files.read_file(temp_file, encoding = encoding, remove_after_read = True)
        if self.cm.catch_error(r): return r

        data = r['data'].strip()

        uname = ctx['tasks']['global']['host']['os']['uname']
        devices = [d for d in parse_gpus(data, uname) if 'intel' in d['name'].lower()]

        if not devices:
            return self.cm.error(f'Intel Graphics is not detected in "{__file__}"')

        return {'return': 0, 'features': {'output': data, 'devices': devices}}

