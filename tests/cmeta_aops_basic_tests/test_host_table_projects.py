"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The project rows of cx host status / cx host ls are printed in the columns of the host table (2026-10-19, the
user's request): a server row has its status in STATUS and its health URL in ADDRESS, the versions after it.
"""

import importlib.util
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def host_category():
    path = REPO_ROOT / "category" / "host" / "api" / "v1.py"
    spec = importlib.util.spec_from_file_location("category_host_table_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # the table helpers use no category state: an instance without the engine's initialisation is enough
    return object.__new__(module.Category)


def server_host(live=True):
    host = {
        "alias": "my-vm",
        "desc": {"projects": {"site-a": {"path": "/srv/a", "server": {"url": "http://127.0.0.1:8118/health/"}},
                              "env-b": {"path": "/srv/b"}}},
        "state": {"projects": {"site-a": {"cmeta_version": "0.37.4", "aops_version": "0.51.0",
                                          "probed_at": "2026-10-19T16:17:53+02:00",
                                          "server": {"status": "up"}}}},
    }
    if live:
        host["project_status"] = {"site-a": {"status": "up", "url": "http://127.0.0.1:8118/health/"}}
    return host


def test_status_rows_use_the_host_columns(capsys):
    category = host_category()
    host = server_host()
    columns = ["HOST", "TYPE", "OS", "STATUS", "ADDRESS"]
    projects = category._project_details([host], columns)
    category._print_table(columns, [["my-vm", "ssh", "ubuntu", "up", "me@192.0.2.1"]], projects=projects)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == columns
    host_line, server_line, env_line = lines[1], lines[2], lines[3]
    # the same column starts: TYPE, STATUS and ADDRESS of a project line up with the host's
    for word in ("ssh", "up", "me@192.0.2.1"):
        column = host_line.index(word)
        cell = {"ssh": "server", "up": "up", "me@192.0.2.1": "http://127.0.0.1:8118/health/"}[word]
        assert server_line[column:].startswith(cell)
    assert server_line.startswith("  * site-a")
    assert server_line.endswith("(cMeta: 0.37.4  AOPS: 0.51.0)")
    assert env_line.split()[:3] == ["*", "env-b", "project"]


def test_ls_rows_put_the_versions_in_their_columns(capsys):
    category = host_category()
    host = server_host(live=False)
    columns = ["HOST", "TYPE", "OS", "CMETA", "AOPS", "PROBED"]
    projects = category._project_details([host], columns)
    host_row = {"alias": "my-vm", "type": "ssh", "os": "Ubuntu", "cmeta": "0.37.4", "aops": "0.51.0",
                "probed": "2026-10-19 16:17"}
    category._print_table(columns, [host_row], projects=projects)
    lines = capsys.readouterr().out.splitlines()
    server_line = lines[2]
    assert server_line.index("0.37.4") == lines[1].index("0.37.4")
    assert server_line.index("2026-10-19 16:17") == lines[1].index("2026-10-19 16:17")
    # no STATUS column in a plain ls: the status saved by the last check follows the URL
    assert server_line.endswith("http://127.0.0.1:8118/health/  (up at the last check)")
