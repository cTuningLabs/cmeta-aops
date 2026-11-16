"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of what a C program needs for the opencl target: tool/lib-opencl (the Khronos headers and the library
to link: the files of the release archives, OpenCL.lib made by the compiler's archiver, the ICD loader on Linux, the
device targets it refuses), the OpenCL device of template-ck-program's hooks (CK_COMPUTE_PLATFORM_ID and
CK_COMPUTE_DEVICE_ID), and the run-time libraries that take the opencl target (lib-xopenme, lib-polybench).
"""

import io
import json
import os
import pathlib
import tarfile
from types import SimpleNamespace

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(rel, drop = (), names = None):
    """A hook file's code with some import lines dropped and their names given."""
    path = ROOT / rel
    src = path.read_text(encoding = 'utf-8')
    for line in drop:
        assert line in src, line
        src = src.replace(line, '')
    ns = dict(names or {}, __name__ = 'opencl_test', __file__ = str(path))
    exec(compile(src, str(path), 'exec'), ns)
    return ns


@pytest.fixture(scope = 'module')
def lib():
    release = load('category/tool/api/common_release.py')
    static = load('category/tool/api/common_static_lib.py',
                  ['from tool_c393ba5c6fa14f66.api.common_release import _sha256, default_version'],
                  {'_sha256': release['_sha256'], 'default_version': release['default_version']})
    return load('tool/lib-opencl/api_v1.py',
                ['from tool_c393ba5c6fa14f66.api.ctool import InitCTool',
                 'from tool_c393ba5c6fa14f66.api.common_release import _sha256, default_version',
                 'from tool_c393ba5c6fa14f66.api.common_static_lib import download, safe_members, c_compiler'],
                {'InitCTool': object, '_sha256': release['_sha256'], 'default_version': release['default_version'],
                 'download': static['download'], 'safe_members': static['safe_members'], 'c_compiler': static['c_compiler']})


def tool(ns):
    t = ns['CTool'].__new__(ns['CTool'])
    t.cm = SimpleNamespace(q = lambda s: s, error = lambda msg: {'return': 1, 'error': msg})
    return t


def archive(path, files):
    with tarfile.open(path, 'w:gz') as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return str(path)


def test_headers_definitions_and_licences_come_out_of_the_release_archives(lib, tmp_path):
    a = archive(tmp_path / 'h.tar.gz', {'OpenCL-Headers-1/CL/cl.h': b'/* cl */', 'OpenCL-Headers-1/CL/cl_platform.h': b'',
                                        'OpenCL-Headers-1/LICENSE': b'Apache', '../evil.h': b'x',
                                        'OpenCL-Headers-1/tests/x.c': b''})
    dest = tmp_path / 'include' / 'CL'
    assert lib['extract'](a, 'OpenCL-Headers-1/CL/', str(dest)) == 2
    assert sorted(os.listdir(dest)) == ['cl.h', 'cl_platform.h']
    assert not (tmp_path / 'evil.h').exists()
    assert lib['extract_file'](a, 'OpenCL-Headers-1/LICENSE', str(tmp_path / 'LICENSE')) is True
    assert (tmp_path / 'LICENSE').read_bytes() == b'Apache'
    assert lib['extract_file'](a, 'OpenCL-Headers-1/missing', str(tmp_path / 'missing')) is False


def test_the_import_library_is_made_by_the_compilers_archiver(lib, tmp_path):
    msvc = {'path': r'C:\VS\bin\cl.exe', 'features': {'paths': {'tool_lib': r'C:\VS\bin\lib.exe'}}}
    args, error = lib['import_lib_args'](msvc, 'OpenCL.def', 'OpenCL.lib', 'x64')
    assert error is None
    assert args == [r'C:\VS\bin\lib.exe', '/nologo', '/def:OpenCL.def', '/name:OpenCL.dll', '/machine:x64', '/out:OpenCL.lib']

    (tmp_path / 'clang.exe').write_text('')
    clang = {'path': str(tmp_path / 'clang.exe'), 'features': {'paths': {'tool_lib': str(tmp_path / 'llvm-ar.exe')}}}
    args, error = lib['import_lib_args'](clang, 'OpenCL.def', 'OpenCL.lib', 'arm64')
    assert args is None and 'llvm-lib.exe' in error
    (tmp_path / 'llvm-lib.exe').write_text('')
    args, error = lib['import_lib_args'](clang, 'OpenCL.def', 'OpenCL.lib', 'arm64')
    assert error is None and args[0] == str(tmp_path / 'llvm-lib.exe') and '/machine:arm64' in args


