"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The task system-ssh-server offline (2026-11-14): a key found in authorized_keys whatever its options and comment, added
once, a private key never taken for a public one, a listener read from "ss -ltn", the keys-only drop-in. Nothing here
installs, starts or changes an ssh server.
"""

import pytest

KEY = ('ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBn8zXq0P5mUo0n3Q1Gm0pGgYwq6r7wq8ZQyR5vYk2Lx '
       'fleet-key')


@pytest.fixture
def ns(task_namespace):
    return task_namespace('system-ssh-server')


def test_a_key_is_known_by_its_type_and_body(ns):
    body = ns['key_body'](KEY)
    assert body[0] == 'ssh-ed25519' and body[1].startswith('AAAAC3')
    assert ns['key_body']('from="10.0.0.1",no-pty ' + KEY.replace('fleet-key', 'another comment')) == body
    assert ns['key_body']('-----BEGIN OPENSSH PRIVATE KEY-----') is None
    assert ns['key_body']('') is None


def test_a_key_is_added_once(ns):
    text, added = ns['with_key']('', KEY)
    assert added and text == KEY + '\n'
    again, added = ns['with_key'](text, KEY.replace('fleet-key', 'the same key, another comment'))
    assert not added and again == text
    other = 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7 someone'
    text2, added = ns['with_key'](other + '\n', KEY)
    assert added and text2 == other + '\n' + KEY + '\n'
    # a commented line does not count as allowed
    text3, added = ns['with_key']('# ' + KEY + '\n', KEY)
    assert added and text3.endswith(KEY + '\n')
    with pytest.raises(ValueError):
        ns['with_key']('', '-----BEGIN OPENSSH PRIVATE KEY-----')


def test_a_listener_on_the_port(ns):
    ss = ('State  Recv-Q Send-Q Local Address:Port  Peer Address:Port Process\n'
          'LISTEN 0      4096         0.0.0.0:22         0.0.0.0:*\n'
          'LISTEN 0      4096       127.0.0.1:8004       0.0.0.0:*\n')
    assert ns['listening'](ss, 22) and ns['listening'](ss, 8004)
    assert not ns['listening'](ss, 2222) and not ns['listening'](ss.replace(':22 ', ':2222 '), 22)
    assert ns['listening']('State Local\nLISTEN 0 4096 [::]:22 [::]:*\n', 22)


def test_the_drop_in_allows_keys_only(ns):
    text = ns['DROPIN_TEXT']
    assert 'PasswordAuthentication no' in text and 'KbdInteractiveAuthentication no' in text
    assert ns['DROPIN'] == '/etc/ssh/sshd_config.d/50-cmeta-keys-only.conf'
