"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

task/download-file against a local HTTP server that can cut a transfer, serve ranges or not, change its file
and fail: a file gets its name only when it is complete and its checksum is right; a transfer cut by the
network is an error and its bytes are continued by the next attempt (an HTTP range request, cMeta 0.34.2+),
also when the caller asks for a clean `directory` on every attempt as the tools do; a file whose checksum is
wrong is never accepted by a later attempt; mirrors never complete each other's files.
"""

import http.server
import inspect
import io
import os
import re
import socket
import threading
import zipfile

import pytest

import cmeta.utils.net as engine_net

# The engine checks the size of a transfer and continues partial files since 0.34.2 (download(resume=...))
pytestmark = pytest.mark.skipif('resume' not in inspect.signature(engine_net.download).parameters,
                                reason = 'needs cMeta 0.34.2 or newer (a cut transfer is an error, download(resume=...))')

BODY = b'cMeta download-file test\n' * 4000
OTHER = b'another file of the same size..\n' * 3125
assert len(OTHER) == len(BODY)


def md5(data):
    import hashlib
    return hashlib.md5(data).hexdigest()


def make_zip(payload = b'#!/bin/sh\necho ok\n'):
    """A zip with one top folder (stripped by strip_folders=1) and bin/tool inside."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as z:
        z.writestr('pkg-1.0/bin/tool', payload)
        z.writestr('pkg-1.0/data.bin', b'd' * 50000)
    return buffer.getvalue()


ZIP = make_zip()


class Site:

    def __init__(self):
        self.reset()

    def reset(self):
        self.bodies = {'/file.bin': BODY, '/mirror/file.bin': BODY, '/pkg.zip': ZIP}
        self.etag = '"v1"'
        self.ranges = True
        self.missing = set()        # paths answered with 404
        self.cut = {}               # path -> [bytes to send, per request] (None: all)
        self.requests = []          # (path, Range header or None)


SITE = Site()


class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        site = SITE
        requested = self.headers.get('Range')
        site.requests.append((self.path, requested))

        if self.path in site.missing or self.path not in site.bodies:
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return

        body = site.bodies[self.path]
        status, first = 200, 0
        if requested and site.ranges and self.headers.get('If-Range') in (None, site.etag):
            first = int(re.match(r'bytes=(\d+)-$', requested).group(1))
            if first >= len(body):
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{len(body)}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            status = 206

        payload = body[first:]
        self.send_response(status)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('ETag', site.etag)
        if status == 206:
            self.send_header('Content-Range', f'bytes {first}-{len(body) - 1}/{len(body)}')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()

        cuts = site.cut.get(self.path) or []
        cut = cuts.pop(0) if cuts else None
        self.wfile.write(payload if cut is None else payload[:cut])
        self.wfile.flush()
        if cut is not None:
            self.connection.shutdown(socket.SHUT_WR)       # the connection ends mid-transfer, cleanly
        self.close_connection = True

    def log_message(self, *args):
        pass


@pytest.fixture(scope = 'module')
def httpd():
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target = server.serve_forever, daemon = True).start()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()
    server.server_close()


@pytest.fixture
def server(httpd):
    SITE.reset()
    return httpd


def download(cm, work, url, **params):
    """The task in the folder `work` (its working directory, as a tool's cache entry is for its install)."""
    work.mkdir(exist_ok = True)
    p = {'category': 'task', 'command': 'run', 'arg1': 'download-file', 'path': str(work), 'url': url,
         'con': False, 'quiet': True}
    p.update(params)
    here = os.getcwd()
    try:
        return cm.access(p)
    finally:
        os.chdir(here)


def ranges(path = '/file.bin'):
    return [r for p, r in SITE.requests if p == path]


def leftovers(work):
    """The partial files and resume records under the working directory."""
    return sorted(str(p.relative_to(work)) for p in work.rglob('*') if p.name.endswith(('.download', '.resume')))


###################################################################################################

