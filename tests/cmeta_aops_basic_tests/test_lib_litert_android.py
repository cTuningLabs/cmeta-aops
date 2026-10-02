"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/lib-litert-android: the SHA-256 digests of a GitHub release, the layout of
the unpacked runtime, NPU libraries and C SDK, and the lib-* features that setup-compile and
setup-run take from it.
"""

import io
import json
import os
import pathlib
import zipfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope = "module")
def litert():
    path = REPO_ROOT / "tool" / "lib-litert-android" / "api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool",
                                                     "class InitCTool:\n    pass")
    ns = {"__name__": "lib_litert", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def zipped(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_release_digests(litert):
    doc = json.dumps({"assets": [{"name": "litert_cc_sdk.zip", "digest": "sha256:ABC"},
                                 {"name": "notes.txt", "digest": None}]})
    assert litert["release_digests"](doc) == {"litert_cc_sdk.zip": "abc"}


def test_unpack_and_features(litert, tmp_path):
    aar, npu, sdk = tmp_path / "litert.aar", tmp_path / "npu.zip", tmp_path / "sdk.zip"
    aar.write_bytes(zipped({"jni/arm64-v8a/libLiteRt.so": b"ELF", "jni/arm64-v8a/libLiteRtClGlAccelerator.so": b"ELF",
                            "jni/x86_64/libLiteRt.so": b"ELF", "classes.jar": b"PK"}))
    npu.write_bytes(zipped({"google_tensor_runtime/src/main/jni/arm64-v8a/libLiteRtDispatch_GoogleTensor.so": b"ELF",
                            "qualcomm_runtime_v79/src/main/jni/arm64-v8a/libLiteRtDispatch_Qualcomm.so": b"ELF",
                            "fetch_qualcomm_library.sh": b"#!"}))
    sdk.write_bytes(zipped({"litert_cc_sdk/litert/c/litert_common.h": b"//",
                            "litert_cc_sdk/litert/build_common/build_config.h.in":
                                b"#cmakedefine01 LITERT_BUILD_CONFIG_DISABLE_GPU\n#cmakedefine01 LITERT_BUILD_CONFIG_DISABLE_NPU\n"}))
    root = tmp_path / "content" / "2.2.0"
    litert["unpack"](str(aar), str(npu), str(sdk), str(root))
    assert (root / "jni" / "arm64-v8a" / "libLiteRtClGlAccelerator.so").is_file()
    assert (root / "npu" / "google_tensor" / "arm64-v8a" / "libLiteRtDispatch_GoogleTensor.so").is_file()
    assert (root / "npu" / "qualcomm_v79" / "arm64-v8a" / "libLiteRtDispatch_Qualcomm.so").is_file()
    config = (root / "sdk" / "litert_cc_sdk" / "litert" / "build_common" / "build_config.h").read_text()
    assert "#define LITERT_BUILD_CONFIG_DISABLE_GPU 0" in config and "cmakedefine" not in config

    (root / litert["MARKER"]).write_text(json.dumps({"version": "2.2.0", "digests": {}, "model": None}))
    t = litert["CTool"].__new__(litert["CTool"])
    f = t._entry(str(root))["features"]
    assert f["lib_names"] == ["LiteRt"]
    assert f["paths"]["includes"] == [str(root / "sdk" / "litert_cc_sdk")]
    assert sorted(os.path.basename(x) for x in f["paths"]["found_dynamic_libs"]) == [
        "libLiteRt.so", "libLiteRtClGlAccelerator.so", "libLiteRtDispatch_GoogleTensor.so"]     # not Qualcomm's
    assert set(f["npu"]) == {"google_tensor", "qualcomm_v79"} and set(f["jni"]) == {"arm64-v8a", "x86_64"}
