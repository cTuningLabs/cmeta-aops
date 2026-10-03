"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/mpi (which MPI a host gets and how it is installed, the environment of a
launcher, the defaults in the cache identity, the PRRTE byte-order change of the source build),
tool/ray (the exact Python every node needs) and common_pyvenv's "bin" folder for packages whose
programs are not console scripts.
"""

import os
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(rel_path, stubs = ()):
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8").replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool",
                                                     "class InitCTool:\n    pass")
    for line in stubs:
        src = src.replace(line, "")
    ns = {"__name__": "under_test", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


PYVENV_IMPORT = "from tool_c393ba5c6fa14f66.api.common_pyvenv import install_pyvenv"
RELEASE_IMPORT = "from tool_c393ba5c6fa14f66.api.common_release import _download, _sha256"


@pytest.fixture(scope = "module")
def mpi():
    return load("tool/mpi/api_v1.py", [PYVENV_IMPORT, RELEASE_IMPORT])


@pytest.fixture(scope = "module")
def pyvenv():
    return load("category/tool/api/common_pyvenv.py")


def test_which_mpi(mpi):
    impl = mpi["implementation"]
    assert impl("linux")[0] == "openmpi" and impl("darwin")[0] == "openmpi" and impl("windows")[0] == "intel"
    name, spec, error = impl("linux", "MPICH")
    assert (name, spec["package"], error) == ("mpich", "mpich", None)
    assert impl("linux", "intel")[1]["package"] == "impi-rt"
    _, spec, error = impl("windows", "openmpi")
    assert spec is None and "--with.mpi=intel" in error
    _, spec, error = impl("darwin", "intel")
    assert spec is None and "openmpi|mpich" in error
    assert "unknown MPI" in impl("linux", "lam")[2]


def test_the_default_is_in_the_cache_identity(mpi):
    t = mpi["CTool"].__new__(mpi["CTool"])
    for uname, want in (("windows", "intel"), ("linux", "openmpi")):
        params = {}
        t.init({"tasks": {"global": {"host": {"os": {"uname": uname}}}}}, params)
        assert params["with"]["mpi"] == want
    params = {"with": {"mpi": "mpich"}}
    t.init({"tasks": {"global": {"host": {"os": {"uname": "linux"}}}}}, params)
    assert params["with"]["mpi"] == "mpich"


def test_how_it_is_installed(mpi):
    kind = mpi["build_kind"]
    assert kind("darwin", "openmpi") == ("source", None)        # PRRTE's byte order (see the module)
    assert kind("linux", "openmpi") == ("pip", None)
    assert kind("windows", "intel") == ("pip", None) and kind("darwin", "mpich") == ("pip", None)
    assert kind("darwin", "openmpi", "pip") == ("pip", None) and kind("linux", "openmpi", "SOURCE") == ("source", None)
    assert "Open MPI only" in kind("linux", "mpich", "source")[1]
    assert "pip|source" in kind("linux", "openmpi", "conda")[1]


class FakeCM:
    def error(self, text, code = 1, extra = None):
        return {"return": code, "error": text}


def test_the_build_is_in_the_cache_identity(mpi):
    t = mpi["CTool"].__new__(mpi["CTool"])
    t.cm = FakeCM()
    host = lambda uname: {"tasks": {"global": {"host": {"os": {"uname": uname}}}}}
    params = {}
    assert t.init(host("darwin"), params)["return"] == 0
    assert params["with"] == {"mpi": "openmpi", "build": "source"} and params["skip_detect"] is True
    params = {}
    t.init(host("linux"), params)
    assert params["with"] == {"mpi": "openmpi", "build": "pip"} and "skip_detect" not in params
    params = {"with": {"build": "pip"}}
    t.init(host("darwin"), params)
    assert params["with"]["build"] == "pip" and "skip_detect" not in params
    assert t.init(host("linux"), {"with": {"mpi": "intel", "build": "source"}})["return"] > 0


def test_prrte_byte_order(mpi, tmp_path):
    path = tmp_path / "3rd-party" / "prrte" / "src" / "hwloc" / "hwloc_base_util.c"
    path.parent.mkdir(parents = True)
    path.write_text('#ifdef __BYTE_ORDER\n#    if __BYTE_ORDER == __LITTLE_ENDIAN\n    endian = "le";\n'
                    '#    else\n    endian = "be";\n#    endif\n#else\n    endian = "unknown";\n#endif\n')
    assert mpi["fix_prrte_byte_order"](str(tmp_path)) is True
    text = path.read_text()
    assert "#elif defined(__BYTE_ORDER__) && defined(__ORDER_LITTLE_ENDIAN__)" in text
    assert text.index("__ORDER_LITTLE_ENDIAN__") < text.index('endian = "unknown"')
    assert mpi["fix_prrte_byte_order"](str(tmp_path)) is False          # once only
    assert mpi["fix_prrte_byte_order"](str(tmp_path / "none")) is False


def test_the_environment_of_a_launcher(mpi, tmp_path):
    venv = tmp_path / "venv"
    (venv / "Library" / "bin").mkdir(parents = True)
    (venv / "pyvenv.cfg").write_text("home = x")
    assert mpi["venv_root"](str(venv / "Library" / "bin" / "mpiexec.exe")) == str(venv)
    assert mpi["venv_root"](str(tmp_path / "usr" / "bin" / "mpiexec")) is None


def test_ray_pins_the_python_patch():
    ray = load("tool/ray/api_v1.py", [PYVENV_IMPORT])
    assert len(ray["SPEC"]["python"].split(".")) == 3          # 3.12.3 and 3.12.14 cannot share a cluster
    assert ray["SPEC"]["package"].startswith("ray[default]")


class FakeCM:
    def __init__(self):
        self.commands = []

        class Sys:
            @staticmethod
            def run(command, **kw):
                self.commands.append(command)
                return {"return": 0, "returncode": 0}

        class Utils:
            sys = Sys

        self.utils = Utils

    def access(self, ii):
        return {"return": 0, "tool_path": "uv"}

    def catch_error(self, r, fail16 = False):
        return r["return"] > 0 and (r["return"] != 16 or fail16)

    def error(self, text):
        return {"return": 1, "error": text}


def test_pyvenv_bin_folder(pyvenv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "venv" / "Scripts").mkdir(parents = True)
    (tmp_path / "venv" / "Scripts" / "python.exe").write_text("")
    (tmp_path / "venv" / "Library" / "bin").mkdir(parents = True)
    (tmp_path / "venv" / "Library" / "bin" / "mpiexec.exe").write_text("")
    tool = type("T", (), {})()
    tool.cm = FakeCM()
    ctx = {"tasks": {"nested_call": 0, "global": {"host": {"os": {"uname": "windows"}, "vars": {"file_ext_exe": ".exe"}},
                                                  "uv": {"qpath": "uv"}}}}
    spec = {"name": "mpiexec", "package": "impi-rt", "default_version": "2021.18.1", "python": "3.12",
            "extra": ["mpi4py==4.1.2"], "bin": {"windows": "Library/bin"}}
    r = pyvenv["install_pyvenv"](tool, ctx, {"control": {}}, None, spec)
    assert r["return"] == 0 and r["found_path"] == os.path.join(str(tmp_path), "venv", "Library", "bin", "mpiexec.exe")
    assert any('"impi-rt==2021.18.1" "mpi4py==4.1.2"' in c for c in tool.cm.commands)
    # without "bin", the command is a console script in Scripts (missing here)
    r = pyvenv["install_pyvenv"](tool, ctx, {"control": {}}, None, dict(spec, bin = None))
    assert r["return"] == 1 and "Scripts" in r["error"]
