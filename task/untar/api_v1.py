"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import json
import os
import re
import shutil
import subprocess
import tarfile
import threading
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask

# .tar.zst and the chains of "cx host archive" (2026-11-12, the user: "add task untar-incremental or something like
# that ... that can automate that portably across all machines with this zstd tool"): zstd and tar set up by cMeta
# (found, else installed). A CHAIN is a full archive <name>-<chain>.tar.zst and its increments
# <name>-<chain>+<when>.tar.zst in one folder (YYYYMMDD-HHMM stamps); --chain restores the full archive, then each
# increment in order up to the given part (or --until a time). The .json beside each part says who made it: GNU tar
# (format gnu-tar - its increments delete through --listed-incremental=/dev/null, GNU tar needed) or the Python
# archiver of a Windows machine (python-tar - names C/Users/..., each increment's .cmeta-archive/deleted.txt lists what
# was removed since the part before: deleted first)
PART = re.compile(r'^(?P<name>.+)-(?P<chain>\d{8}-\d{4})(?:\+(?P<when>\d{8}-\d{4}))?\.tar\.zst$')
META_DIR = '.cmeta-archive'
PROGRESS_EVERY = 10


def _size_text(n):
    """Bytes for a person, 1000-based (2026-11-12): 812 B, 3.4 GB."""
    n = float(n or 0)
    for unit in ('B', 'kB', 'MB', 'GB', 'TB'):
        if n < 1000 or unit == 'TB':
            return f'{n:.0f} {unit}' if unit in ('B', 'kB') else f'{n:.1f} {unit}'
        n /= 1000


def _stamp(text):
    """'2026-11-12 08:30', '20261112-0830', '20261112' -> '20261112-0830' / '20261112' (a prefix: the end of that day)."""
    digits = re.sub(r'\D', '', str(text or ''))
    return digits[:8] + ('-' + digits[8:12] if len(digits) > 8 else '')


def chain_parts(filename, until=None):
    """The parts of the chain of filename (a part of it), in order, up to filename - or up to the newest part made at or
    before until -> {return, parts: [paths], error}."""
    folder, base = os.path.split(os.path.abspath(filename))
    m = PART.match(base)
    if not m:
        return {'return': 1, 'error': f'{base} is no part of a chain of "cx host archive" (<name>-<YYYYMMDD-HHMM>[+<YYYYMMDD-HHMM>].tar.zst)'}
    name, chain = m.group('name'), m.group('chain')
    full, increments = '', []
    for x in os.listdir(folder):
        mx = PART.match(x)
        if not mx or mx.group('name') != name or mx.group('chain') != chain:
            continue
        if mx.group('when'):
            increments.append((mx.group('when'), x))
        else:
            full = x
    if not full:
        return {'return': 1, 'error': f'the full archive of the chain {chain} ({name}-{chain}.tar.zst) is not in {folder}'}
    last = m.group('when') or chain
    parts = [(chain, full)] + sorted(increments)
    parts = [p for p in parts if p[0] <= last]
    if until:
        u = _stamp(until)
        parts = [p for p in parts if p[0][:len(u)] <= u]
        if not parts:
            return {'return': 1, 'error': f'the chain {chain} begins after {until}'}
    return {'return': 0, 'parts': [os.path.join(folder, x) for _, x in parts]}


def part_format(path):
    """Who made a part: 'python-tar' (the Python archiver), else 'gnu-tar' (also an archive from elsewhere)."""
    try:
        with open(path + '.json', encoding='utf-8') as f:
            return json.load(f).get('format') or 'gnu-tar'
    except (OSError, ValueError):
        return 'gnu-tar'


def _long(path):
    if os.name == 'nt' and len(path) >= 240 and not path.startswith('\\\\'):
        return '\\\\?\\' + path
    return path


