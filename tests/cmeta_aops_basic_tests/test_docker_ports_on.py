"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
Authors: Grigori Fursin.

Offline tests of get-host--docker's published ports (2026-11-23): the forms of --ports (a port, host:container, /udp),
their engine flags on 127.0.0.1 by default and on the address --ports_on names - an explicit exposure; anything else is
refused. The forms before stay as they were.
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def task_module():
    """task/get-host--docker's module with the task category's base class replaced by a plain one."""
    path = REPO_ROOT / 'task' / 'get-host--docker' / 'api_v1.py'
    src = path.read_text(encoding = 'utf-8')
    line = 'from task_c36be4b9314a45e0.api.ctask import InitCTask, changed_mounts, write_signatures'
    assert line in src
    src = src.replace(line, 'class InitCTask:\n    def __init__(self, *args, **kwargs):\n        pass\n'
                            'changed_mounts = write_signatures = None')
    ns = {'__name__': 'get_host_docker_api', '__file__': str(path)}
    exec(compile(src, str(path), 'exec'), ns)
    return ns


def test_the_forms_of_ports():
    m = task_module()
    assert m['parse_ports']('') == []
    assert m['parse_ports']('8000') == ['8000:8000']
    assert m['parse_ports']('8080:80, 6443') == ['8080:80', '6443:6443']
    assert m['parse_ports']('8472/udp,10250/tcp') == ['8472:8472/udp', '10250:10250']
    for bad in ('x', '80:y', '8472/sctp', ':80'):
        with pytest.raises(ValueError):
            m['parse_ports'](bad)


def test_the_engine_flags_on_loopback_and_on_an_address():
    m = task_module()
    published = m['parse_ports']('8080:80,8472/udp')
    assert m['port_flags'](published) == ['-p', '127.0.0.1:8080:80', '-p', '127.0.0.1:8472:8472/udp']
    assert m['port_flags'](published, '192.168.1.20') == ['-p', '192.168.1.20:8080:80', '-p', '192.168.1.20:8472:8472/udp']
    assert m['port_flags']([]) == []
