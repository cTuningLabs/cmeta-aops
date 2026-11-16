"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The hooks of programs converted from the Collective Knowledge (CK) format (cBench, PolyBench/C and
PolyBench/GPU of cmeta-ck-legacy ...). A program inherits them with

  inherits:
    - template-c-cpu,649899ef3f004e4a
    - template-ck-program,f7fab3bed78041d1

and no api_v1.py of its own (task select-program gives a program without hooks those of the first
artifact it inherits that has some). They do what CK's program pipeline did around the command line,
on the host CPU, CUDA and an Android device over adb (an iPhone app, through devicectl, gets no
redirection), driven by the program's local_vars:

- customize2 (compile):
  the WINDOWS define the CK sources use, for a build that runs on a Windows host (cpu, cuda);
  ck_legacy_c       GNU C89 for sources written before C99, with GCC and clang (LEGACY_C_FLAGS);
  ck_size_vars      PolyBench: --compile.size=<mini|small|standard|large|extralarge> replaces these
                    defines (CK's sizes) by the header's size macro; --compile.n=<N> makes every one
                    of them N (square arrays); --compile.dump=yes|no keeps or drops
                    POLYBENCH_DUMP_ARRAYS (default: yes with CK's sizes, no with a size or an N).
                    All are compile parameters, so each choice is a build of its own;
  DATA_TYPE         --compile.precision=float|double sets the define, where a program has it;
  ck_cpu_check      PolyBench/GPU: CK_CPU_CHECK, the CPU reference CK commented out, unless
                    --compile.check=no (a compile parameter too);
- customize_ck_run (run, after the dataset step):
  ck_number_from_dataset  the dataset is a number for the command line ({{local.ck_number}}): the
                          "number" of its result, else the content of its file;
  ck_dataset_more_files   the other files of the dataset, in its order ("files" of its result), as the
                          input files data1, data2 ... ({qinput_files.data1});
  ck_run_files            files of the program (src/) the run expects in its working folder;
  ck_dump_file            an output that exists only when the arrays are dumped (PolyBench);
  ck_redirect_stdio       standard output and error into tmp-output1.tmp and tmp-output2.tmp
                          ({{local.ck_redirects}}; not on iOS, where an app has no redirection);
  ck_opencl_device        the OpenCL platform and device (CK_COMPUTE_PLATFORM_ID, CK_COMPUTE_DEVICE_ID):
                          --opencl_platform and --opencl_device (numbers, or the device by a word of
                          its name), else the first GPU that the opencl target found;
- customize_output_check (the reference outputs, --check_output): what tells the cases of a program
  apart besides its command and input - the defines it was built with (every one it declares but
  XOPENME and WINDOWS, with --compile.size / n / precision / dump applied: NI, DATA_TYPE ...),
  PolyBench's size and dump, the kernel's repeat (--repeat, CK's CT_REPEAT_MAIN; after a
  --calibrate, the repeat it settled on) unless output_check.invariant_of_repeat says the output does
  not depend on it, and the other parameters of the run its environment takes (the codelet's
  --time, CK's CT_TIME); PolyBench's dump file is compared only when the arrays are dumped, and
  within a relative tolerance (POLYBENCH_TOLERANCE) unless the program gives its own;
- customize_summary: what the run summary says of a CK program (the defines, PolyBench's size, the
  CPU-GPU comparison, the OpenCL device, the output CK redirected).
"""

import os
import re
import shutil

from program_22788f3c30d04e6d.api.cprogram import InitCProgram

# PolyBench's dataset sizes (its header's macros)
SIZES = {'mini': 'MINI_DATASET', 'small': 'SMALL_DATASET', 'standard': 'STANDARD_DATASET',
         'large': 'LARGE_DATASET', 'extralarge': 'EXTRALARGE_DATASET'}

# The precisions a PolyBench program is built with (DATA_TYPE; the printf format follows the type by token pasting)
PRECISIONS = ('float', 'double')

# The defines that say nothing of the program's result: the instrumentation and the platform
NOT_IN_THE_KEY = ('XOPENME', 'WINDOWS')

# A parameter of the run in the program's environment: {{local.params.<name>|<default>}} (CK's run_vars mapped)
ENV_PARAM = re.compile(r'\{\{\s*local\.params\.([A-Za-z0-9_]+)\s*(?:\|([^}]*))?\}\}')

# PolyBench dumps floating-point arrays as text; a reference holds across compilers and architectures within this
# relative tolerance (an absolute floor of the same value), well under a wrong kernel's error. A program overrides
# it with output_check.tolerance in its _desc.yaml.
POLYBENCH_TOLERANCE = 1e-6

# Sources written before C99 (K&R declarations, functions used without a declaration, long for
# time_t): GCC and clang compile them as GNU C89, as they did when the sources were written, with
# what GCC 14 and clang 16 made errors kept as warnings (local_vars: ck_legacy_c). MSVC needs none.
LEGACY_C_FLAGS = ['-std=gnu89',
                  '-Wno-error=implicit-function-declaration',
                  '-Wno-error=implicit-int',
                  '-Wno-error=int-conversion',
                  '-Wno-error=incompatible-pointer-types']


class CProgram(InitCProgram):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def customize2(self,
                   ctx: dict,
                   **misc
    ):
        """The WINDOWS define (a build for the Windows host), GNU C89 for old sources, PolyBench's sizes, precision and dump."""

        _local = ctx['tasks']['local']
        _global = ctx['tasks']['global']

        compute = _global['target']['compute']
        uname = _global['host']['os']['uname']

        _compile = _local['params'].get('compile')
        if not isinstance(_compile, dict):
            _compile = _local['params']['compile'] = {}
        d = _compile.get('d')
        if not isinstance(d, dict):
            d = _compile['d'] = {}

        # Not for a device built on Windows (Android, iPhone): its C library is not Windows'
        if uname == 'windows' and any(c in compute for c in ('cpu', 'cuda', 'opencl')):
            d['WINDOWS'] = None

        if _local.get('ck_legacy_c'):
            compiler = _global.get('compiler-' + str(_local.get('lang') or 'c')) or {}
            msvc_style = str(((compiler.get('features') or {}).get('flags') or {}).get('d', '')).startswith('/')
            if not msvc_style:
                flags = _compile.get('flags') or []
                if isinstance(flags, str):
                    flags = flags.split()
                _compile['flags'] = list(flags) + [f for f in LEGACY_C_FLAGS if f not in flags]

        # PolyBench's sizes, precision and dump: the compile parameters applied to the defines
        r = self._defines(d, _compile, _local.get('ck_size_vars') or [])
        if r['return'] > 0:
            return r

        # PolyBench/GPU: the CPU reference that the CK versions commented out (#ifdef CK_CPU_CHECK in the
        # converted sources), compiled unless --compile.check=no - then the program's "Non-Matching CPU-GPU
        # Outputs" compares the GPU's result with the CPU's
        if _local.get('ck_cpu_check') and self._check(_compile):
            d['CK_CPU_CHECK'] = None

        return {'return':0}

    ############################################################
    def _defines(self, d, _compile, size_vars):
        """
        The defines of a build with the compile parameters applied, in place - and the same whether they were applied
        before or not, since a reused build brings its defines back applied: --compile.size (PolyBench's size macro
        instead of the size defines), --compile.n (every size define = N: square arrays; not with a size),
        --compile.precision (DATA_TYPE, where the program has it), --compile.dump (POLYBENCH_DUMP_ARRAYS kept or
        dropped: yes with CK's sizes, no with a size or an N, unless said).
        """
        n = _compile.get('n')
        if n not in (None, '') and not size_vars:
            return self.cm.error('this program has no array sizes to set (no ck_size_vars): --compile.n does not apply')

        if size_vars:
            size = self._size(_compile)
            if size is False:
                return self.cm.error(f'--compile.size must be one of {", ".join(SIZES)} (got "{_compile.get("size")}")')

            if n not in (None, ''):
                if size:
                    return self.cm.error('--compile.n and --compile.size are two ways to size the arrays: give one of them')
                try:
                    n = int(n)
                except (TypeError, ValueError):
                    n = 0
                if n < 1:
                    return self.cm.error(f'--compile.n takes a positive whole number, the size of every array dimension (got "{_compile.get("n")}")')
                for k in size_vars:
                    d[k] = str(n)
                for macro in SIZES.values():
                    d.pop(macro, None)
            elif size:
                for k in size_vars:
                    d.pop(k, None)
                for macro in SIZES.values():
                    d.pop(macro, None)
                d[SIZES[size]] = None

        precision = _compile.get('precision')
        if precision not in (None, ''):
            if 'DATA_TYPE' not in d:
                return self.cm.error('this program has no DATA_TYPE define: --compile.precision does not apply')
            precision = str(precision).strip().lower()
            if precision not in PRECISIONS:
                return self.cm.error(f'--compile.precision must be one of {", ".join(PRECISIONS)} (got "{_compile.get("precision")}")')
            d['DATA_TYPE'] = precision

        if size_vars and not self._dump(_compile):
            d.pop('POLYBENCH_DUMP_ARRAYS', None)

        return {'return': 0, 'd': d}

    ############################################################
    def _check(self, _compile):
        """Whether the CPU reference is compiled: --compile.check, yes unless it says no."""
        check = _compile.get('check')
        if check is None or str(check).strip() == '':
            return True
        if isinstance(check, bool):
            return check
        return str(check).strip().lower() in ('yes', 'true', 'on', '1')

    ############################################################
    def _size(self, _compile):
        """The PolyBench size asked for: None for CK's sizes, False when it is not one of SIZES."""
        size = str(_compile.get('size') or '').strip().lower()
        if not size or size in ('none', 'ck'):
            return None
        return size if size in SIZES else False

    def _dump(self, _compile):
        """Whether the arrays are dumped: --compile.dump, else yes with CK's sizes and no with --compile.size or --compile.n."""
        dump = _compile.get('dump')
        if dump is None or str(dump).strip() == '':
            return not (self._size(_compile) or _compile.get('n') not in (None, ''))
        if isinstance(dump, bool):
            return dump
        return str(dump).strip().lower() in ('yes', 'true', 'on', '1')

    def _env_params(self, _local):
        """
        The parameters of the run the program's environment takes besides the repeat - {{local.params.<name>|<default>}}
        in run_time_env of its own _desc.yaml (the environment in the context is expanded already) - with their
        defaults: {name: default}. Read from the program's folder; nothing when it cannot be read.
        """
        program = _local.get('selected-program') if isinstance(_local.get('selected-program'), dict) else {}
        path = program.get('path')
        reader = getattr(getattr(getattr(self, 'cm', None), 'utils', None), 'files', None)
        if not path or reader is None or not os.path.isfile(os.path.join(path, '_desc.yaml')):
            return {}
        r = reader.read_file(os.path.join(path, '_desc.yaml'))
        if r.get('return', 1) > 0 or not isinstance(r.get('data'), dict):
            return {}
        env = (r['data'].get('local_vars') or {}).get('run_time_env') or {}
        repeat_param = str(_local.get('repeat_param') or 'repeat')
        out = {}
        for value in env.values() if isinstance(env, dict) else []:
            for m in ENV_PARAM.finditer(str(value)):
                name, default = m.group(1), (m.group(2) or '').strip()
                if name != repeat_param and name not in out:
                    out[name] = default
        return out

    def _repeats(self, _local):
        """Whether the program repeats its kernel: repeat_param of its local_vars, or CK's CT_REPEAT_MAIN in its environment."""
        if _local.get('repeat_param'):
            return True
        env = _local.get('run_time_env')
        if not isinstance(env, dict):
            return False
        return 'CT_REPEAT_MAIN' in env or any('params.repeat' in str(v) for v in env.values())

    ############################################################
    def customize_ck_run(self,
                         ctx: dict,
                         **misc
    ):
        """Prepare the run as CK did: dataset files and number, files in the run folder, outputs."""

        _local = ctx['tasks']['local']
        _global = ctx['tasks']['global']

        compute = _global['target']['compute']
        ios = 'ios-cpu' in compute
        on_device = ios or any(str(c).startswith('android-') for c in compute)   # android-cpu, android-gpu ...

        input_files = _local.get('input_files')
        if not isinstance(input_files, dict):
            input_files = {}
        _local['input_files'] = input_files

        output_files = list(_local.get('output_files') or [])

        dataset = _local.get('dataset') or {}
        dataset_path = dataset.get('path')

        # A number on the command line (CK: $#dataset_number#$)
        if _local.get('ck_number_from_dataset'):
            if dataset.get('number') is not None:
                _local['ck_number'] = str(dataset['number']).strip()
            elif dataset_path and os.path.isfile(dataset_path):
                with open(dataset_path, encoding='utf-8') as f:
                    _local['ck_number'] = f.read().strip()
            else:
                return self.cm.error('this program takes a number from its dataset, but the dataset has none')

        # The other files of the dataset (CK: $#dataset_filename_1#$ ...), in the dataset's order
        if _local.get('ck_dataset_more_files'):
            if not dataset_path:
                return self.cm.error('this program takes several files of its dataset, but no dataset file was selected')

            folder = os.path.dirname(dataset_path)
            files = dataset.get('files') or self._dataset_files(folder) or sorted(os.listdir(folder))

            first = os.path.basename(dataset_path)
            others = [f for f in files if f != first]
            for n, f in enumerate(others, 1):
                input_files[f'data{n}'] = os.path.join(folder, f)

        # Files of the program the run expects in its folder (pgp's key rings): pushed or copied
        # into the device's folder with the input files, copied into the run folder on the host
        run_files = _local.get('ck_run_files') or []
        if run_files:
            src_path = os.path.join(_local['selected-program']['path'], 'src')
            work_path = _local.get('work_path') or os.getcwd()

            for f in run_files:
                src = os.path.join(src_path, f)
                if not os.path.isfile(src):
                    return self.cm.error(f'file "{f}" not found in "{src_path}"')

                if on_device:
                    input_files['ck-' + f] = src
                else:
                    os.makedirs(work_path, exist_ok = True)
                    shutil.copy2(src, os.path.join(work_path, f))

        # The OpenCL platform and device of the program's calls (CK: CK_COMPUTE_PLATFORM_ID and
        # CK_COMPUTE_DEVICE_ID, indexes in the order of clGetPlatformIDs and clGetDeviceIDs)
        if _local.get('ck_opencl_device'):
            r = self._opencl_device(ctx)
            if r['return'] > 0:
                return r
            env = _local.get('run_time_env')
            if not isinstance(env, dict):
                env = _local['run_time_env'] = {}
            env['CK_COMPUTE_PLATFORM_ID'] = str(r['platform'])
            env['CK_COMPUTE_DEVICE_ID'] = str(r['device'])
            _local['ck_opencl'] = r
            if (ctx.get('control') or {}).get('con', False) and r.get('name'):
                print(f'INFO: OpenCL device: {r["name"]} (platform {r["platform"]}, device {r["device"]}; '
                      '--opencl_device=<number or name> chooses another)')

        # An output that exists only when the arrays are dumped (PolyBench)
        dump_file = _local.get('ck_dump_file')
        if dump_file and self._dump((_local.get('params') or {}).get('compile') or {}) and dump_file not in output_files:
            output_files.append(dump_file)

        # Standard output and error into files, as CK did (tmp-output1.tmp, tmp-output2.tmp)
        _local['ck_redirects'] = ''
        if _local.get('ck_redirect_stdio') and not ios:
            _local['ck_redirects'] = '> tmp-output1.tmp 2> tmp-output2.tmp'
            for f in ('tmp-output1.tmp', 'tmp-output2.tmp'):
                if f not in output_files:
                    output_files.append(f)

        _local['output_files'] = output_files

        return {'return':0}

    ############################################################
    def _opencl_device(self, ctx):
        """
        The OpenCL platform and device indexes for a run: --opencl_platform and --opencl_device (numbers),
        or --opencl_device=<a word of the device's name, vendor or platform>, else the first GPU that the
        opencl target found (tool/opencl lists platforms and devices in the order a program gets them).
        """
        params = ctx['tasks']['local'].get('params') or {}
        features = (ctx['tasks']['global'].get('opencl') or {}).get('features') or {}
        platforms = [p.get('name', '') for p in features.get('platforms') or []]

        # (platform index, device index in its platform, device); two platforms of one name take the first's
        listed, count = [], {}
        for d in features.get('devices') or []:
            name = d.get('platform', '')
            if name not in platforms:
                continue
            pi = platforms.index(name)
            listed.append((pi, count.get(pi, 0), d))
            count[pi] = count.get(pi, 0) + 1

        platform, device = params.get('opencl_platform'), params.get('opencl_device')
        word = str(device).strip().lower() if device is not None and not str(device).strip().isdigit() else None
        if word:
            for pi, di, d in listed:
                text = ' '.join(str(d.get(k) or '') for k in ('name', 'vendor', 'platform')).lower()
                if word in text and (platform is None or str(platform) == str(pi)):
                    return {'return': 0, 'platform': pi, 'device': di, 'name': d.get('name')}
            return self.cm.error(f'no OpenCL device matches "{device}": ' +
                                 '; '.join(f'{pi}/{di} {d.get("name")} ({d.get("platform")})' for pi, di, d in listed))
        if platform is not None or device is not None:
            pi, di = int(platform or 0), int(device or 0)
            name = next((d.get('name') for p, i, d in listed if p == pi and i == di), None)
            return {'return': 0, 'platform': pi, 'device': di, 'name': name}

        chosen = next((x for x in listed if x[2].get('type') == 'gpu'), None) or (listed[0] if listed else None)
        if chosen is None:
            return {'return': 0, 'platform': 0, 'device': 0, 'name': None}
        return {'return': 0, 'platform': chosen[0], 'device': chosen[1], 'name': chosen[2].get('name')}

    ############################################################
    def _built_defines(self, _local):
        """
        The defines the program was built with: every one its parameters declare but the instrumentation and the
        platform (NOT_IN_THE_KEY), with the compile parameters applied (size, n, precision, dump) - the same whether
        the build was made now or reused. None for an error.
        """
        params = _local.get('params') if isinstance(_local.get('params'), dict) else {}
        _compile = params.get('compile') if isinstance(params.get('compile'), dict) else {}
        declared = _compile.get('d') if isinstance(_compile.get('d'), dict) else {}
        size_vars = _local.get('ck_size_vars') or []
        d = {str(k): v for k, v in declared.items() if str(k) not in NOT_IN_THE_KEY}
        r = self._defines(d, _compile, size_vars)
        if r['return'] > 0:
            return r
        return {'return': 0, 'd': d}

    ############################################################
    def customize_output_check(self,
                               ctx: dict,
                               rules: dict,
                               **misc
    ):
        """
        What tells the cases of a CK program apart besides its command and input (compile-and-run-program's check
        of the outputs against the reference, --check_output): the defines it was built with (compile.d.<NAME>,
        a valueless define as ''), PolyBench's size and dump (--compile.size, --compile.dump) when the program has
        sizes (ck_size_vars), and the kernel's repeat (--repeat; after a calibration, the one it settled on) when
        the program repeats it, unless output_check.invariant_of_repeat says the output is the same whatever it is.
        """

        _local = ctx['tasks']['local']
        params = _local.get('params') if isinstance(_local.get('params'), dict) else {}
        values = dict(rules.get('key_values') or {})

        r = self._built_defines(_local)
        if r['return'] > 0:
            return r
        for k, v in r['d'].items():
            values[f'compile.d.{k}'] = '' if v is None else str(v)

        if _local.get('ck_size_vars'):
            names = list(rules.get('key_params') or [])
            for name in ('compile.size', 'compile.dump'):
                if name not in names:
                    names.append(name)
            rules['key_params'] = names

            # PolyBench dumps its arrays as floating-point text: the last digits differ between compilers and
            # between architectures (x86 and arm64 round fused multiply-adds differently), so a reference holds
            # across targets only within a tolerance - a relative one that still catches a wrong kernel (those
            # differ by much more). The program's own output_check.tolerance (its _desc.yaml) overrides this.
            if 'tolerance' not in rules:
                rules['tolerance'] = POLYBENCH_TOLERANCE

        if not rules.get('invariant_of_repeat') and self._repeats(_local):
            repeat = params.get('repeat')
            try:
                values['repeat'] = int(repeat) if repeat not in (None, '') else 1
            except (TypeError, ValueError):
                values['repeat'] = str(repeat)

        # The other parameters of the run the program's environment takes ({{local.params.<name>|<default>}}: the
        # codelet's --time=day|night, CK's CT_TIME), with their default when not given
        for name, default in self._env_params(_local).items():
            given = params.get(name)
            values[name] = str(given) if given not in (None, '') else default

        # PolyBench without the dump of its arrays (--compile.dump=no, or a size): its dump file is not compared
        dump_file = _local.get('ck_dump_file')
        compile_params = params.get('compile') if isinstance(params.get('compile'), dict) else {}
        if dump_file and isinstance(rules.get('files'), list) and not self._dump(compile_params):
            rules['files'] = [f for f in rules['files'] if f != dump_file]

        rules['key_values'] = values

        return {'return': 0}

    ############################################################
    def customize_summary(self,
                          ctx: dict,
                          summary: dict,
                          **misc
    ):
        """
        What the summary of a run says of a CK program (compile-and-run-program prints it after the run): the
        defines the program was built with, the comparison of a PolyBench/GPU result with the CPU's, the OpenCL
        device the run used, PolyBench's size, and the standard error that CK's redirect kept, when the run failed.
        """

        _local = ctx['tasks']['local']
        work = summary.get('work_path') or _local.get('work_path') or os.getcwd()

        def text_of(name, last = None):
            path = os.path.join(work, name)
            if not os.path.isfile(path):
                return None
            try:
                with open(path, encoding = 'utf-8', errors = 'replace') as f:
                    text = f.read()
            except OSError:
                return None
            return text if last is None else '\n'.join(text.strip().splitlines()[-last:])

        # The defines of the build: the sizes, the precision, the dump (what the reference outputs are keyed by)
        r = self._built_defines(_local)
        if r['return'] == 0 and r['d']:
            summary.setdefault('lines', []).append('defines:  ' + ', '.join(k if v is None else f'{k}={v}' for k, v in r['d'].items()))

        # PolyBench/GPU: the GPU's result against the CPU's (CK_CPU_CHECK; the program prints the count)
        out = text_of('tmp-output1.tmp') or ''
        m = re.search(r'Non-Matching CPU-GPU Outputs Beyond Error Threshold of ([0-9.]+) Percent: (\d+)', out)
        if m:
            n = int(m.group(2))
            summary.setdefault('checks', []).append({'what': f'GPU results against the CPU\'s (beyond {m.group(1)} %)',
                                                     'ok': n == 0, 'detail': f'{n} values differ' if n else 'none differ'})
        elif _local.get('ck_cpu_check') and summary.get('status') == 'ok':
            summary.setdefault('checks', []).append({'what': 'GPU results against the CPU\'s', 'ok': None,
                                                     'detail': 'no comparison in the output (a build with --compile.check=no?)'})

        # The OpenCL device of the run (customize_ck_run chose it)
        chosen = _local.get('ck_opencl')
        if isinstance(chosen, dict):
            devices = ((ctx['tasks']['global'].get('opencl') or {}).get('features') or {}).get('devices') or []
            d = next((x for x in devices if isinstance(x, dict) and x.get('name') == chosen.get('name')), {})
            extra = ', '.join(str(d.get(k)) for k in ('platform', 'version') if d.get(k))
            if d.get('driver_version'):
                extra += f', driver {d["driver_version"]}'
            summary.setdefault('lines', []).append(f'opencl:   platform {chosen.get("platform")}, device {chosen.get("device")}: '
                                                   f'{chosen.get("name") or "?"}' + (f' ({extra})' if extra else ''))

        # PolyBench: the size of its arrays and whether they were dumped
        if _local.get('ck_size_vars'):
            compile_params = (_local.get('params') or {}).get('compile') or {}
            size = self._size(compile_params) if isinstance(compile_params, dict) else None
            n = compile_params.get('n') if isinstance(compile_params, dict) else None
            dump = self._dump(compile_params) if isinstance(compile_params, dict) else None
            what = f'every dimension {n} (--compile.n)' if n not in (None, '') else (size or 'of CK (the sources\' defines)')
            summary.setdefault('lines', []).append(f'polybench: size {what}, arrays {"dumped" if dump else "not dumped"}')

        # CK's redirects: what the program printed is in files - the summary shows them
        if _local.get('ck_redirects'):
            for stream, name in (('stdout', 'tmp-output1.tmp'), ('stderr', 'tmp-output2.tmp')):
                text = text_of(name)
                if text and text.strip():
                    summary[stream] = {'source': name, 'text': text, 'path': os.path.join(work, name)}

        return {'return': 0}

    ############################################################
    def _dataset_files(self, folder):
        """
        The order of a dataset's files when its result does not give it: "files" of its _desc.yaml, or those of
        the sub-dataset the folder is (files/<sub-dataset>/: "sub_datasets" of the _desc.yaml one level up).
        """

        for up, sub in ((os.path.dirname(folder), None),
                        (os.path.dirname(os.path.dirname(folder)), os.path.basename(folder))):
            path_desc = os.path.join(up, '_desc.yaml')
            if not os.path.isfile(path_desc):
                continue

            r = self.cm.utils.files.read_file(path_desc)
            if r['return'] > 0:
                continue

            data = r.get('data') or {}
            if sub is not None:
                data = (data.get('sub_datasets') or {}).get(sub) if isinstance(data.get('sub_datasets'), dict) else None
                data = data if isinstance(data, dict) else {}
            files = data.get('files')
            if isinstance(files, list):
                return files

        return []