def test_the_linux_loader_is_the_probed_one_else_the_first_found(lib, tmp_path):
    probed = tmp_path / 'probed' / 'libOpenCL.so.1'
    probed.parent.mkdir()
    probed.write_text('')
    assert lib['linux_loader'](str(probed), []) == str(probed)
    assert lib['linux_loader'](str(tmp_path / 'other.so'), []) is None

    d1, d2 = tmp_path / 'a', tmp_path / 'b'
    d1.mkdir()
    d2.mkdir()
    (d1 / 'libOpenCL.so.1').write_text('')
    assert lib['linux_loader'](None, [str(d1), str(d2)]) == str(d1 / 'libOpenCL.so.1')
    (d2 / 'libOpenCL.so').write_text('')
    assert lib['linux_loader'](None, [str(d1), str(d2)]) == str(d2 / 'libOpenCL.so')


def test_an_installation_gives_the_include_folder_and_the_import_library(lib, tmp_path):
    install = tmp_path / 'install'
    (install / 'include' / 'CL').mkdir(parents = True)
    (install / 'include' / 'CL' / 'cl.h').write_text('')
    (install / '_source.json').write_text(json.dumps({'version': '2026.05.29'}))
    t = tool(lib)

    r = t.detect_versions({}, [str(install / 'include' / 'CL' / 'cl.h')])
    found = r['found_paths_with_versions'][str(install / 'include' / 'CL' / 'cl.h')]
    assert found['output'] == '2026.05.29'
    assert found['features']['paths']['includes'] == [str(install / 'include')]
    assert 'lib_names' not in found['features']

    (install / 'lib').mkdir()
    (install / 'lib' / 'OpenCL.lib').write_text('')
    r = t.detect_versions({}, [str(install / 'include' / 'CL' / 'cl.h')])
    found = r['found_paths_with_versions'][str(install / 'include' / 'CL' / 'cl.h')]
    assert found['features']['lib_names'] == [str(install / 'lib' / 'OpenCL.lib')]


def test_the_library_to_link_is_found_at_each_use_and_device_targets_are_refused(lib, tmp_path):
    t = tool(lib)
    loader = tmp_path / 'libOpenCL.so.1'
    loader.write_text('')

    def ctx(uname, compute, opencl_path = None):
        return {'tasks': {'global': {'host': {'os': {'uname': uname}}, 'target': {'compute': compute},
                                     'opencl': {'path': opencl_path}}}}

    result = {'return': 0, 'features': {'paths': {}}}
    assert t.finish_dynamic_result(ctx('linux', ['opencl'], str(loader)), result, {})['return'] == 0
    assert result['features']['lib_names'] == [str(loader)]

    result = {'return': 0, 'features': {'paths': {}, 'lib_names': ['OpenCL.lib']}}
    assert t.finish_dynamic_result(ctx('windows', ['opencl']), result, {})['return'] == 0
    assert result['features']['lib_names'] == ['OpenCL.lib']

    r = t.finish_dynamic_result(ctx('darwin', ['ios-gpu']), {'return': 0}, {})
    assert r['return'] == 1 and 'iOS has no OpenCL' in r['error']


