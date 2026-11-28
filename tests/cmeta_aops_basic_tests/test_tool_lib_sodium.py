"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/lib-sodium, tool/lib-sodium-android and tool/libc-static, and of fetch_pinned
(category/tool/api/common_release.py), with stand-ins for cMeta, the network, the compiler and adb:

- a release file of a tool's "release:" block: its pinned SHA-256 decides, a mirror is tried, a kept
  file is reused when it is right and fetched again when it is not, a version without a pin is refused;
- lib-sodium: what a program links from an unpacked MSVC package (the oldest toolset unless one is
  named, a toolset the package does not have refused) and from a prefix (the static library by its
  path with what it needs, the shared one by name), and the facts of its _desc.yaml;
- lib-sodium-android: the clang target (the block's API level, else the NDK's lowest above it), the
  sources without the skipped folders, the ABI from the device or from --with.abi, the shared library
  named for the device only for a dynamic build; both tools pin one source release;
- libc-static: the compiler's answer decides, a repository that is off by default is enabled for the
  install on the distributions that need it, and its key keeps it out of the link.
"""

import hashlib
import os
import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CTOOL = "from tool_c393ba5c6fa14f66.api.ctool import InitCTool"


def load(rel_path, imports):
    """The module's namespace, with its cMeta imports replaced."""
    path = REPO_ROOT / rel_path
    src = path.read_text(encoding = "utf-8")
    for line, replacement in imports.items():
        assert line in src, line
        src = src.replace(line, replacement)
    ns = {"__name__": path.stem, "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def desc(tool):
    return yaml.safe_load((REPO_ROOT / "tool" / tool / "_desc.yaml").read_text(encoding = "utf-8"))


class CM:
    def error(self, text):
        return {"return": 1, "error": text}

    def q(self, path):
        return f'"{path}"'


class Tool:
    """A tool object as the hooks see it: cMeta and the tool's own description."""

    def __init__(self, name):
        self.cm, self.cdesc = CM(), desc(name)


def ctx(**known):
    return {"control": {"con": False}, "tasks": {"global": dict(known), "local": {}, "nested_call": 0}}


@pytest.fixture(scope = "module")
def release():
    return load("category/tool/api/common_release.py", {})


@pytest.fixture(scope = "module")
def sodium():
    return load("tool/lib-sodium/api_v1.py",
                {CTOOL: "class InitCTool: pass",
                 "from tool_c393ba5c6fa14f66.api.common_release import fetch_pinned": "fetch_pinned = None",
                 "from tool_c393ba5c6fa14f66.api.common_static_lib import c_compiler": "c_compiler = None"})


@pytest.fixture(scope = "module")
def android():
    return load("tool/lib-sodium-android/api_v1.py",
                {CTOOL: "class InitCTool: pass",
                 "from tool_c393ba5c6fa14f66.api.common_release import fetch_pinned": "fetch_pinned = None",
                 "from tool_c393ba5c6fa14f66.api.common_static_lib import object_name, safe_members":
                     "object_name = safe_members = None"})


@pytest.fixture(scope = "module")
def libc():
    return load("tool/libc-static/api_v1.py",
                {CTOOL: "class InitCTool: pass",
                 "from tool_c393ba5c6fa14f66.api.common_static_lib import c_compiler": "c_compiler = None"})


def touch(path, text = "x"):
    os.makedirs(os.path.dirname(path), exist_ok = True)
    with open(path, "w", encoding = "utf-8") as f:
        f.write(text)
    return str(path)


############################################################
# fetch_pinned

CONTENT = b"the bytes of a release file"
DIGEST = hashlib.sha256(CONTENT).hexdigest()
BLOCK = {"urls": ["https://first.example/{version}/{file}", "https://mirror.example/{file}"],
         "files": {"source": "thing-{version}.tar.gz"},
         "sha256": {"1.2.3": {"source": DIGEST}}}


def fetching(release, monkeypatch, tmp_path, serve):
    """fetch_pinned in tmp_path with a download that writes what `serve` gives for a URL (None: it fails)."""
    asked = []

    def download(tool, c, params, url, directory, filename):
        asked.append(url)
        data = serve(url)
        if data is None:
            return {"return": 1, "error": "not reachable"}
        path = os.path.join(os.getcwd(), directory, filename)
        os.makedirs(os.path.dirname(path), exist_ok = True)
        with open(path, "wb") as f:
            f.write(data)
        return {"return": 0, "path": path}

    monkeypatch.setitem(release, "_download", download)
    monkeypatch.chdir(tmp_path)

    def fetch(version = "1.2.3", **with_):
        return release["fetch_pinned"](Tool("lib-sodium"), ctx(), {"with": with_}, BLOCK, "source", version)

    return fetch, asked


def test_a_release_file_is_taken_when_its_digest_is_the_pinned_one(release, monkeypatch, tmp_path):
    fetch, asked = fetching(release, monkeypatch, tmp_path, lambda url: CONTENT)

    r = fetch()
    assert r["return"] == 0 and r["sha256"] == DIGEST and r["url"] == "https://first.example/1.2.3/thing-1.2.3.tar.gz"
    assert pathlib.Path(r["path"]).read_bytes() == CONTENT

    # a second call keeps the file: nothing is asked again
    assert fetch()["return"] == 0 and len(asked) == 1


def test_a_mirror_is_tried_and_a_wrong_file_never_stays(release, monkeypatch, tmp_path):
    fetch, asked = fetching(release, monkeypatch, tmp_path, lambda url: CONTENT if "mirror" in url else None)
    r = fetch()
    assert r["return"] == 0 and "mirror.example" in r["url"] and len(asked) == 2

    # a kept file with other bytes is fetched again
    pathlib.Path(r["path"]).write_bytes(b"changed")
    assert fetch()["return"] == 0 and pathlib.Path(r["path"]).read_bytes() == CONTENT

    (tmp_path / "other").mkdir()
    fetch, asked = fetching(release, monkeypatch, tmp_path / "other", lambda url: b"not the release")
    r = fetch()
    assert r["return"] == 1 and "SHA-256" in r["error"] and len(asked) == 2
    assert not (tmp_path / "other" / "download" / "thing-1.2.3.tar.gz").exists()


def test_a_version_without_a_pin_needs_its_digest(release, monkeypatch, tmp_path):
    fetch, asked = fetching(release, monkeypatch, tmp_path, lambda url: CONTENT)

    r = fetch("9.9.9")
    assert r["return"] == 1 and "--with.sha256" in r["error"] and "1.2.3" in r["error"] and asked == []

    assert fetch("9.9.9", sha256 = DIGEST.upper())["return"] == 0


############################################################
# lib-sodium

def msvc_package(home, toolsets, kinds = ("static", "dynamic")):
    for toolset in toolsets:
        for kind in kinds:
            touch(home / "x64" / "Release" / toolset / kind / "libsodium.lib")
            if kind == "dynamic":
                touch(home / "x64" / "Release" / toolset / kind / "libsodium.dll")


def test_an_msvc_package_gives_the_oldest_toolset_unless_one_is_named(sodium, tmp_path):
    msvc_package(tmp_path, ["v143", "v142", "v145"])
    touch(tmp_path / "x64" / "Release" / "notes" / "readme.txt")

    features, error = sodium["describe_msvc"](str(tmp_path), "x64")
    assert error is None and features["toolset"] == "v142" and set(features["toolsets"]) == {"v142", "v143", "v145"}

    base = os.path.join(str(tmp_path), "x64", "Release", "v142")
    assert features["lib_names"] == [os.path.join(base, "dynamic", "libsodium.lib")]
    assert features["lib_names_static"] == [os.path.join(base, "static", "libsodium.lib")]
    assert features["dynamic_lib"] == os.path.join(base, "dynamic", "libsodium.dll")
    assert features["paths"]["found_dynamic_lib_paths"] == [os.path.join(base, "dynamic")]

    features, error = sodium["describe_msvc"](str(tmp_path), "x64", "v145")
    assert error is None and features["toolset"] == "v145"

    features, error = sodium["describe_msvc"](str(tmp_path), "x64", "v999")
    assert features is None and "v999" in error and "v142" in error

    features, error = sodium["describe_msvc"](str(tmp_path), "ARM64")
    assert features is None and "ARM64" in error


def test_an_msvc_package_with_the_static_library_alone_links_it(sodium, tmp_path):
    msvc_package(tmp_path, ["v143"], kinds = ("static",))

    features, error = sodium["describe_msvc"](str(tmp_path), "x64")
    static = os.path.join(str(tmp_path), "x64", "Release", "v143", "static", "libsodium.lib")
    assert error is None and features["lib_names"] == [static] == features["lib_names_static"]
    assert "dynamic_lib" not in features


def test_a_prefix_gives_the_static_library_by_its_path_with_what_it_needs(sodium, tmp_path):
    lib = tmp_path / "lib"
    archive = touch(lib / "libsodium.a")
    shared = touch(lib / "libsodium.so")
    touch(lib / "pkgconfig" / "libsodium.pc", "Name: libsodium\nLibs: -L${libdir} -lsodium\nLibs.private: -lpthread -pthread\n")

    features, error = sodium["describe_prefix"](str(tmp_path), "linux")
    assert error is None and features["lib_names"] == ["sodium"]
    assert features["lib_names_static"] == [archive, "pthread"]
    assert features["static_lib"] == archive and features["dynamic_lib"] == shared
    assert features["paths"]["found_dynamic_lib_paths"] == [str(lib)]

    # macOS: the shared library has another name; a prefix without a static library says so in describe()
    os.remove(archive)
    features, error = sodium["describe_prefix"](str(tmp_path), "darwin")
    assert features is None and "libsodium.dylib" in error

    touch(lib / "libsodium.dylib")
    touch(tmp_path / "include" / "sodium.h")
    tool = Tool("lib-sodium")
    features, error = sodium["describe"](tool, str(tmp_path / "include" / "sodium.h"), "darwin", "arm64", {})
    assert error is None and "lib_names_static" not in features and "no static library" in features["static_unavailable"]
    assert features["paths"]["includes"] == [str(tmp_path / "include")]


def test_the_version_is_read_from_the_installed_header(sodium, tmp_path):
    touch(tmp_path / "sodium" / "version.h", '#define SODIUM_VERSION_STRING "1.0.22"\n#define SODIUM_LIBRARY_VERSION_MAJOR 26\n')
    assert sodium["read_version"](str(tmp_path)) == "1.0.22"
    assert sodium["read_version"](str(tmp_path / "none")) is None


def test_the_release_facts_of_lib_sodium():
    import re

    d = desc("lib-sodium")
    pins = d["release"]["sha256"]

    assert d["skip_detect"] is True and str(d["default_version"]) in pins
    for version, kinds in pins.items():
        assert set(kinds) == {"source", "msvc"}, version
        assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in kinds.values()), version

    assert all("{file}" in url for url in d["release"]["urls"]) and len(d["release"]["urls"]) >= 2
    assert set(d["release"]["msvc_arch"]) == {"amd64", "arm64"}

    # the release tags only (a tag and its peeled line name one version)
    tags = ("aaa\trefs/tags/1.0.22-RELEASE\nbbb\trefs/tags/1.0.22-FINAL\nccc\trefs/tags/1.0.19\n"
            "ddd\trefs/tags/1.0.21-RELEASE\neee\trefs/tags/1.0.21-RELEASE^{}\nfff\trefs/tags/1.0.20-RELEASE-rc1\n")
    assert set(re.findall(d["cmd_get_versions_regex"], tags)) == {"1.0.22", "1.0.21"}


