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
                    defines (CK's sizes) by the header's size macro; --compile.dump=yes|no keeps or
                    drops POLYBENCH_DUMP_ARRAYS (default: yes with CK's sizes, no with --compile.size).
                    Both are compile parameters, so each choice is a build of its own;
- customize_ck_run (run, after the dataset step):
  ck_number_from_dataset  the dataset is a number for the command line ({{local.ck_number}}): the
                          "number" of its result, else the content of its file;
  ck_dataset_more_files   the other files of the dataset, in its order ("files" of its result), as the
                          input files data1, data2 ... ({qinput_files.data1});
  ck_run_files            files of the program (src/) the run expects in its working folder;
  ck_dump_file            an output that exists only when the arrays are dumped (PolyBench);
  ck_redirect_stdio       standard output and error into tmp-output1.tmp and tmp-output2.tmp
                          ({{local.ck_redirects}}; not on iOS, where an app has no redirection).
"""

import os
import shutil

from program_22788f3c30d04e6d.api.cprogram import InitCProgram

# PolyBench's dataset sizes (its header's macros)
SIZES = {'mini': 'MINI_DATASET', 'small': 'SMALL_DATASET', 'standard': 'STANDARD_DATASET',
         'large': 'LARGE_DATASET', 'extralarge': 'EXTRALARGE_DATASET'}

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
        """The WINDOWS define (a build for the Windows host), GNU C89 for old sources, PolyBench's sizes and dump."""

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
        if uname == 'windows' and any(c in compute for c in ('cpu', 'cuda')):
            d['WINDOWS'] = None

        if _local.get('ck_legacy_c'):
            compiler = _global.get('compiler-' + str(_local.get('lang') or 'c')) or {}
            msvc_style = str(((compiler.get('features') or {}).get('flags') or {}).get('d', '')).startswith('/')
            if not msvc_style:
                flags = _compile.get('flags') or []
                if isinstance(flags, str):
                    flags = flags.split()
                _compile['flags'] = list(flags) + [f for f in LEGACY_C_FLAGS if f not in flags]

        size_vars = _local.get('ck_size_vars')
        if size_vars:
            size = self._size(_compile)
            if size is False:
                return self.cm.error(f'--compile.size must be one of {", ".join(SIZES)} (got "{_compile.get("size")}")')
            if size:
                for k in size_vars:
                    d.pop(k, None)
                d[SIZES[size]] = None
            if not self._dump(_compile):
                d.pop('POLYBENCH_DUMP_ARRAYS', None)

        return {'return':0}

    ############################################################
    def _size(self, _compile):
        """The PolyBench size asked for: None for CK's sizes, False when it is not one of SIZES."""
        size = str(_compile.get('size') or '').strip().lower()
        if not size or size in ('none', 'ck'):
            return None
        return size if size in SIZES else False

    def _dump(self, _compile):
        """Whether the arrays are dumped: --compile.dump, else yes with CK's sizes and no with --compile.size."""
        dump = _compile.get('dump')
        if dump is None or str(dump).strip() == '':
            return not self._size(_compile)
        if isinstance(dump, bool):
            return dump
        return str(dump).strip().lower() in ('yes', 'true', 'on', '1')

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
        on_device = ios or 'android-cpu' in compute

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
    def _dataset_files(self, folder):
        """The order of a dataset's files when its result does not give it: "files" of its _desc.yaml."""

        path_desc = os.path.join(os.path.dirname(folder), '_desc.yaml')
        if not os.path.isfile(path_desc):
            return []

        r = self.cm.utils.files.read_file(path_desc)
        if r['return'] > 0:
            return []

        files = (r.get('data') or {}).get('files')
        return files if isinstance(files, list) else []
