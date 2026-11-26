"""
tool/nsys installs Nsight Systems without root from NVIDIA's CUDA redistributable archives: offline, the release whose
Nsight Systems is asked (or the newest one the driver runs), the command line inside an unpacked archive, and the
tool that reads NVIDIA's lists, named by its UID.
"""

import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# The Nsight Systems of four CUDA releases, one without it
MANIFESTS = {
    "12.8.1": {"nsight_systems": {"version": "2025.1.1.110"}},
    "12.9.1": {"nsight_systems": {"version": "2025.1.3.140"}},
    "13.0.0": {"cuda_nvcc": {"version": "13.0.48"}},
    "13.3.1": {"nsight_systems": {"version": "2026.1.3.425"}},
}
RELEASES = sorted(MANIFESTS, key = lambda r: tuple(int(x) for x in r.split(".")))


@pytest.fixture(scope = "module")
def nsys():
    """tool/nsys/api_v1.py without the tool engine: its helpers."""
    path = REPO_ROOT / "tool" / "nsys" / "api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from tool_c393ba5c6fa14f66.api.ctool import InitCTool",
                                                     "class InitCTool:\n    pass")
    ns = {"__name__": "tool_nsys_under_test", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def prefix(spec, version):
    """As cMeta matches a version asked: the same, or a prefix of its parts."""
    return version == spec or version.startswith(spec + ".")


def test_a_version_asked_takes_the_newest_release_that_carries_it(nsys):
    pick = nsys["pick"]
    assert pick(RELEASES, MANIFESTS.get, "2026.1.3.425", prefix) == ("13.3.1", "2026.1.3.425")
    assert pick(RELEASES, MANIFESTS.get, "2025.1", prefix) == ("12.9.1", "2025.1.3.140")

    release, why = pick(RELEASES, MANIFESTS.get, "2027", prefix)
    assert release is None
    assert why == "Nsight Systems 2027 not available in NVIDIA's CUDA archives (12.8.1 to 13.3.1)"


def test_without_a_version_the_newest_release_the_driver_runs(nsys):
    pick = nsys["pick"]
    assert pick(RELEASES, MANIFESTS.get, None, prefix, "13.3.1") == ("13.3.1", "2026.1.3.425")
    assert pick(RELEASES, MANIFESTS.get, None, prefix, None) == ("13.3.1", "2026.1.3.425")

    # the newest release this driver runs carries no Nsight Systems: the newest older one that does
    assert pick(RELEASES, MANIFESTS.get, None, prefix, "13.0.0") == ("12.9.1", "2025.1.3.140")
    assert pick([], MANIFESTS.get)[0] is None


def test_the_command_line_of_an_unpacked_archive(nsys, tmp_path):
    find = nsys["find_nsys"]
    assert find(str(tmp_path / "none")) is None

    # host-* holds the GUI and the scripts of the reports; the command line is in target-<platform>
    (tmp_path / "host-linux-x64").mkdir()
    (tmp_path / "host-linux-x64" / "nsys-ui").write_text("")
    assert find(str(tmp_path)) is None

    (tmp_path / "target-linux-x64").mkdir()
    (tmp_path / "target-linux-x64" / "nsys").write_text("")
    assert find(str(tmp_path)) == str(tmp_path / "target-linux-x64" / "nsys")


def test_the_command_line_of_the_windows_archive_is_the_one_of_this_cpu(nsys, tmp_path):
    # nsight-systems/<version>/target-*: armv8 sorts before x64 (an x64 Windows ran the ARM nsys.exe, 2026-11-26),
    # and target-linux-x64/nsys is there for remote targets
    top = tmp_path / "nsight-systems" / "2026.3.2"
    for target, name in (("target-linux-x64", "nsys"), ("target-windows-armv8", "nsys.exe"),
                         ("target-windows-x64", "nsys.exe")):
        (top / target).mkdir(parents = True)
        (top / target / name).write_text("")
    find = nsys["find_nsys"]
    assert find(str(tmp_path), ".exe", "windows", "amd64") == str(top / "target-windows-x64" / "nsys.exe")
    assert find(str(tmp_path), ".exe", "windows", "arm64") == str(top / "target-windows-armv8" / "nsys.exe")
    assert find(str(tmp_path), "", "linux", "amd64") == str(top / "target-linux-x64" / "nsys")

    # none of this system and CPU: none, never another one
    assert find(str(tmp_path), "", "linux", "arm64") is None


def test_the_reader_of_nvidias_lists_is_tool_nvcc_by_its_uid(nsys):
    meta = yaml.safe_load((REPO_ROOT / "tool" / "nvcc" / "_cmeta.yaml").read_text(encoding = "utf-8"))
    assert nsys["NVCC"] == "nvcc," + meta["artifact"]
    assert (REPO_ROOT / "tool" / "nvcc" / "redist.py").is_file()
