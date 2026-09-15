"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Run an rclone command against a plain SSH host, with no rclone.conf entry.

The remote is assembled on the fly in rclone's connection-string form

    :sftp:<remote path>   --sftp-ssh "ssh <ssh-target>"

which makes rclone shell out to the system ssh binary instead of using its own
SSH library. Everything ssh already knows - Host aliases, User, Port,
IdentityFile, ProxyJump, the running agent - then comes from ~/.ssh/config for
free, and no host or key is ever written into an rclone config file.

The assembled command is handed to task/cmd, which runs it with the terminal
attached, so --progress renders live and an ssh passphrase prompt still works.

See _desc.yaml for the CLI recipes and for why the remote is built this way.
"""

import os
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask

USAGE = 'usage: cx task run rclone-to-ssh <command> <local dir> <ssh-target>:<remote path> ' \
        '[flags] [-- <extra rclone flags>]  (e.g. "cxt rclone-to-ssh sync D:\\photos me@nas:/mnt/backup")'

# Values that turn a flag off when it is written with "=" (--progress=false).
# The bare forms (--progress / --no-progress / --progress-) already arrive as
# real booleans from the CLI parser.
FALSE_STRINGS = ['false', 'no', 'off', '0', 'none', '']


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,                    # cMeta context
            rclone_command: str = None,   # rclone command: sync, copy, move, bisync, check, ... (local -> remote)
            local_dir: str = None,        # local directory or file to push (default: the current directory)
            remote: str = None,           # "<ssh-target>:<remote path>", e.g. me@nas:/mnt/backup (split on the FIRST ":")
            whitelist: list = None,       # only these dirs/files are transferred (--whitelist=src/,docs/,README.md)
            whitelist_from: str = None,   # the same whitelist read from a file, one pattern per line
            blacklist: list = None,       # these dirs/files are never transferred (--blacklist=.venv/,.git/,build/)
            blacklist_from: str = None,   # the same blacklist read from a file, one pattern per line
            progress: bool = True,        # append --progress (on by default; turn off with --no-progress)
            resync: bool = None,          # append --resync (the first "bisync" run needs it);
                                          # implied by the "resync" command spelling
            mkdir: bool = None,           # create the remote dir before a resync (default: yes;
                                          # bisync errors out if either side is missing)
            unlock: bool = False,         # delete a stale bisync lock for this pair before running
                                          # (left behind when a previous run was interrupted)
            workdir: str = None,          # bisync working dir, where the lock and listings live
                                          # (default: rclone's own <cache dir>/bisync)
            ssh_options: str = None,      # extra flags for the ssh binary, e.g. --ssh_options="-p 2222 -i ~/.ssh/nas"
            env: dict = {},               # extra environment variables for the rclone process
            timeout: int = None,          # kill rclone after N seconds (default: no limit)
            unparsed: list = None,        # everything after "--" is quoted and appended to the rclone command
            install: bool = None,         # consumed by _desc.yaml: answers task/setup's "install rclone?" up front
            rclone_version: str = None,   # consumed by _desc.yaml: pin the rclone version to set up
    ):

        """
        Push a local directory to a plain SSH host with rclone, without an rclone.conf entry.

            cxt rclone-to-ssh sync D:\\photos me@nas:/mnt/backup/photos

        assembles and runs (through task/cmd):

            rclone sync "D:\\photos" :sftp:/mnt/backup/photos --sftp-ssh "ssh me@nas" --progress

        --whitelist keeps only the listed directories and files, --blacklist
        drops them; a trailing "/" means "this directory, recursively", and a
        blacklist carve-out beats the whitelist:

            cxt rclone-to-ssh sync . me@nas:/backup --blacklist=.venv/,.git/,build/

            rclone sync "." :sftp:/backup --sftp-ssh "ssh me@nas" \\
                   --exclude ".venv/**" --exclude ".git/**" --exclude "build/**" --progress

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **cmd** (str): The rclone command that was run.
                - **returncode** (int): rclone exit code.
                - **ssh_target** (str): The ssh target parsed out of `remote`.
                - **remote_path** (str): The remote path parsed out of `remote`.
        """

        self.logger.debug("RUNNING TASK rclone-to-ssh run")

        # Wall clock for the whole job - the remote mkdir and the transfer
        # together. rclone prints its own "Elapsed time" for the transfer only,
        # and only when --progress is on, so a --no-progress run otherwise
        # reports no timing at all.
        t_start = time.time()

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']

        space = '  ' * ctx_tasks['nested_call'] if verbose else ''

        quote_path = self.cm.utils.files.quote_path

        # Reported on EVERY exit path below, not just the happy one: a run that
        # died half way through - an unreachable host, a refused key - is
        # exactly when the duration is worth knowing. Returns the seconds so the
        # caller can put them in the result dict.
        def report_elapsed(what):
            elapsed = time.time() - t_start
            if con and not quiet:
                print ('')
                print (f'{space}ELAPSED: {self._format_elapsed(elapsed)}'
                       f'  (rclone-to-ssh: {what})')
            return elapsed

        ###########################################################################################
        # Check and normalize params

        if not rclone_command:
            return self.cm.error(f'rclone command (sync, copy, bisync, ...) is not set - {USAGE}')

        # "resync" is not an rclone command - rclone rejects it outright
        # ("unknown command \"resync\"") - it is bisync's first-run mode, spelled
        # `bisync --resync`. Accepting it as a command means the word you type
        # matches the thing you are doing, and the first run of a bisync pair
        # stops being two pieces of syntax to remember.
        #
        # An explicit --no-resync still wins: the param default is None, so
        # "not given" is distinguishable from "given as false", and someone who
        # writes both plainly wants a plain bisync.
        if rclone_command.strip().lower() == 'resync':
            rclone_command = 'bisync'
            if resync is None:
                resync = True

        if not remote:
            return self.cm.error(f'remote "<ssh-target>:<remote path>" is not set - {USAGE}')

        # Split on the FIRST ":" so that the remote path keeps any colon of its
        # own. An empty path is legal: ":sftp:" is the ssh login home directory.
        ssh_target, separator, remote_path = remote.partition(':')

        if not separator or not ssh_target:
            return self.cm.error(
                f'remote "{remote}" must be "<ssh-target>:<remote path>", e.g. me@nas:/mnt/backup - {USAGE}')

        if not local_dir:
            local_dir = '.'

        # Fail here rather than let rclone fail later: with "sync" a mistyped
        # source is the difference between a backup and an empty destination.
        if not os.path.exists(local_dir):
            return self.cm.error(f'local directory "{local_dir}" not found (cur dir: {os.getcwd()})')

        ###########################################################################################
        # Assemble the rclone command
        #   rclone <command> "<local dir>" :sftp:<remote path> --sftp-ssh "ssh <ssh-target>" <flags>

        # "qpath" is already quoted by task/setup when the path needs it
        rclone_path = ctx_tasks['global']['rclone']['qpath']

        ssh_cmd = f'ssh {ssh_options.strip()} {ssh_target}' if ssh_options else f'ssh {ssh_target}'

        cmd_parts = [
            rclone_path,
            rclone_command,
            quote_path(local_dir),
            quote_path(':sftp:' + remote_path),
            f'--sftp-ssh "{ssh_cmd}"',

            # NOT optional here, despite looking like a tuning knob. rclone
            # probes an sftp remote for a usable hash command by running
            # "ssh <target> md5sum" - with no file argument, so md5sum reads its
            # stdin and blocks forever. rclone normally survives that because it
            # caches the answer in rclone.conf, but ":sftp:" is an on-the-fly
            # remote it cannot write to ("Can't save config md5sum_command"), so
            # every single run re-probes and can hang: observed sitting at
            # "Transferred: 0 B / 0 B" for 7+ minutes with an idle
            # "ssh ... md5sum" child, where the same transfer takes 14s with
            # this flag. rclone then compares size+modtime, which is the normal
            # sftp default anyway.
            # To verify hashes instead, override it: -- --sftp-disable-hashcheck=false
            '--sftp-disable-hashcheck',
        ]

        # The whitelist/blacklist go out as rclone --filter rules, NOT as
        # --include/--exclude. rclone builds one rule list and adds every
        # --include before every --exclude no matter what order they appear in
        # on the command line, so an --exclude can never carve anything out of
        # an --include: whitelisting "cmeta/" and blacklisting "__pycache__/"
        # that way still copied all 168 __pycache__ files, in either order.
        # --filter keeps the order given and the first matching rule wins, which
        # is the semantics this task promises.
        #
        # Rules are always double-quoted: they contain a space after the +/-
        # sign, and their globs would otherwise be expanded by a POSIX shell
        # against the current directory before rclone ever saw them.
        r = self._filter_rules(whitelist, whitelist_from, blacklist, blacklist_from)
        if self.cm.catch_error(r): return r

        for rule in r['rules']:
            cmd_parts.append(f'--filter "{rule}"')

        # Passed through when set so that rclone and --unlock look in the SAME
        # place; left off otherwise so rclone keeps using its own default.
        if workdir:
            cmd_parts.append(f'--workdir {quote_path(workdir)}')

        if self._flag_is_on(progress, True):
            cmd_parts.append('--progress')

        if self._flag_is_on(resync, False):
            cmd_parts.append('--resync')

        cmd = ' '.join(cmd_parts)

        if con and verbose:
            print ('')
            print (f'{space}INFO: ssh target:  {ssh_target}')
            print (f'{space}INFO: remote path: {remote_path if remote_path else "(ssh login home directory)"}')

        ###########################################################################################
        # Drop a stale bisync lock.
        #
        # Interrupt a bisync (Ctrl-C, a dropped link, a killed shell) and its
        # lock file survives, so the next run refuses to start:
        #
        #   NOTICE: Failed to bisync: prior lock file found: <workdir>/<session>.lck
        #   Tip: ... either is still running or was interrupted before completion.
        #   If you're SURE ... delete the lock file with the following command
        #
        # rclone has no --unlock of its own, so this does what that advice says.
        # It is deliberately opt-in: the lock also protects against a second
        # bisync of the same pair running concurrently, and only you know that
        # the other run is dead rather than busy.
        #
        # Non-destructive alternatives, both rclone's own and reachable through
        # "--": "-- --max-lock 2m" expires locks older than a duration
        # (minimum 2m) instead of deleting them, and "-- --recover" resumes an
        # interrupted run without needing a full resync.

        if rclone_command == 'bisync' and self._flag_is_on(unlock, False):
            r = self._unlock(workdir, remote_path, con, quiet, space)
            if self.cm.catch_error(r):
                report_elapsed('unlock failed')
                return r

        ###########################################################################################
        # Seed the remote directory for a resync.
        #
        # bisync refuses to start unless BOTH sides already exist - unlike sync
        # and copy it never creates one:
        #
        #   ERROR : error reading source root directory: directory not found
        #   ERROR : Bisync critical error: directory not found
        #   ERROR : Bisync aborted. Must run --resync to recover.
        #
        # That last line is generic and actively misleading, since --resync is
        # exactly what was being run. And seeding a pair is precisely the moment
        # the remote does not exist yet, so "resync" creates it first.
        #
        # "rclone mkdir" is idempotent (exit 0 on a directory already there), so
        # this stays a no-op for every later resync of an established pair.
        # Turn it off with --no-mkdir.

        if rclone_command == 'bisync' and self._flag_is_on(resync, False) \
                and self._flag_is_on(mkdir, True):

            mkdir_cmd = ' '.join([
                rclone_path,
                'mkdir',
                quote_path(':sftp:' + remote_path),
                f'--sftp-ssh "{ssh_cmd}"',
                '--sftp-disable-hashcheck',
            ])

            # No "unparsed" here: those flags are meant for the transfer, and a
            # mkdir has no use for --transfers or --dry-run. It also must not
            # inherit --progress or the filters.
            rm = self.cm.access({
                'category': self.category_alias + ',' + self.category_uid,
                'command': 'run',
                'arg1': 'cmd,c9ba0a88df394d7f',
                'ctx': ctx,
                'cmd': mkdir_cmd,
                'env': env,
                'timeout': timeout,
                'con': con,
                'quiet': quiet,
                'verbose': verbose,
                'text_cmd': 'MKDIR (remote, so --resync has both sides):',
                'print_extra_line': True,
            })
            if self.cm.catch_error(rm):
                report_elapsed('remote mkdir failed')
                return rm

        ###########################################################################################
        # Run it through task/cmd, which appends "unparsed" (everything the user
        # put after "--") and runs with the terminal attached

        ii = {'category': self.category_alias + ',' + self.category_uid,
              'command': 'run',
              'arg1': 'cmd,c9ba0a88df394d7f',
              'ctx': ctx,
              'cmd': cmd,
              'unparsed': unparsed,
              'env': env,
              'timeout': timeout,
              'con': con,
              'quiet': quiet,
              'verbose': verbose,
              'text_cmd': 'RUN:',
              'print_extra_line': True,
        }

        rx = self.cm.access(ii)

        elapsed = report_elapsed(rclone_command)

        if self.cm.catch_error(rx): return rx

        return {
            'return': 0,
            'cmd': rx.get('cmd', cmd),
            'returncode': rx.get('returncode', 0),
            'ssh_target': ssh_target,
            'remote_path': remote_path,
            'elapsed': round(elapsed, 3),
            'self_time_rclone_to_ssh': round(elapsed, 3),
        }


    ############################################################
    def _filter_rules(self,
                      whitelist = None,
                      whitelist_from = None,
                      blacklist = None,
                      blacklist_from = None,
    ):
        """
        Build the ordered rclone --filter rule list for a whitelist/blacklist pair.

        Blacklist rules come first: rclone stops at the first matching rule, so
        a carve-out has to be seen before the whitelist entry that would
        otherwise pull the same path in. Together they read as "everything in
        the whitelist except the blacklist".

        A closing "- **" is appended whenever the whitelist contributed anything.
        rclone adds that implicitly behind --include, but NOT behind a "+"
        --filter rule - without it every unlisted file would still be
        transferred (measured: 7705 files instead of 159).

        Args:
            whitelist: Entries to keep (str, list or None).
            whitelist_from: File of entries to keep, or None.
            blacklist: Entries to drop (str, list or None).
            blacklist_from: File of entries to drop, or None.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **rules** (list): rclone --filter rules, e.g. ['- .git/**', '+ src/**', '- **'].
        """

        rules = []
        keeps = 0

        for entries, from_file, label, sign in (
                (blacklist, blacklist_from, 'blacklist', '-'),
                (whitelist, whitelist_from, 'whitelist', '+'),
        ):
            patterns = []

            if from_file:
                r = self._read_filter_file(from_file, label + '_from')
                if r['return'] > 0: return r

                patterns += r['patterns']

            patterns += self._filter_patterns(entries)

            for pattern in patterns:
                rules.append(f'{sign} {pattern}')

            if sign == '+':
                keeps = len(patterns)

        if keeps:
            rules.append('- **')

        return {'return': 0, 'rules': rules}


    ############################################################
    def _read_filter_file(self, path, label):
        """
        Read a whitelist/blacklist file - one entry per line.

        Blank lines and "#" comments are skipped and the same trailing-"/"
        shorthand as the inline form applies. Unlike the inline form a line is
        never split on commas, so this is the place for a brace pattern such as
        "*.{jpg,png}".

        Args:
            path (str): Path to the file.
            label (str): Param name to quote in an error message.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **patterns** (list): One pattern per meaningful line.
        """

        if not os.path.isfile(path):
            return self.cm.error(f'{label} file "{path}" not found (cur dir: {os.getcwd()})')

        with open(path, encoding='utf-8') as f:
            lines = [x for x in (line.strip() for line in f)
                     if x != '' and not x.startswith('#')]

        return {
            'return': 0,
            'patterns': [x + '**' if x.endswith('/') else x for x in lines],
        }


    ############################################################
    @staticmethod
    def _filter_patterns(entries):
        """
        Normalize a whitelist or blacklist into rclone filter patterns.

        rclone filters match FILES, never directories, so a bare directory name
        selects nothing at all - the recursive form is "<dir>/**". Ending an
        entry with "/" asks for exactly that and is expanded here, so

            --whitelist=src/,docs/,README.md
            --blacklist=.venv/,.git/

        become --include "src/**" --include "docs/**" --include "README.md"
        and    --exclude ".venv/**" --exclude ".git/**".

        Everything else is passed to rclone untouched, so its full pattern
        syntax stays available - in particular a leading "/" anchors a pattern
        to the top of the transfer ("/src/**" is only the top-level src), while
        an unanchored pattern matches at any depth.

        Args:
            entries: A comma-separated string, a list of entries, or None.

        Returns:
            list: rclone filter patterns, in the order they were given.
        """

        if not entries:
            return []

        if isinstance(entries, str):
            entries = [entries]

        patterns = []

        for entry in entries:
            # Splitting every entry on "," makes both CLI spellings behave the
            # same: --whitelist=a,b,c (one string) and --whitelist,=a,b,c (a list
            # the CLI already split) both end up as three patterns.
            for item in str(entry).split(','):
                item = item.strip()

                if item == '':
                    continue

                # "src/" -> "src/**": the directory's contents, recursively
                patterns.append(item + '**' if item.endswith('/') else item)

        return patterns


    ############################################################
    def _unlock(self, workdir, remote_path, con, quiet, space):
        """
        Delete the bisync lock file for this path pair, if one is lying around.

        bisync names its session after BOTH paths, joined by ".." and with the
        path separators and the colon flattened to "_" - "@" and "-" survive:

            <workdir>/<path1>..<path2>.lck
            c__Temp_x_ctuninglabs@cmeta-aops..c__Temp_y_dst-1.lck

        Only the REMOTE half is matched here. That half is the literal
        ":sftp:<remote path>" string this task builds, so it is known exactly,
        whereas the local half is whatever rclone made of the path it was given
        (relative or absolute, forward or back slashes). Matching on the end of
        the name identifies the pair without having to reproduce rclone's
        handling of the local side.

        Args:
            workdir (str): Explicit bisync workdir, or None for rclone's default.
            remote_path (str): The remote path, without the ":sftp:" prefix.
            con (bool): Print to the console.
            quiet (bool): Suppress the console output.
            space (str): Indent for nested verbose output.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **unlocked** (list): Lock files that were deleted.
        """

        import glob

        lock_dir = workdir if workdir else self._default_bisync_workdir()

        if not os.path.isdir(lock_dir):
            if con and not quiet:
                print (f'{space}UNLOCK: no bisync working dir yet ({lock_dir}) - nothing to unlock')
            return {'return': 0, 'unlocked': []}

        suffix = '..' + self._norm_for_lock(':sftp:' + remote_path) + '.lck'

        removed = []

        for path in sorted(glob.glob(os.path.join(lock_dir, '*.lck'))):
            if not os.path.basename(path).endswith(suffix):
                continue
            try:
                os.remove(path)
            except OSError as e:
                return self.cm.error(f'could not delete lock file "{path}": {e}')
            removed.append(path)

        if con and not quiet:
            if removed:
                for path in removed:
                    print (f'{space}UNLOCK: deleted stale bisync lock {path}')
            else:
                print (f'{space}UNLOCK: no lock file for this pair in {lock_dir}')

        return {'return': 0, 'unlocked': removed}


    ############################################################
    @staticmethod
    def _default_bisync_workdir():
        """
        Where rclone keeps bisync state when --workdir is not given.

        It is "<rclone cache dir>/bisync", and the cache dir follows the
        platform: %LOCALAPPDATA%\rclone on Windows, else $XDG_CACHE_HOME or
        ~/.cache. Computed rather than read back from "rclone config paths" so
        that no extra process has to be started to find out.

        Returns:
            str: Path to the default bisync working directory.
        """

        local_app_data = os.environ.get('LOCALAPPDATA')

        if os.name == 'nt' and local_app_data:
            base = os.path.join(local_app_data, 'rclone')
        else:
            cache = os.environ.get('XDG_CACHE_HOME')
            if not cache:
                cache = os.path.join(os.path.expanduser('~'), '.cache')
            base = os.path.join(cache, 'rclone')

        return os.path.join(base, 'bisync')


    ############################################################
    @staticmethod
    def _norm_for_lock(path):
        """
        Flatten a path the way bisync does when naming its session files.

        Only the separators and the drive colon collapse to "_"; everything
        else, "@" and "-" included, is left alone - measured against rclone
        1.75 with a path holding both.

        Args:
            path (str): A path as handed to rclone.

        Returns:
            str: The flattened form used in the lock/listing file names.
        """

        for ch in (':', '/', '\\'):
            path = path.replace(ch, '_')

        return path


    ############################################################
    @staticmethod
    def _format_elapsed(seconds):
        """
        Render a duration the way rclone does, so the two lines read alike.

        Seconds alone below a minute, then minutes, then hours - a bare
        "3843.7s" is not a number anyone reads as "just over an hour".

        Args:
            seconds (float): Elapsed wall-clock seconds.

        Returns:
            str: e.g. "12.3s", "2m 5.1s", "1h 4m 3.7s".
        """

        # Round BEFORE splitting, or 59.96s renders as "60.0s" instead of
        # rolling over into "1m 0.0s".
        total = round(max(0.0, float(seconds)), 1)

        hours, rest = divmod(total, 3600)
        minutes, secs = divmod(rest, 60)

        if hours:
            return f'{int(hours)}h {int(minutes)}m {secs:.1f}s'
        if minutes:
            return f'{int(minutes)}m {secs:.1f}s'
        return f'{secs:.1f}s'


    ############################################################
    @staticmethod
    def _flag_is_on(value, default):
        """
        Normalize a boolean CLI flag.

        "--progress" and "--no-progress" arrive as real booleans, but
        "--progress=false" arrives as the string "false", so both are handled.

        Args:
            value: The raw param value (bool, str or None).
            default (bool): Result when the param was not set at all.

        Returns:
            bool: True if the flag should be appended to the command.
        """

        if value is None:
            return default

        if isinstance(value, bool):
            return value

        return str(value).strip().lower() not in FALSE_STRINGS