def test_download(cm, server, tmp_path):
    work = tmp_path / 'w'
    r = download(cm, work, server + '/file.bin')
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == BODY
    assert os.path.samefile(r['path_to_file'], work / 'file.bin') and r['file_size'] == len(BODY)
    assert leftovers(work) == []


def test_cut_transfer_fails_and_the_next_attempt_continues_it(cm, server, tmp_path):
    work = tmp_path / 'w'
    SITE.cut['/file.bin'] = [30000]
    r = download(cm, work, server + '/file.bin')
    assert r['return'] > 0
    assert 'failed downloading file' in r['error']
    assert '30000 of %d bytes' % len(BODY) in r['error']
    assert not (work / 'file.bin').exists()                      # a cut download never gets the file's name
    assert (work / 'file.bin.download').read_bytes() == BODY[:30000]

    r = download(cm, work, server + '/file.bin')
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == BODY
    assert leftovers(work) == []
    assert ranges() == [None, 'bytes=30000-']


def test_cut_twice(cm, server, tmp_path):
    work = tmp_path / 'w'
    SITE.cut['/file.bin'] = [30000, 20000]
    assert download(cm, work, server + '/file.bin')['return'] > 0
    assert download(cm, work, server + '/file.bin')['return'] > 0
    r = download(cm, work, server + '/file.bin')
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == BODY and leftovers(work) == []
    assert ranges() == [None, 'bytes=30000-', 'bytes=50000-']


def test_resume_can_be_turned_off(cm, server, tmp_path):
    work = tmp_path / 'w'
    SITE.cut['/file.bin'] = [30000]
    assert download(cm, work, server + '/file.bin', resume = False)['return'] > 0
    r = download(cm, work, server + '/file.bin', resume = False)
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == BODY and leftovers(work) == []
    assert ranges() == [None, None]


def test_a_clean_directory_keeps_the_partial_download(cm, server, tmp_path):
    """The tools download into `directory` with clean=True on every attempt: the partial file lives outside it."""
    work = tmp_path / 'w'
    SITE.cut['/file.bin'] = [30000]
    r = download(cm, work, server + '/file.bin', directory = 'content', clean = True)
    assert r['return'] > 0
    assert leftovers(work) == ['file.bin.download', 'file.bin.download.resume']
    assert list((work / 'content').iterdir()) == []

    (work / 'content' / 'left-by-the-first-attempt.txt').write_text('x')
    r = download(cm, work, server + '/file.bin', directory = 'content', clean = True)
    assert r['return'] == 0, r.get('error')
    assert (work / 'content' / 'file.bin').read_bytes() == BODY
    assert sorted(p.name for p in (work / 'content').iterdir()) == ['file.bin']       # cleaned, as asked
    assert leftovers(work) == []
    assert ranges() == [None, 'bytes=30000-']


def test_the_install_of_a_tool_cut_and_resumed(cm, server, tmp_path):
    """What a tool's install does (zip, unpack, clean, strip one folder, a check file), cut mid-download."""
    work = tmp_path / 'w'
    check = str(work / 'content' / 'bin' / 'tool')
    params = dict(directory = 'content', unzip = True, clean = True, clean_after_unzip = True, strip_folders = 1, check_file = check)
    SITE.cut['/pkg.zip'] = [20000]
    r = download(cm, work, server + '/pkg.zip', **params)
    assert r['return'] > 0 and not os.path.isfile(check)

    r = download(cm, work, server + '/pkg.zip', **params)
    assert r['return'] == 0, r.get('error')
    assert os.path.isfile(check) and r['path_to_check_file'] == os.path.normpath(check)
    assert not (work / 'content' / 'pkg.zip').exists()          # clean_after_unzip
    assert leftovers(work) == []
    assert ranges('/pkg.zip') == [None, 'bytes=20000-']

    # the check file is there: nothing is asked again (without clean, which empties the folder first)
    r = download(cm, work, server + '/pkg.zip', **dict(params, clean = False))
    assert r['return'] == 0 and len(ranges('/pkg.zip')) == 2