class _Counting:
    """A file read through, its bytes counted (the progress of a part)."""

    def __init__(self, f):
        self.f, self.n = f, 0

    def read(self, size=-1):
        b = self.f.read(size)
        self.n += len(b)
        return b


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def init(self,
             ctx: dict,
             params: dict,
    ):
        """
        We need this function to resolve name if not provided,
        to be able to customize cache_artifact properly.

        We can also add extra checks on unified params here.
        """

        result = {'return':0}

        filename = params.get('filename')

        if not filename:
            return self.cm.error(f'filename is not defined in "{__file__}" ({__name__})')

        if not os.path.isfile(filename):
            return self.cm.error(f'filename "{filename}" not found in "{__file__}" ({__name__})')

        return result


    ############################################################
    def customize_cache_artifact(self,
                                 ctx,
                                 cache_alias_template,
                                 cache_extra_alias,
                                 cache_meta,
                                 cache_tags,
                                 cache_params,
                                 params,
                                 **extra,
        ):

        result = {'return':0}

        # It's dangerous because filenames can contain weird characters
        # Either clean it or rely on manually added cache_extra_alias

#        filename = params['filename']
#
#        if cache_extra_alias is None:
#            cache_extra_alias = ''
#
#        if cache_extra_alias !='':
#            cache_extra_alias += self.cache_sep
#        cache_extra_alias += filename
#
#        result['cache_extra_alias'] = cache_extra_alias


        return result

    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            filename: str = None,
            env: dict = {},
            directory: str = None,
            clean_after_untar: bool = False,
            strip_folders: int = None,
            timeout: int = None,
            fail_if_nonzero_return_code: bool = True,
            chain: bool = False,        # .tar.zst of "cx host archive": the whole chain up to this part, in order
            until: str = None,          # with chain: up to the newest part made at or before this time (YYYYMMDD-HHMM or a prefix)
            sudo: bool = False,         # tar through sudo -n (owners and modes kept, system folders writable) - Linux, macOS
            in_place: bool = False,     # the Python archiver's parts: each name back to its drive (C/Users/... -> C:\Users\...)
            paths: str = None,          # only these names of the archive (comma-separated, as they are in it), what is under them too
    ):

        """
        Untar file.

            cx task run untar backup.tar.gz --directory=out
            cx task run untar my-vm-20261112-0800.tar.zst --directory=restore      # zstd and tar set up by cMeta
            cx task run untar my-vm-20261112-0800+20261113-0800.tar.zst --chain --directory=restore   # the full one, then each increment
            cx task run untar my-vm-20261112-0800.tar.zst --chain --until=20261120 --directory=restore

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK untar run api_v1")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''
        clean = ctx['tasks']['run_control'].get('clean', False)
        update = ctx['tasks']['run_control'].get('update', False)

        uname = ctx['tasks']['global']['host']['os']['uname']

        if filename.endswith('.tar.zst') or filename.endswith('.tzst'):
            return self._untar_zst(ctx, filename, directory, chain, until, sudo, in_place, paths, strip_folders,
                                   clean_after_untar, con, quiet, verbose)
        if chain or in_place:
            return self.cm.error('--chain and --in_place are for the .tar.zst archives of "cx host archive"')

        _local = {}

        uses = None

        flags = '-xvf'

        if filename.endswith('.xz'):
            flags = '-xf'

            if uname != 'windows':
                uses = [{
                  'task': 'setup,a2f9b61079ce4333',
                  'name': 'xz,ed6519b03186488d',
                }]

        elif filename.endswith('.tar.gz') or filename.endswith('.tgz'):
            flags = '-xvzf'

            if uname != 'windows':
                uses = [{
                  'task': 'setup,a2f9b61079ce4333',
                  'name': 'gzip',
                }]

        elif filename.endswith('.tar.bz2'):
            flags = '-xvjf'

            if uname != 'windows':
                uses = [{
                  'task': 'setup,a2f9b61079ce4333',
                  'name': 'bzip2,97c4bde150494ca6',
                }]


        # Check extra deps
        if uses:
            ii = {'category': self.category_alias + ',' + self.category_uid,
                  'command': 'use',
                  'con': con,
                  'quiet': quiet,
                  'verbose': verbose,
                  'ctx': ctx,
                  'desc': uses,
                  'local': _local,
                  'task_artifact_alias': self.artifact_alias,
                  'task_artifact_uid': self.artifact_uid,
                  'task_artifact_path': self.artifact_path,
                 }

            r = self.cm.access(ii)
            if self.cm.catch_error(r, fail16=True): return r


        tar_path = ctx['tasks']['global']['tar']['qpath']

# FGG: should not make such default since can break logic in related tasks
#        if not directory:
#            directory = 'content'

        if not directory:
            directory = os.getcwd()

        path = os.path.abspath(directory)
        qpath = self.cm.utils.files.quote_path(path)

        if not os.path.exists(path):
            os.makedirs(path)

        cmd = tar_path + ' ' + flags + ' ' + filename + ' -C ' + qpath

        if strip_folders:
            cmd += f' --strip-components={strip_folders}'

        ii = {'category': self.category_alias + ',' + self.category_uid,
              'command': 'run',
              'ctx': ctx,
              'arg1': 'cmd,c9ba0a88df394d7f',
              'cmd': cmd,
              'env': env,
              'con': con,
              'quiet': quiet,
              'verbose': verbose,
              'quiet': quiet,
              'text_cmd': 'RUN:',
#              'print_env_keys': [],
              'print_extra_line': True,
              'fail_if_nonzero_return_code': fail_if_nonzero_return_code,
        }

        rx = self.cm.access(ii)
        if self.cm.catch_error(rx): return rx

        if clean_after_untar and os.path.isfile(filename):
            if verbose:
                print (f'{space}RUN: rm {filename}')

            os.remove(filename)

        return {'return':0, 'path':path, 'qpath':qpath}

    ############################################################
    def _tool(self, name, quiet):
        """A tool set up by cMeta here (found, else installed) -> {return, path}."""
        r = self.cm.access({'category': self.category_alias + ',' + self.category_uid, 'command': 'run',
                            'arg1': 'setup,a2f9b61079ce4333', 'name': name, 'con': False, 'quiet': quiet})
        if r.get('return', 1) > 0 or not r.get('path'):
            return self.cm.error(f'{name.split(",")[0]} could not be set up by cMeta: {r.get("error", "no path")}')
        return {'return': 0, 'path': r['path']}

    def _untar_zst(self, ctx, filename, directory, chain, until, sudo, in_place, paths, strip_folders, clean_after_untar,
                   con, quiet, verbose):
        """A .tar.zst (or a chain of them) extracted: the Python archiver's parts by Python, the others by tar fed by zstd -
        both tools set up by cMeta."""
        if in_place and directory:
            return self.cm.error('--in_place puts each name back where it came from: not with --directory')
        if chain:
            r = chain_parts(filename, until)
            if r['return'] > 0:
                return self.cm.error(r['error'])
            parts = r['parts']
        else:
            parts = [os.path.abspath(filename)]
        formats = {part_format(p) for p in parts}
        if len(formats) > 1:
            return self.cm.error('the chain mixes the archives of GNU tar and of the Python archiver - restore its parts one by one')
        python_tar = formats == {'python-tar'}
        if in_place and not python_tar:
            return self.cm.error('--in_place is for the archives of the Python archiver (Windows); a GNU tar archive: --directory=/')
        if not in_place:
            directory = os.path.abspath(directory or os.getcwd())
            os.makedirs(directory, exist_ok=True)
        only = [p.strip().strip('/') for p in str(paths or '').split(',') if p.strip()]

        if con:
            print(f'{"the chain, in order" if chain else "the archive"}: ' + ', '.join(os.path.basename(p) for p in parts))
            print('into: ' + ('the places the names come from (C/... -> C:\\...)' if in_place else directory))

        r = {'return': 0, 'deleted': 0, 'entries': 0, 'warnings': []}
        zstd = None
        tar = None
        for i, part in enumerate(parts):
            label = f'part {i + 1}/{len(parts)} {os.path.basename(part)}' if len(parts) > 1 else os.path.basename(part)
            if python_tar:
                x = self._extract_py(part, directory, in_place, only, label, con, quiet)
            else:
                if zstd is None:
                    x = self._tool('zstd,e70d016f472d462e', quiet)
                    if x['return'] > 0: return x
                    zstd = x['path']
                    # GNU tar for a chain (its deletions: --listed-incremental), any tar else
                    x = self._tool('gnu-tar,93bb237a0ee04cd6' if chain else 'tar,788abc644bf24d86', quiet)
                    if x['return'] > 0: return x
                    tar = x['path']
                    if con:
                        print(f'tools: zstd ({zstd}), tar ({tar})')
                x = self._extract_tar(part, directory, zstd, tar, chain, sudo, only, strip_folders, label, con)
            if x['return'] > 0:
                return x
            r['entries'] += x.get('entries', 0)
            r['deleted'] += x.get('deleted', 0)
            r['warnings'] += x.get('warnings', [])
        if clean_after_untar and not chain and os.path.isfile(filename):
            os.remove(filename)
        r.update(path=directory or '', parts=parts)
        if con:
            print(f'restored: {len(parts)} part(s)' + (f', {r["entries"]:,} entries' if r['entries'] else '')
                  + (f', {r["deleted"]:,} deleted as the chain says' if r['deleted'] else '')
                  + (f', {len(r["warnings"])} warnings' if r['warnings'] else ''))
        return r

    def _extract_tar(self, part, directory, zstd, tar, chain, sudo, only, strip_folders, label, con):
        """zstd -dc | tar -x for one part, the compressed bytes fed from here (a line every 10 s)."""
        # GNU tar of Windows (Git's) reads a backslash as an escape (D:\x\1356 -> D:x]6): forward slashes there
        cmd = ([] if not sudo else ['sudo', '-n']) + [tar, '-xf', '-', '-C', directory.replace('\\', '/') if os.name == 'nt' else directory]
        if sudo:
            cmd += ['-p', '--numeric-owner']
        if chain:
            cmd += ['--listed-incremental=/dev/null']       # GNU tar: the deletions each increment records
        if strip_folders:
            cmd += [f'--strip-components={strip_folders}']
        cmd += only
        size = os.path.getsize(part)
        z = subprocess.Popen([zstd, '-dc', '-q'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        t = subprocess.Popen(cmd, stdin=z.stdout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        z.stdout.close()
        out = []
        reader = threading.Thread(target=lambda: out.extend(t.stdout.read().decode('utf-8', 'replace').splitlines()), daemon=True)
        reader.start()
        t0 = last = time.monotonic()
        done = 0
        try:
            with open(part, 'rb') as f:
                for chunk in iter(lambda: f.read(1 << 20), b''):
                    z.stdin.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if con and now - last >= PROGRESS_EVERY:
                        last = now
                        print(f'    {label}: {_size_text(done)} of {_size_text(size)} ({100 * done / max(size, 1):.0f}%)', flush=True)
            z.stdin.close()
        except BrokenPipeError:
            pass
        zrc, trc = z.wait(), t.wait()
        reader.join(timeout=10)
        if zrc != 0 or trc not in (0,):
            return self.cm.error(f'{os.path.basename(part)}: zstd ended with {zrc}, tar with {trc}: ' + ' | '.join(out[-3:]))
        if con:
            print(f'    {label}: done in {int(time.monotonic() - t0)}s', flush=True)
        return {'return': 0, 'warnings': out[-20:]}

    def _extract_py(self, part, directory, in_place, only, label, con, quiet):
        """A part of the Python archiver extracted by Python: what its deleted.txt lists removed first, then every entry
        (only those under the names asked for), each name mapped to its place. A line every 10 s."""
        def target(name):
            bits = [b for b in name.split('/') if b]
            if not bits or any(b in ('.', '..') for b in bits):
                return None
            if in_place:
                if len(bits[0]) != 1 or not bits[0].isalpha():
                    return None
                return bits[0] + ':\\' + '\\'.join(bits[1:]) if os.name == 'nt' else '/' + '/'.join(bits[1:])
            return os.path.join(directory, *bits)

        def wanted(name):
            return not only or any(name == o or name.startswith(o + '/') for o in only)

        proc = None
        raw = open(part, 'rb')
        counting = _Counting(raw)
        size = os.path.getsize(part)
        try:
            try:
                from compression import zstd as _z     # noqa: F401 - tarfile reads zstd through it
                tf = tarfile.open(fileobj=counting, mode='r|zst')
            except ImportError:
                x = self._tool('zstd,e70d016f472d462e', quiet)
                if x['return'] > 0:
                    return x
                proc = subprocess.Popen([x['path'], '-dc', '-q', part], stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
                tf = tarfile.open(fileobj=proc.stdout, mode='r|')
            entries = deleted = 0
            warnings, dirs = [], []
            t0 = last = time.monotonic()
            with tf:
                for m in tf:
                    if m.name == META_DIR + '/deleted.txt':
                        for name in tf.extractfile(m).read().decode('utf-8').splitlines():
                            p = target(name) if wanted(name) else None
                            if not p:
                                continue
                            try:
                                if os.path.isdir(_long(p)) and not os.path.islink(p):
                                    shutil.rmtree(_long(p))
                                elif os.path.lexists(_long(p)):
                                    os.remove(_long(p))
                                deleted += 1
                            except OSError as e:
                                warnings.append(f'{p}: not deleted ({e.strerror or e})')
                        continue
                    if not wanted(m.name):
                        continue
                    p = target(m.name)
                    if not p:
                        warnings.append(f'{m.name}: a name that has no place here - skipped')
                        continue
                    try:
                        if m.isdir():
                            os.makedirs(_long(p), exist_ok=True)
                            dirs.append((p, m.mtime))
                        elif m.issym():
                            os.makedirs(_long(os.path.dirname(p)), exist_ok=True)
                            if os.path.lexists(_long(p)):
                                os.remove(_long(p))
                            os.symlink(m.linkname, p)
                        elif m.isfile():
                            os.makedirs(_long(os.path.dirname(p)), exist_ok=True)
                            with open(_long(p + '.cmeta-part'), 'wb') as out:
                                shutil.copyfileobj(tf.extractfile(m), out, 1 << 20)
                            os.replace(_long(p + '.cmeta-part'), _long(p))
                            os.utime(_long(p), (m.mtime, m.mtime))
                        entries += 1
                    except OSError as e:
                        warnings.append(f'{p}: {e.strerror or e}')
                        try:
                            os.remove(_long(p + '.cmeta-part'))
                        except OSError:
                            pass
                    now = time.monotonic()
                    if con and now - last >= PROGRESS_EVERY:
                        last = now
                        print(f'    {label}: {entries:,} entries, {_size_text(counting.n)} of {_size_text(size)} read'
                              + (f' ({100 * counting.n / max(size, 1):.0f}%)' if not proc else ''), flush=True)
            for p, mtime in reversed(dirs):
                try:
                    os.utime(_long(p), (mtime, mtime))
                except OSError:
                    pass
            if proc and proc.wait() != 0:
                return self.cm.error(f'{os.path.basename(part)}: zstd ended with {proc.returncode}')
        except (tarfile.TarError, EOFError, ValueError) as e:
            return self.cm.error(f'{os.path.basename(part)} could not be read: {type(e).__name__}: {e}')
        finally:
            raw.close()
            if proc and proc.poll() is None:
                proc.kill()
        if con:
            print(f'    {label}: {entries:,} entries' + (f', {deleted:,} deleted' if deleted else '')
                  + (f', {len(warnings)} warnings (first: {warnings[0][:160]})' if warnings else '')
                  + f' in {int(time.monotonic() - t0)}s', flush=True)
        return {'return': 0, 'entries': entries, 'deleted': deleted, 'warnings': warnings}