############################################################
# lib-sodium-android

def test_the_clang_target_is_the_blocks_api_level_or_the_ndks_lowest_above_it(android):
    build = desc("lib-sodium-android")["build"]
    target = android["clang_target"]

    assert target(build, "arm64-v8a", ["35", "21", "24"]) == ("aarch64-linux-android21", 21, None)
    assert target(build, "armeabi-v7a", ["21", "37"]) == ("armv7a-linux-androideabi21", 21, None)
    assert target(build, "arm64-v8a", ["24", "37", "28"]) == ("aarch64-linux-android24", 24, None)

    assert "no Android API level" in target(build, "arm64-v8a", ["19", "20"])[2]
    assert "x86_64" in target(build, "x86_64", ["21"])[2] and "arm64-v8a" in target(build, "x86_64", ["21"])[2]


def test_the_library_sources_leave_the_skipped_folders_out(android, tmp_path):
    build = desc("lib-sodium-android")["build"]
    kept = {"sodium/core.c", "crypto_aead/aegis128l/aegis128l_armcrypto.c", "crypto_stream/salsa20/ref/salsa20_ref.c"}
    skipped = {"crypto_scalarmult/curve25519/sandy2x/curve25519_sandy2x.c", "crypto_stream/salsa20/xmm6/salsa20_xmm6.c"}

    for rel in kept | skipped | {"sodium/notes.txt", "crypto_stream/salsa20/xmm6/salsa20_xmm6-asm.S"}:
        touch(tmp_path / rel)

    found = android["library_sources"](str(tmp_path), build)
    assert {os.path.relpath(f, tmp_path).replace(os.sep, "/") for f in found} == kept
    assert found == sorted(found)