def test_file_changed_on_the_server_between_attempts(cm, server, tmp_path):
    work = tmp_path / 'w'
    SITE.cut['/file.bin'] = [30000]
    assert download(cm, work, server + '/file.bin')['return'] > 0
    SITE.bodies['/file.bin'], SITE.etag = OTHER, '"v2"'
    r = download(cm, work, server + '/file.bin')
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == OTHER             # the new file, whole: nothing of the old one
    assert leftovers(work) == []


def test_server_without_ranges(cm, server, tmp_path):
    work = tmp_path / 'w'
    SITE.ranges = False
    SITE.cut['/file.bin'] = [30000]
    assert download(cm, work, server + '/file.bin')['return'] > 0
    r = download(cm, work, server + '/file.bin')
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == BODY and leftovers(work) == []


###################################################################################################
# Checksums

def test_md5sum(cm, server, tmp_path):
    work = tmp_path / 'w'
    r = download(cm, work, server + '/file.bin', md5sum = md5(BODY))
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == BODY


def test_wrong_md5sum_is_never_accepted(cm, server, tmp_path):
    """
    Until 0.45.0 the checksum was compared only right after a download: the file kept its name after a
    failed check and the next attempt (the same request resumes the same cache entry) took it.
    """
    work = tmp_path / 'w'
    wrong = md5(OTHER)
    for attempt in (1, 2, 3):
        r = download(cm, work, server + '/file.bin', md5sum = wrong)
        assert r['return'] > 0 and 'md5sum failed' in r['error'], f'attempt {attempt}: {r}'
        assert not (work / 'file.bin').exists()
        assert leftovers(work) == []                             # nothing of a wrong file is kept to continue
    assert ranges() == [None, None, None]

    r = download(cm, work, server + '/file.bin', md5sum = md5(BODY))
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == BODY


def test_md5sum_after_a_cut(cm, server, tmp_path):
    """A continued download is checked as a whole."""
    work = tmp_path / 'w'
    SITE.cut['/file.bin'] = [30000]
    assert download(cm, work, server + '/file.bin', md5sum = md5(BODY))['return'] > 0
    r = download(cm, work, server + '/file.bin', md5sum = md5(BODY))
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == BODY and leftovers(work) == []
    assert ranges() == [None, 'bytes=30000-']


def test_a_file_left_with_a_wrong_checksum_is_downloaded_again(cm, server, tmp_path):
    """A file under its name from an attempt of an older cMeta (cut, or of a failed check)."""
    work = tmp_path / 'w'
    work.mkdir()
    (work / 'file.bin').write_bytes(BODY[:30000])
    r = download(cm, work, server + '/file.bin', md5sum = md5(BODY))
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == BODY
    assert ranges() == [None]


def test_a_file_left_without_a_checksum_is_taken_as_it_is(cm, server, tmp_path):
    """As before: nothing says that it is wrong (a file the user put there, a download of an earlier run)."""
    work = tmp_path / 'w'
    work.mkdir()
    (work / 'file.bin').write_bytes(b'put here by hand')
    (work / 'file.bin.download').write_bytes(BODY[:100])         # and what an interrupted attempt left
    (work / 'file.bin.download.resume').write_text('{}')
    r = download(cm, work, server + '/file.bin')
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == b'put here by hand'
    assert SITE.requests == [] and leftovers(work) == []


###################################################################################################
# Mirrors

def test_second_mirror_after_a_missing_file(cm, server, tmp_path):
    work = tmp_path / 'w'
    SITE.missing.add('/file.bin')
    r = download(cm, work, server + '/file.bin,' + server + '/mirror/file.bin')
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == BODY and leftovers(work) == []


def test_mirrors_never_complete_each_other(cm, server, tmp_path):
    """The first mirror is cut, the second serves another file under the same name: its file, whole."""
    work = tmp_path / 'w'
    SITE.cut['/file.bin'] = [30000]
    SITE.bodies['/mirror/file.bin'] = OTHER
    r = download(cm, work, server + '/file.bin,' + server + '/mirror/file.bin')
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == OTHER and leftovers(work) == []
    assert ranges('/mirror/file.bin') == [None]