def test_an_android_target_links_a_stub_made_from_the_loaders_export_list(lib, tmp_path, monkeypatch):
    text, n = lib['stub_source']('EXPORTS\n\nclBuildProgram\n; a comment\nclGetPlatformIDs @2\nclBuildProgram\nNotOpenCL\n')
    assert n == 2
    assert 'void clBuildProgram(void) {}' in text and 'void clGetPlatformIDs(void) {}' in text and 'NotOpenCL' not in text

    install = tmp_path / 'install'
    (install / 'lib').mkdir(parents = True)
    (install / 'lib' / 'OpenCL.def').write_text('EXPORTS\nclGetPlatformIDs\nclGetDeviceIDs\n')
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        out = args[args.index('-o') + 1]
        pathlib.Path(out).write_text('ELF')
        return SimpleNamespace(returncode = 0, stdout = '', stderr = '')

    monkeypatch.setitem(lib, 'subprocess', SimpleNamespace(run = run, DEVNULL = None))
    t = tool(lib)
    ctx = {'tasks': {'global': {'host': {'os': {'uname': 'windows'}}, 'target': {'compute': ['android-gpu']},
                                'compiler-c': {'path': r'C:\ndk\clang.exe'},
                                'android-ndk-clang': {'features': {'target_arch': {
                                    'clang_target': 'aarch64-linux-android35', 'flags': '-target aarch64-linux-android35'}}}}}}
    result = {'return': 0, 'features': {'paths': {'root': str(install)}}}
    assert t.finish_dynamic_result(ctx, result, {})['return'] == 0
    stub = install / 'android' / 'aarch64-linux-android35' / 'libOpenCL.so'
    assert result['features']['lib_names'] == [str(stub)] and stub.is_file()
    assert calls[0][:3] == [r'C:\ndk\clang.exe', '-target', 'aarch64-linux-android35']
    assert '-Wl,-soname,libOpenCL.so' in calls[0]
    assert 'void clGetDeviceIDs(void) {}' in (stub.parent / 'opencl_stub.c').read_text()

    # Built once: the next use takes it as it is
    assert t.finish_dynamic_result(ctx, {'return': 0, 'features': {'paths': {'root': str(install)}}}, {})['return'] == 0
    assert len(calls) == 1

    # Without the NDK compiler of the program: a clear error
    del ctx['tasks']['global']['android-ndk-clang']
    r = t.finish_dynamic_result(ctx, {'return': 0, 'features': {'paths': {'root': str(tmp_path / 'other')}}}, {})
    assert r['return'] == 1 and 'NDK' in r['error']


def test_the_default_release_is_pinned_for_both_archives(lib):
    desc = yaml.safe_load((ROOT / 'tool' / 'lib-opencl' / '_desc.yaml').read_text(encoding = 'utf-8'))
    version = desc['default_version']
    assert len(lib['HEADERS']['sha256'][version]) == 64
    assert len(lib['LOADER']['sha256'][version]) == 64


# template-ck-program: the OpenCL device of a run

@pytest.fixture(scope = 'module')
def ck():
    return load('program/template-ck-program/api_v1.py',
                ['from program_22788f3c30d04e6d.api.cprogram import InitCProgram'], {'InitCProgram': object})


def hooks(ns):
    h = ns['CProgram'].__new__(ns['CProgram'])
    h.cm = SimpleNamespace(error = lambda msg: {'return': 1, 'error': msg})
    return h


# The platforms and devices as tool/opencl lists them (in the order a program gets them)
LAPTOP = {'platforms': [{'name': 'NVIDIA CUDA'}, {'name': 'Intel(R) OpenCL'}, {'name': 'Intel(R) OpenCL Graphics'}],
          'devices': [{'name': 'NVIDIA RTX PRO 1000 Blackwell', 'type': 'gpu', 'vendor': 'nvidia', 'platform': 'NVIDIA CUDA'},
                      {'name': 'Intel(R) Core(TM) Ultra 9', 'type': 'cpu', 'vendor': 'intel', 'platform': 'Intel(R) OpenCL'},
                      {'name': 'Intel(R) Graphics', 'type': 'gpu', 'vendor': 'intel', 'platform': 'Intel(R) OpenCL Graphics'}]}


def context(params = None, features = LAPTOP, compute = ('opencl',), uname = 'windows'):
    return {'tasks': {'global': {'target': {'compute': list(compute)}, 'host': {'os': {'uname': uname}},
                                 'opencl': {'features': features}, 'compiler-c': {'features': {'flags': {'d': '/D'}}}},
                      'local': {'lang': 'c', 'params': dict(params or {}), 'ck_opencl_device': True}}}


def test_the_opencl_device_is_the_first_gpu_or_the_one_asked_for(ck):
    h = hooks(ck)
    assert h._opencl_device(context()) == {'return': 0, 'platform': 0, 'device': 0, 'name': 'NVIDIA RTX PRO 1000 Blackwell'}
    assert h._opencl_device(context({'opencl_device': 'graphics'}))['platform'] == 2
    assert h._opencl_device(context({'opencl_device': 'Intel'}))['platform'] == 1
    assert h._opencl_device(context({'opencl_device': 'intel', 'opencl_platform': 2}))['platform'] == 2
    assert h._opencl_device(context({'opencl_platform': 1, 'opencl_device': 0}))['name'] == 'Intel(R) Core(TM) Ultra 9'
    r = h._opencl_device(context({'opencl_device': 'amd'}))
    assert r['return'] == 1 and 'NVIDIA RTX PRO 1000 Blackwell' in r['error']

    # A CPU device only (allow_cpu): that one; nothing found: 0 and 0, the program's own default
    cpu_only = {'platforms': [{'name': 'Portable Computing Language'}],
                'devices': [{'name': 'cpu-haswell', 'type': 'cpu', 'platform': 'Portable Computing Language'}]}
    assert h._opencl_device(context(features = cpu_only))['name'] == 'cpu-haswell'
    assert h._opencl_device(context(features = {}))['platform'] == 0