def android_tool(android, device_abi = None):
    t = object.__new__(android["CTool"])
    t.cm, t.cdesc = CM(), desc("lib-sodium-android")

    def access(i):
        if device_abi is None:
            return {"return": 1, "error": "no Android device is connected (adb devices)"}
        i["ctx"]["tasks"]["global"]["target--android-cpu"] = {"features": {"ro.product.cpu.abi": device_abi}}
        return {"return": 0}

    t.cm.access = access
    return t


def test_the_abi_is_the_devices_or_the_one_named(android):
    c = ctx()
    assert android_tool(android, "arm64-v8a").check_params(c, {}, {})["return"] == 0
    assert c["tasks"]["local"]["target_abi"] == "arm64-v8a"

    # no device: the target's own error, unless the ABI is named
    r = android_tool(android).check_params(ctx(), {}, {})
    assert r["return"] == 1 and "no Android device" in r["error"]

    c = ctx()
    assert android_tool(android).check_params(c, {"with": {"abi": "armeabi-v7a"}}, {})["return"] == 0
    assert c["tasks"]["local"]["target_abi"] == "armeabi-v7a"


def test_a_dynamic_build_names_the_shared_library_for_the_device(android, tmp_path):
    header = touch(tmp_path / "include" / "sodium.h")
    archive = touch(tmp_path / "lib" / "libsodium.a")
    shared = touch(tmp_path / "lib" / "libsodium.so")
    t = android_tool(android, "arm64-v8a")

    result = {"return": 0, "path": header, "features": {"flags": {"kept": 1}}}
    assert t.finish_dynamic_result(ctx(), result, {"with": {}})["return"] == 0

    features = result["features"]
    assert features["lib_names"] == ["sodium"] and features["lib_names_static"] == [archive]
    assert features["paths"]["found_dynamic_libs"] == [shared] and features["flags"] == {"kept": 1}

    # the host never gets an Android library on its own loader path
    assert "found_dynamic_lib_paths" not in features["paths"]

    result = {"return": 0, "path": header}
    assert t.finish_dynamic_result(ctx(), result, {"with": {"static": "True"}})["return"] == 0
    assert "found_dynamic_libs" not in result["features"]["paths"]

    os.remove(shared)
    r = t.finish_dynamic_result(ctx(), {"return": 0, "path": header}, {})
    assert r["return"] == 1 and "libsodium.so" in r["error"]