def test_second_mirror_after_a_wrong_checksum(cm, server, tmp_path):
    """Until 0.45.0 the second mirror found the first one's bad file under its name and took it."""
    work = tmp_path / 'w'
    SITE.bodies['/file.bin'] = OTHER
    r = download(cm, work, server + '/file.bin,' + server + '/mirror/file.bin', md5sum = md5(BODY) + ',' + md5(BODY))
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == BODY and leftovers(work) == []


def test_all_mirrors_fail(cm, server, tmp_path):
    work = tmp_path / 'w'
    SITE.missing.update(['/file.bin', '/mirror/file.bin'])
    r = download(cm, work, server + '/file.bin,' + server + '/mirror/file.bin')
    assert r['return'] > 0 and 'failed downloading file' in r['error'] and '404' in r['error']
    assert not (work / 'file.bin').exists()


###################################################################################################
# What earlier versions left

def test_partial_file_of_the_old_layout_is_dropped(cm, server, tmp_path):
    """Until 0.45.0 the partial file was in `directory`: it has no record and cannot be continued."""
    work = tmp_path / 'w'
    (work / 'content').mkdir(parents = True)
    (work / 'content' / 'file.bin.download').write_bytes(OTHER[:30000])
    r = download(cm, work, server + '/file.bin', directory = 'content')
    assert r['return'] == 0, r.get('error')
    assert (work / 'content' / 'file.bin').read_bytes() == BODY
    assert leftovers(work) == [] and ranges() == [None]


def test_partial_file_without_a_record_starts_over(cm, server, tmp_path):
    work = tmp_path / 'w'
    work.mkdir()
    (work / 'file.bin.download').write_bytes(OTHER[:30000])
    r = download(cm, work, server + '/file.bin')
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == BODY and ranges() == [None]


def test_a_cut_archive_left_under_its_name_says_what_to_do(cm, server, tmp_path):
    """
    cMeta before 0.34.2 could leave a cut download under its name; the same request then finds it and fails
    at the unpack every time. The error names the file to delete - and a fresh download has no such advice.
    """
    work = tmp_path / 'w'
    (work / 'content').mkdir(parents = True)
    (work / 'content' / 'pkg.zip').write_bytes(ZIP[:20000])
    r = download(cm, work, server + '/pkg.zip', directory = 'content', unzip = True, strip_folders = 1)
    assert r['return'] > 0
    assert 'was left by an earlier attempt' in r['error'] and 'delete this file' in r['error']
    assert os.path.join('content', 'pkg.zip') in r['error']
    assert SITE.requests == []

    (work / 'content' / 'pkg.zip').unlink()
    SITE.bodies['/pkg.zip'] = ZIP[:20000]                        # the server's own file is damaged
    r = download(cm, work, server + '/pkg.zip', directory = 'content', unzip = True, strip_folders = 1)
    assert r['return'] > 0 and 'was left by an earlier attempt' not in r['error']


def test_an_engine_without_resume(cm, server, tmp_path, monkeypatch):
    """cMeta before 0.34.2: download() has no `resume` - the task does not pass it and every attempt starts over."""
    real = cm.utils.net.download

    def old_download(url, filename = None, path = None, chunk_size = 65536, show_progress = False, fail_on_error = False,
                     text = 'Downloading ', headers = None, api_key = None, skip_ssl_certificate = False, space = ''):
        return real(url, filename = filename, path = path, show_progress = show_progress, fail_on_error = fail_on_error,
                    headers = headers, api_key = api_key, skip_ssl_certificate = skip_ssl_certificate, space = space)

    monkeypatch.setattr(cm.utils.net, 'download', old_download)
    work = tmp_path / 'w'
    SITE.cut['/file.bin'] = [30000]
    assert download(cm, work, server + '/file.bin')['return'] > 0
    r = download(cm, work, server + '/file.bin')
    assert r['return'] == 0, r.get('error')
    assert (work / 'file.bin').read_bytes() == BODY
    assert ranges() == [None, None]
