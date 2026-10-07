"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

tool/node-js: the release asset per OS and CPU, the digest looked up in SHASUMS256.txt, and the unpacking of a
release archive without its top folder (a .tar.gz and a .zip made here). Offline.
"""

import io
import os
import tarfile
import zipfile

import pytest


@pytest.fixture(scope="module")
def node(task_namespace):
    return task_namespace("../tool/node-js")


def load_node():
    import importlib.util
    import pathlib
    import sys
    import types
    # the hook imports the tool category's base class: a stand-in is enough for the helpers
    stub = types.ModuleType("tool_c393ba5c6fa14f66.api.ctool")
    stub.InitCTool = type("InitCTool", (), {"__init__": lambda self, *a, **k: None})
    pkg = types.ModuleType("tool_c393ba5c6fa14f66"); api = types.ModuleType("tool_c393ba5c6fa14f66.api")
    saved = {k: sys.modules.get(k) for k in ("tool_c393ba5c6fa14f66", "tool_c393ba5c6fa14f66.api", "tool_c393ba5c6fa14f66.api.ctool")}
    sys.modules.update({"tool_c393ba5c6fa14f66": pkg, "tool_c393ba5c6fa14f66.api": api, "tool_c393ba5c6fa14f66.api.ctool": stub})
    try:
        fp = pathlib.Path(__file__).resolve().parents[2] / "tool" / "node-js" / "api_v1.py"
        spec = importlib.util.spec_from_file_location("node_js_under_test", str(fp))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return module


def test_the_asset_per_os_and_cpu():
    m = load_node()
    assert m.asset_name("24.21.0", "linux", "amd64") == "node-v24.21.0-linux-x64.tar.gz"
    assert m.asset_name("24.21.0", "linux", "arm64") == "node-v24.21.0-linux-arm64.tar.gz"
    assert m.asset_name("24.21.0", "darwin", "arm64") == "node-v24.21.0-darwin-arm64.tar.gz"
    assert m.asset_name("24.21.0", "windows", "amd64") == "node-v24.21.0-win-x64.zip"
    assert m.asset_name("24.21.0", "freebsd", "amd64") is None
    assert m.DEFAULT_VERSION.count(".") == 2


def test_the_digest_comes_from_the_release_list():
    m = load_node()
    sums = "abc123  node-v24.21.0-linux-x64.tar.gz\nDEF456  node-v24.21.0-win-x64.zip\n"
    assert m.expected_digest(sums, "node-v24.21.0-win-x64.zip") == "def456"
    assert m.expected_digest(sums, "node-v24.21.0-darwin-arm64.tar.gz") == ""


def test_an_archive_is_unpacked_without_its_top_folder(tmp_path):
    m = load_node()
    # a tar.gz as nodejs.org lays it out
    tgz = tmp_path / "node-v1.0.0-linux-x64.tar.gz"
    with tarfile.open(tgz, "w:gz") as t:
        for name, data, mode in (("node-v1.0.0-linux-x64/bin/node", b"#!/bin/sh\necho node\n", 0o755),
                                 ("node-v1.0.0-linux-x64/lib/node_modules/npm/bin/npm-cli.js", b"// npm\n", 0o644)):
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = mode
            t.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("node-v1.0.0-linux-x64/bin/npm"); link.type = tarfile.SYMTYPE; link.linkname = "../lib/node_modules/npm/bin/npm-cli.js"
        t.addfile(link)
    dest = tmp_path / "content"
    m.unpack_stripped(str(tgz), str(dest))
    assert (dest / "bin" / "node").read_bytes().startswith(b"#!/bin/sh") and (dest / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js").is_file()
    assert (dest / "bin" / "npm").exists()                       # the symlink, or a copy where links cannot be made
    if os.name != "nt":
        assert os.access(dest / "bin" / "node", os.X_OK)
    # a zip as nodejs.org lays it out for Windows
    z = tmp_path / "node-v1.0.0-win-x64.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("node-v1.0.0-win-x64/node.exe", b"MZ")
        zf.writestr("node-v1.0.0-win-x64/npm.cmd", b"@echo npm")
        zf.writestr("node-v1.0.0-win-x64/node_modules/npm/bin/npm-cli.js", b"// npm")
    dest2 = tmp_path / "content2"
    m.unpack_stripped(str(z), str(dest2))
    assert (dest2 / "node.exe").read_bytes() == b"MZ" and (dest2 / "npm.cmd").is_file() and (dest2 / "node_modules" / "npm" / "bin" / "npm-cli.js").is_file()