def test_both_tools_pin_one_source_release_and_the_build_block_is_whole():
    host, device = desc("lib-sodium"), desc("lib-sodium-android")

    assert str(host["default_version"]) == str(device["default_version"])
    for version, kinds in device["release"]["sha256"].items():
        assert kinds["source"] == host["release"]["sha256"][version]["source"], version

    build = device["build"]
    assert set(build["targets"]) == set(build["defines_abi"]) == {"arm64-v8a", "armeabi-v7a"}
    assert "CONFIGURED=1" in build["defines"] and len(set(build["defines"])) == len(build["defines"])
    assert int(build["api_level"]) >= 21 and "-shared" in build["ldflags_shared"]
    assert all(key in build["tests"] for key in ("sources", "expected", "include_dirs", "device_dir"))


############################################################
# libc-static

def test_the_compilers_answer_decides_where_the_static_c_library_is(libc, monkeypatch, tmp_path):
    archive = touch(tmp_path / "usr" / "lib64" / "libc.a")

    class Answer:
        def __init__(self, text, code = 0):
            self.stdout, self.returncode = text, code

    answers = {"found": Answer(archive + "\n"), "bare": Answer("libc.a\n"), "failed": Answer(archive, 1)}

    monkeypatch.setattr(libc["subprocess"], "run", lambda args, **kw: answers[args[0]])

    assert libc["static_library_of"]("found") == os.path.realpath(archive)
    assert libc["static_library_of"]("bare") is None
    assert libc["static_library_of"]("failed") is None

    assert isinstance(libc["libc_version"](), str) and libc["libc_version"]()


def test_the_package_and_its_repository_by_distribution(libc):
    t = object.__new__(libc["CTool"])
    t.cm, t.cdesc = CM(), desc("libc-static")

    def package(os_id):
        return t.customize_install_cmd(ctx(host = {"os_extra": {"id": os_id}}), "dnf install -y {{name}}", {})

    assert package("rocky") == {"return": 0, "package_name": "--enablerepo=crb glibc-static"}
    assert package("almalinux")["package_name"] == "--enablerepo=crb glibc-static"

    # the other distributions take the package of the description as it is
    for os_id in ("fedora", "amzn", "azurelinux", "opensuse-leap", "ubuntu", "debian"):
        assert package(os_id) == {"return": 0}, os_id

    d = t.cdesc
    assert d["package_name_os_id"]["fedora"] == d["package_name_os_id"]["amzn"] == "glibc-static"
    assert d["package_name_os_id"]["opensuse-leap"] == "glibc-devel-static" and d["package_name"] == "libc6-dev"
    assert set(d["package_repo_os_id"]) <= set(d["package_name_os_id"])

    # setup-compile links every global key that starts with "lib-": this one is the compiler's own
    assert not d["storage_key"].startswith("lib-") and d["requires_sudo"]["linux"] is True