def test_the_run_gets_cks_platform_and_device_variables(ck):
    h = hooks(ck)
    ctx = context({'opencl_device': 'graphics'})
    assert h.customize_ck_run(ctx)['return'] == 0
    env = ctx['tasks']['local']['run_time_env']
    assert env == {'CK_COMPUTE_PLATFORM_ID': '2', 'CK_COMPUTE_DEVICE_ID': '0'}


def test_an_opencl_build_on_windows_gets_the_windows_define(ck):
    h = hooks(ck)
    ctx = context()
    assert h.customize2(ctx)['return'] == 0
    assert ctx['tasks']['local']['params']['compile']['d'] == {'WINDOWS': None}

    # An Android GPU build on a Windows host: not Windows' C library
    ctx = context(compute = ('android-gpu',))
    assert h.customize2(ctx)['return'] == 0
    assert ctx['tasks']['local']['params']['compile']['d'] == {}


def test_the_cpu_reference_is_compiled_unless_check_is_no(ck):
    h = hooks(ck)
    for check, defined in ((None, True), ('yes', True), (True, True), ('no', False), (False, False), ('', True)):
        ctx = context(compute = ('cuda',), uname = 'linux')
        ctx['tasks']['local']['ck_cpu_check'] = True
        if check is not None:
            ctx['tasks']['local']['params']['compile'] = {'check': check}
        assert h.customize2(ctx)['return'] == 0
        assert ('CK_CPU_CHECK' in ctx['tasks']['local']['params']['compile']['d']) is defined, check

    # A program without ck_cpu_check: nothing
    ctx = context(compute = ('cuda',), uname = 'linux')
    assert h.customize2(ctx)['return'] == 0
    assert 'CK_CPU_CHECK' not in ctx['tasks']['local']['params']['compile']['d']


def test_the_files_of_a_run_are_pushed_to_an_android_gpu_device(ck, tmp_path):
    h = hooks(ck)
    program = tmp_path / 'program'
    (program / 'src').mkdir(parents = True)
    (program / 'src' / 'gemm.cl').write_text('__kernel void k() {}')
    ctx = context(compute = ('android-gpu',))
    ctx['tasks']['local'].update({'ck_run_files': ['gemm.cl'], 'work_path': str(tmp_path / 'not-made'),
                                  'selected-program': {'path': str(program)}})
    assert h.customize_ck_run(ctx)['return'] == 0
    assert ctx['tasks']['local']['input_files'] == {'ck-gemm.cl': str(program / 'src' / 'gemm.cl')}
    assert not (tmp_path / 'not-made').exists()


@pytest.mark.parametrize('name', ['lib-xopenme', 'lib-polybench'])
def test_the_runtime_libraries_take_the_opencl_target(name):
    meta = json.loads((ROOT / 'program' / name / '_cmeta.json').read_text(encoding = 'utf-8'))
    assert 'opencl' in meta['constraints']['supported_compute']

    ns = load(f'program/{name}/api_v1.py', ['from program_22788f3c30d04e6d.api.cprogram import InitCProgram'],
              {'InitCProgram': object})
    p = ns['CProgram'].__new__(ns['CProgram'])
    for compute, uname, defined in ((['opencl'], 'windows', True), (['opencl'], 'linux', False),
                                    (['android-cpu'], 'windows', False), (['cpu'], 'windows', True)):
        ctx = {'tasks': {'global': {'target': {'compute': compute}, 'host': {'os': {'uname': uname}}},
                         'local': {'params': {'compile': {}}}}}
        assert p.customize2(ctx)['return'] == 0
        assert ('WINDOWS' in ctx['tasks']['local']['params']['compile'].get('d', {})) is defined
