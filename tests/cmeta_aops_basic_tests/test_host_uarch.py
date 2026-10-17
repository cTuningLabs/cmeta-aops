"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

task/host gives one name per architecture, as Go and Docker spell them: amd64 and arm64. Linux says x86_64 and
aarch64; only x86_64 was mapped, so on an ARM Linux machine (a Linux container on a Mac, 2026-10-17) the tools that
know arm64 found no asset - cmake stopped with an unbound variable, the release tools fell back to the package
manager. The OS's own spelling stays in uarch_native.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def host_module():
    path = REPO_ROOT / "task" / "host" / "api_v1.py"
    src = path.read_text(encoding = "utf-8").replace("from task_c36be4b9314a45e0.api.ctask import InitCTask",
                                                     "class InitCTask: pass")
    ns = {"__name__": "task_host_under_test", "__file__": str(path)}
    exec(compile(src, str(path), "exec"), ns)
    return ns


def test_the_linux_names_become_the_names_the_tools_know():
    n = host_module()["normal_uarch"]

    assert n("x86_64") == "amd64" and n("aarch64") == "arm64"

    # Windows (lowercased) and macOS spell them so already; other machines keep their names
    assert n("amd64") == "amd64" and n("arm64") == "arm64"
    assert n("armv7l") == "armv7l" and n("riscv64") == "riscv64" and n("x86") == "x86"
    assert n("") == "" and n(None) is None


def test_no_code_waits_for_a_name_that_never_comes():
    # A comparison with x86_64 or aarch64 never matches now (maps that list both names are fine)
    asked = re.compile(r"""uarch\w*\s*(==|!=)\s*['"](x86_64|aarch64)['"]|['"](x86_64|aarch64)['"]\s*(==|!=)\s*uarch""")
    found = []
    for top in ("category", "task", "tool", "program"):
        for path in (REPO_ROOT / top).rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding = "utf-8", errors = "replace").splitlines(), 1):
                if asked.search(line):
                    found.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert found == []
