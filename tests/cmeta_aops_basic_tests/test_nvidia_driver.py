"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Offline tests of tool/nvidia-driver (the releases a GPU can take and how one is installed, drivers.py) and of the
hook task/setup asks for a tool's newest version (latest_version of the tool's API). No network, nothing installed:
NVIDIA's answers are small copies of their real shape (2026-10-30).
"""

import importlib.util
import json
import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "tool" / "nvidia-driver"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def nv():
    return load("nvidia_driver_drivers", TOOL / "drivers.py")


@pytest.fixture(scope="module")
def desc():
    return yaml.safe_load((TOOL / "_desc.yaml").read_text(encoding="utf-8"))


def test_versions_branches_and_requests(nv):
    assert nv.key("615.78.08") == (615, 78, 8) and nv.branch("580.196.07") == 580
    assert nv.matches("615.78.08", "615") and nv.matches("615.78.08", "615.78") and not nv.matches("615.71.09", "615.78")
    assert nv.matches("615.78.08", "") and not nv.matches("610.57.04", "615")
    versions = ["580.126.20", "580.196.07", "595.84", "610.57.04", "615.71.09", "615.78.08"]
    assert nv.pick(versions) == "615.78.08"
    assert nv.pick(versions, max_branch=580) == "580.196.07"
    assert nv.pick(versions, "610") == "610.57.04" and nv.pick(versions, "615", max_branch=580) is None
    assert nv.pick(versions, "595.84") == "595.84"


def test_legacy_gpus_stop_at_their_branch(nv, desc):
    legacy = desc["legacy_branches"]
    assert nv.last_branch(50, legacy) == 580                  # GeForce 940MX (Maxwell)
    assert nv.last_branch(70, legacy) == 580                  # Volta
    assert nv.last_branch(35, legacy) == 470                  # Kepler
    assert nv.last_branch(21, legacy) == 390                  # Fermi
    assert nv.last_branch(75, legacy) is None and nv.last_branch(120, legacy) is None
    assert nv.last_branch(None, legacy) is None


def test_the_linux_archive(nv, desc):
    listing = ("<a href='580.196.07/'>580.196.07/</a> <a href='595.84/'>595.84/</a>"
               "<a href='615.78.08/'>615.78.08/</a> <a href='latest.txt'>latest.txt</a> <a href='1.0-9629/'>1.0-9629/</a>")
    assert nv.linux_versions(listing) == ["580.196.07", "595.84", "615.78.08"]
    url, sha = nv.linux_runfile(desc["linux_archive"], "615.78.08")
    assert url == "https://download.nvidia.com/XFree86/Linux-x86_64/615.78.08/NVIDIA-Linux-x86_64-615.78.08.run"
    assert sha == url + ".sha256sum"
    digest = "a" * 64
    assert nv.linux_sha256(f"{digest}  NVIDIA-Linux-x86_64-615.78.08.run\n") == digest and nv.linux_sha256("") is None


def test_the_kernel_module_type_and_the_installer_options(nv, desc):
    min_arch = desc["open_kernel_modules_min_arch"]
    running_open = "NVRM version: NVIDIA UNIX Open Kernel Module for x86_64  610.43.02  Release Build"
    running_prop = "NVRM version: NVIDIA UNIX x86_64 Kernel Module  580.126.20  Wed Feb 18 05:56:34 UTC 2026"
    assert nv.module_type(running_open, 86, min_arch) == "open"
    assert nv.module_type(running_prop, 86, min_arch) == "proprietary"      # the type in use is kept
    assert nv.module_type("", 86, min_arch) == "open" and nv.module_type("", 50, min_arch) == "proprietary"
    args = nv.linux_install_args("open")
    for a in ("--silent", "--dkms", "--no-x-check", "--skip-module-load", "--rebuild-initramfs", "--kernel-module-type=open"):
        assert a in args
    assert "--disable-nouveau" not in args and "--disable-nouveau" in nv.linux_install_args("proprietary", True)


def test_a_module_that_does_not_build_is_named(nv):
    log = ("make[4]: Entering directory\n"
           "././common/inc/nv-linux.h:1270:34: error: field 'cxlds' has incomplete type\n"
           " 1270 |     struct cxl_dev_state         cxlds;\n"
           "ERROR: The nvidia kernel module was not created.\n")
    assert nv.build_error(log) == "././common/inc/nv-linux.h:1270:34: error: field 'cxlds' has incomplete type"
    assert nv.build_error("ERROR: Installation has failed.\n") is None and nv.build_error("") is None


def test_the_product_of_a_gpu(nv):
    xml = ('<LookupValueSearch><LookupValues>'
           '<LookupValue ParentID="99" RequiresProduct="False"><Name>GeForce 940MX</Name><Value>796</Value></LookupValue>'
           '<LookupValue ParentID="124" RequiresProduct="False"><Name>NVIDIA RTX A500 Laptop GPU</Name><Value>998</Value></LookupValue>'
           '<LookupValue ParentID="133" RequiresProduct="False"><Name>NVIDIA RTX PRO 1000 Blackwell</Name><Value>1077</Value></LookupValue>'
           '<LookupValue ParentID="134" RequiresProduct="False"><Name>NVIDIA RTX PRO 1000 Blackwell Laptop GPU</Name><Value>1088</Value></LookupValue>'
           '</LookupValues></LookupValueSearch>')
    plist = nv.products(xml)
    assert len(plist) == 4
    # nvidia-smi says "Generation", NVIDIA's list does not; a laptop GPU is never taken for the desktop one
    assert nv.find_product(plist, "NVIDIA RTX PRO 1000 Blackwell Generation Laptop GPU")[:2] == (134, 1088)
    assert nv.find_product(plist, "NVIDIA RTX PRO 1000 Blackwell")[:2] == (133, 1077)
    assert nv.find_product(plist, "NVIDIA GeForce 940MX")[:2] == (99, 796)
    assert nv.find_product(plist, "NVIDIA RTX A500 Laptop GPU")[:2] == (124, 998)
    assert nv.find_product(plist, "NVIDIA GeForce RTX 5090") is None


def test_the_download_service(nv, desc):
    url = nv.lookup_url(desc["download_service"], 134, 1088, desc["windows_os_id"])
    assert "psid=134" in url and "pfid=1088" in url and "osID=57" in url and "qnf=1" in url and "dch=1" in url
    answer = {"Success": "1", "IDS": [
        {"downloadInfo": {"Version": "610.88", "Name": "NVIDIA%20RTX%20Driver%20Release%20610",
                          "ReleaseDateTime": "Thu Jul 30, 2026", "DownloadURLFileSize": "768.42 MB",
                          "DownloadURL": "https://us.download.nvidia.com/Windows/Quadro_Certified/610.88/610.88-quadro-rtx-desktop-notebook-win10-win11-64bit-international-dch-whql.exe"}},
        {"downloadInfo": {"Version": "616.92", "Name": "NVIDIA%20RTX%20Driver%20Release%20615",
                          "DownloadURL": "https://us.download.nvidia.com/Windows/Quadro_Certified/616.92/616.92-quadro-rtx-desktop-notebook-win10-win11-64bit-international-dch-whql.exe"}},
        {"downloadInfo": {"Success": "0", "ID": ""}}]}
    found = nv.lookup_drivers(json.dumps(answer))
    assert [d["version"] for d in found] == ["616.92", "610.88"]
    assert found[0]["name"] == "NVIDIA RTX Driver Release 615" and found[0]["url"].endswith(".exe")
    assert [d["branch"] for d in found] == [615, 610]

    # a Windows driver's number does not say its branch: 616.92 is R615, 582.99 is R580
    branches = {"616.92": 615, "610.88": 610, "597.30": 595, "582.99": 580}
    versions = list(branches)
    assert nv.pick(versions, "615", branches=branches) == "616.92" and nv.pick(versions, "616", branches=branches) == "616.92"
    assert nv.pick(versions, max_branch=595, branches=branches) == "597.30"
    assert nv.pick(versions, max_branch=580, branches=branches) == "582.99"
    assert nv.pick(versions, max_branch=580) is None                       # without the listing's branches
    assert nv.lookup_drivers("not json") == [] and nv.lookup_drivers('{"Success": "0"}') == []
    assert nv.windows_install_args() == ["-s", "-noreboot"]


def test_the_windows_driver_version(nv):
    assert nv.windows_version("32.0.15.9713") == "597.13"
    assert nv.windows_version("32.0.16.1692") == "616.92"
    assert nv.windows_version("31.0.15.8088") == "580.88"
    assert nv.windows_version("") is None and nv.windows_version("1.2") is None


def test_the_cuda_of_each_branch_is_declared(desc):
    assert desc["cuda_of_branch"]["615"] == "13.4" and desc["cuda_of_branch"]["595"] == "13.2"
    assert desc["requires_sudo"] == {"windows": True, "linux": True}


###################################################################################################
# task/setup asks the tool's API for its newest version

class _Code:
    def __init__(self, answer):
        self.answer = answer

    def latest_version(self, ctx, params):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture(scope="module")
def up():
    return load("setup_upgrade_nvidia", REPO_ROOT / "task" / "setup" / "upgrade.py")


CTX = {"tasks": {"global": {"host": {"os": {"uname": "linux"}, "os_extra": {}}}}}
CHANNELS = {"declared": None, "package": None}


def test_find_latest_takes_the_answer_of_the_tools_api(up):
    tool_read = {"tool_api_code": _Code({"return": 0, "version": "615.78.08", "source": "the archive"})}
    r = up.find_latest(None, CTX, {}, tool_read, {}, CHANNELS)
    assert (r["upstream_version"], r["upstream_source"]) == ("615.78.08", "the archive") and r["notes"] == []


def test_find_latest_notes_a_failed_answer_and_goes_on(up):
    for answer in ({"return": 16, "error": "no NVIDIA GPU found"}, RuntimeError("offline")):
        r = up.find_latest(None, CTX, {}, {"tool_api_code": _Code(answer)}, {}, CHANNELS)
        assert r["upstream_version"] is None
        assert any("could not tell its newest version" in n for n in r["notes"])
    r = up.find_latest(None, CTX, {}, {"tool_api_code": object()}, {}, CHANNELS)    # a tool without the hook
    assert r["upstream_version"] is None and not any("could not tell" in n for n in r["notes"])
