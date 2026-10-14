"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import copy
import json
import re

from cmeta.category import InitCategory

# Where a recursive search ("**") must not start: a filesystem root (it would walk the whole disk and,
# on Linux, /proc and /sys, which never end) and the pseudo file systems themselves
UNSAFE_SEARCH_ROOTS = ('/proc', '/sys', '/dev', '/run')

# This category, for the commands that list its artifacts
TOOL_CATEGORY = 'tool,c393ba5c6fa14f66'

# The order of the report of "cx tool check-updates": what needs a look first
UPDATE_STATUS_ORDER = ('behind', 'unknown', 'error', 'ahead', 'current', 'no pin')


def glob_pattern_is_safe(pattern):
    """
    Whether a search pattern may be expanded: a pattern without a recursive "**" always; one with it only
    when the folder the recursion starts from is a real folder below a filesystem root (not "/", not "C:\\",
    not /proc, /sys, /dev, /run, not "/*" - every folder of a disk). A tool's "{{...home}}/**" becomes "//**"
    when the home of a distribution's compiler resolves to "/".

    Only a whole "**" component recurses (as Python's glob reads it): "C:\\Program Files**\\OpenSSL**\\**"
    starts its recursion in the OpenSSL folders, so a wildcard in the folders before it is expanded (one
    level each, cheap) and every folder it gives is checked. Before (0.42.0 - 0.46.0) the pattern was judged
    by the text before its first wildcard, "C:\\", and skipped: lib-openssl, openssl, llama-cpp,
    microsoft.windows.adk and windirstat were never found in their Program Files folders.
    """
    import glob

    m = re.search(r'(?:^|(?<=[\\/]))\*\*(?=[\\/]|$)', pattern)
    if m is None:
        return True

    def is_root_or_pseudo(folder):
        posix = os.path.normpath(folder).replace('\\', '/').rstrip('/') if folder else ''
        if posix in ('', '.') or re.fullmatch(r'[A-Za-z]:', posix):     # "/", "//" or a drive root, on any OS
            return True
        return any(posix == root or posix.startswith(root + '/') for root in UNSAFE_SEARCH_ROOTS)

    base = pattern[:m.start()].rstrip('\\/')
    if is_root_or_pseudo(base):
        return False

    # The first folder below the root must name something: "/*/**" or "C:\\?*\\**" is the whole disk
    first = re.sub(r'^[A-Za-z]:', '', base.replace('\\', '/')).lstrip('/').split('/')[0]
    if re.sub(r'\[[^\]]*\]|[*?]', '', first) == '':
        return False

    if not any(c in base for c in '*?['):
        return True

    return not any(is_root_or_pseudo(folder) for folder in glob.glob(base))


class Category(InitCategory):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def test_(self, ctx, arg1=None, flag1=False):
        """
        """

        self.logger.debug("RUNNING API v1 test_")

        print (f'arg1={arg1}')
        print (f'flag1={flag1}')

        return {'return':0}

    ############################################################
    def test2(self, params):
        """
        """

        self.logger.debug("RUNNING API v1 test2")

        import json
        print (json.dumps(params, indent=2))

        return {'return':0}

    ############################################################
    def find_path_(
            self, 
            ctx, 
            path = None, 
            paths = None, 
            space = None, 
            context={}, 
            desc={}, 
            tool_name=None,
        ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING tool find_path v1")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx.setdefault('tasks', {})

        if space is None:
            nested_call = ctx_tasks.setdefault('nested_call', 0)
            space = '  ' * nested_call if verbose else ''

        if not paths:
            paths = []

        # Resolve exe_path
        found_paths = []

        if not path and 'path' in desc:
            path = desc['path']

            r = self.cm.utils.common.expand_string(path, context)
            if self.cm.catch_error(r): return r
            path = r['string']

        if path and os.path.isfile(path):
            found_paths = [path]

        else:
            if path and not os.path.isdir(path):
                return {'return':1, 'error': f'tool "{path}" doesn\'t exist'}

            if type(paths) == str:
                paths = paths.split(os.pathsep)

            if path:
                search_paths = [path]
            else:
                search_paths = paths.copy()

            if len(search_paths) == 0:
                search_paths = [os.getcwd()]

                env_paths = os.environ.get('PATH','').strip()
                if env_paths != '':
                    search_paths += env_paths.split(os.pathsep)

            search_paths = self._drop_merged_usr_aliases(search_paths)

            if tool_name:
                names = [tool_name]
            else:
                names = desc.get('names', [])
                if not names:
                    name = desc.get('name')
                    if name:
                        names = [name]

            for name in names:

                r = self.cm.utils.common.expand_string(name, context)
                if self.cm.catch_error(r): return r
                name = r['string']

                if con and verbose:
                    print ('')
                    print (f'{space}SEARCH: file {name} ...')

                find_without_ext = False
                if name.endswith('.'):
                    find_without_ext = True
                    name = name[:-1]

                for spath in search_paths:
                    spath = spath.strip()

                    if not spath:
                        continue

                    candidate = os.path.join(spath, name)

                    # Handle wildcards in name
                    if '*' in spath or '?' in spath or '*' in name or '?' in name:
                        import glob

                        pattern = os.path.join(spath, name)

                        # A recursive search from a filesystem root or a pseudo file system never ends
                        # (/proc, /sys): such a pattern comes from a tool whose home resolved to "/"
                        # (a distribution's /usr/bin/clang) and is skipped
                        if not glob_pattern_is_safe(pattern):
                            if verbose:
                                print (f'{space}SEARCH: skipping "{pattern}": a recursive search from a filesystem root')
                            continue

                        matches = glob.iglob(pattern, recursive = True)
                  
                        for match in matches:
                            if os.path.isfile(match) and match not in found_paths:
                                to_add = True

                                if find_without_ext:
                                    if os.path.splitext(match)[1] != "":
                                        to_add = False

                                if to_add:
                                    match = os.path.normpath(match)

                                    for _match in found_paths:
                                        if os.path.normcase(_match) == os.path.normcase(match):
                                            to_add = False
                                            break

                                    if to_add:
                                        found_paths.append(match)

                    elif os.path.isfile(candidate):
                        candidate = os.path.normpath(candidate)

                        to_add = True
                        for _candidate in found_paths:
                            if os.path.normcase(_candidate) == os.path.normcase(candidate):
                                to_add = False
                                break

                        if to_add:
                            found_paths.append(candidate)

        return {'return':0, 'found_paths': found_paths}

    ############################################################
    def _drop_merged_usr_aliases(self, search_paths):
        """
        Drop the merged-/usr aliases from a list of directories to search.

        On Ubuntu, Debian, Fedora, Arch and others /bin and /sbin (and on some
        /usr/sbin) are symlinks into /usr, and all of them are on PATH - so
        every tool there was found two to four times, and `cx tool setup git`
        on a fresh machine asked which of /bin/git and /usr/bin/git, the same
        file, to use.

        Only these system aliases are dropped, and only when the directory
        they point to is searched anyway. Any other symlinked directory stays,
        because there the two paths mean different things: /usr/local/cuda
        follows the next CUDA update while /usr/local/cuda-13.0 does not, and
        a Homebrew opt/ path survives an upgrade that removes its Cellar/
        version. Several real versions of a tool still ask which one to use;
        -q (quiet) takes the default, which is what runs with no terminal need.
        """

        if os.name == 'nt':
            return search_paths

        searched = set(os.path.normpath(s.strip()) for s in search_paths
                       if s.strip() and '*' not in s and '?' not in s)

        # An alias goes only when its real directory is searched under its own
        # name - never both of two aliases that merely point at each other.
        aliases = set()
        for alias in ('/bin', '/sbin', '/usr/sbin'):
            if alias in searched and os.path.islink(alias):
                real = os.path.realpath(alias)
                if real != alias and real in searched:
                    aliases.add(alias)

        if not aliases:
            return search_paths

        return [s for s in search_paths
                if not s.strip() or os.path.normpath(s.strip()) not in aliases]

    ############################################################
    def setup(self, params):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING tool api v1 setup")

        p = self._prepare_input_from_params(params, base = False)

        p['category'] = self.cmeta['uses_categories']['task']
        p['command'] = 'run'
        p['name'] = params.get('arg1')
        p['arg1'] = self.cmeta['uses_artifacts']['tool::setup']

        return self.cm.access(p)

    ############################################################
    def check_updates_(self,
                       ctx: dict,
                       arg1: str = None,                 # the tools to check, comma-separated (else every tool with a default_version)
                       all: bool = False,                # also the tools without a default_version (their newest version only)
                       refresh_versions: bool = False,   # ask the channels and upstream again instead of the cached lookups
                       output: str = None,               # write the report to this file: .json as JSON, anything else as Markdown
    ):
        """
        The tools behind upstream: for each tool, the version cMeta installs when none is asked for (known: the
        default_version of its _desc.yaml) against the newest one its channel or upstream offers (latest: the
        lookup of "cx tool setup <tool> --versions", cached per tool for versions_ttl_hours). A report only:
        nothing is installed or changed - moving a pin stays a decision, with a test.

            cx tool check-updates                      # every tool with a default_version
            cx tool check-updates yq,jq,helm           # these tools
            cx tool check-updates --all                # every tool, the ones without a pin too
            cx tool check-updates --refresh_versions   # ask again, not the cached answers
            cx tool check-updates --output=updates.md  # the report as Markdown (.json: as JSON)

        Returns:
            dict: return, tools (a row per tool: tool, known, latest, latest_source, status - behind, current,
                  ahead, unknown, no pin or error -, step - major, minor or patch for a pin behind -, notes,
                  from_cache, asked_at), summary (status -> count, and behind_<step> -> count)
        """

        con = ctx['control'].get('con', False)

        # The tools: the named ones, else every tool artifact with a default_version (every one with --all)
        if arg1:
            names = list(dict.fromkeys(n.strip() for n in str(arg1).split(',') if n.strip()))
        else:
            r = self.cm.access({'category': TOOL_CATEGORY, 'command': 'find', 'con': False})
            if self.cm.catch_error(r): return r

            names = []
            for a in sorted(r.get('artifacts', []), key = lambda a: a['cmeta_ref_parts']['artifact_alias']):
                alias = a['cmeta_ref_parts']['artifact_alias']
                if alias in names:
                    continue
                if not all:
                    rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(a['path'], '_desc'))
                    if rd['return'] > 0 or not (rd.get('data') or {}).get('default_version'):
                        continue
                names.append(alias)

        width = max([len(n) for n in names] + [4])
        line = lambda t, k, l, s: f'{t:<{width}}  {k:<14}  {l:<14}  {s}'

        if con:
            print ('')
            print (line('TOOL', 'KNOWN', 'NEWEST', 'STATUS'))

        # One quiet setup per tool in this run's context: the host, the runner and git are set up once
        rows = []
        for name in names:
            saved = dict(ctx['control'])
            r = self.cm.access({'category': self.cmeta['uses_categories']['task'], 'command': 'run',
                                'arg1': self.cmeta['uses_artifacts']['tool::setup'], 'name': name,
                                'check_update': True, 'refresh_versions': bool(refresh_versions),
                                'ctx': ctx, 'con': False, 'quiet': True})
            ctx['control'].clear()
            ctx['control'].update(saved)

            if r['return'] > 0:
                row = {'tool': name, 'known': None, 'latest': None, 'latest_source': None, 'newest': None, 'limit': None,
                       'limit_text': None,
                       'status': 'error', 'step': None, 'notes': [str(r.get('error') or '').strip()],
                       'from_cache': None, 'asked_at': None}
            else:
                row = {k: r.get(k) for k in ('known', 'latest', 'latest_source', 'newest', 'limit', 'limit_text',
                                             'status', 'step', 'notes', 'from_cache', 'asked_at')}
                row['tool'] = name
            rows.append(row)

            if con:
                status = row['status'] + (f' ({row["step"]})' if row.get('step') else '')
                print (line(name, row.get('known') or '-', row.get('latest') or '-', status))

        # The summary, and the notes of the tools whose newest version is not known
        summary = {}
        for row in rows:
            summary[row['status']] = summary.get(row['status'], 0) + 1
            if row.get('step'):
                summary['behind_' + row['step']] = summary.get('behind_' + row['step'], 0) + 1

        if con:
            print ('')
            parts = [f'{summary[s]} {s}' + (' (' + ', '.join(f'{summary["behind_" + p]} {p}' for p in ('major', 'minor', 'patch')
                                                            if summary.get('behind_' + p)) + ')' if s == 'behind' else '')
                     for s in UPDATE_STATUS_ORDER if summary.get(s)]
            print (f'{len(rows)} tool{"s" if len(rows) != 1 else ""}: ' + ', '.join(parts))
            for row in rows:
                if row.get('limit'):
                    print (f'  {row["tool"]}: the newest one, {row.get("newest")}, is {row.get("limit_text")}')
            for row in rows:
                if row['status'] in ('unknown', 'error') and row.get('notes'):
                    print (f'  {row["tool"]}: {"; ".join(n for n in row["notes"] if n)}')

        result = {'return': 0, 'tools': rows, 'summary': summary}

        if output:
            if str(output).lower().endswith('.json'):
                text = json.dumps(result, indent = 2) + '\n'
            else:
                ordered = sorted(rows, key = lambda r: (UPDATE_STATUS_ORDER.index(r['status'])
                                                        if r['status'] in UPDATE_STATUS_ORDER else len(UPDATE_STATUS_ORDER), r['tool']))
                text = '\n'.join(['# Tools against their newest versions', '',
                                  '| Tool | Known | Newest | Status | Source | Limit of latest |', '|---|---|---|---|---|---|'] +
                                 [f'| {r["tool"]} | {r.get("known") or "-"} | {r.get("latest") or "-"} | '
                                  f'{r["status"]}{" (" + r["step"] + ")" if r.get("step") else ""} | {r.get("latest_source") or "-"} | '
                                  f'{(str(r.get("newest")) + " " + r["limit_text"]) if r.get("limit_text") else "-"} |'
                                  for r in ordered]) + '\n'
            try:
                with open(output, 'w', encoding = 'utf-8') as f:
                    f.write(text)
            except OSError as e:
                return self.cm.error(f'the report could not be written to "{output}": {e}')

            result['output'] = os.path.abspath(output)
            if con:
                print (f'cMeta info: the report is in {result["output"]}')

        return result

    ############################################################
    def run(self, params):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING tool api v1 run")

        ctx = params['ctx']

        p = self._prepare_input_from_params(params)

        unparsed = p.pop('unparsed', [])

        # Setup tool
        p.update({'category': self.cmeta['uses_categories']['task'],
                  'command': 'run',
                  'ctx': ctx,
        })

        pp = copy.deepcopy(p)

        p['arg1'] = self.cmeta['uses_artifacts']['tool::setup']
        p['name'] = params.get('arg1')

        r = self.cm.access(p)
        if self.cm.catch_error(r): return r

        # Setup may stop early without producing a CMD - for example
        # "--versions" only prints the available versions of a tool and
        # "--status" only reports the installed and the newest versions
        if 'cmd' not in r:
            return r

        cmd = r['cmd']

        for param in unparsed:
            param = param.strip()
            if ' ' in param and not param.startswith('"'):
                param = '"' + param + '"'

            cmd += ' ' + param

        # Clean some params (needed for "setup tool" task but not for "cmd" task)

        for k in ['detect','install', 'build', 'skip_install', 'skip_detect', 'skip_build',
                  'status', 'upgrade',
                  'name', 'tool_tags', 'tool_api_ver', 'tool_path', 'paths', 'with',
                  'version']:
            if k in pp:
                del(pp[k])

        env = pp.setdefault('env', {})

        fdlp = r.get('features',{}).get('paths',{}).get('found_dynamic_lib_paths')

        uname = ctx['tasks']['global']['host']['os']['uname']

        if fdlp:
            if uname == 'windows':
                env_dlib = env.setdefault('+PATH', [])
            elif uname == 'darwin':
                env_dlib = env.setdefault('+DYLD_LIBRARY_PATH', [])
            else:
                env_dlib = env.setdefault('+LD_LIBRARY_PATH', [])

            for f in reversed(fdlp):
                if f not in env_dlib:
                    env_dlib.insert(0, f)


        pp['arg1'] = self.cmeta['uses_artifacts']['tool::cmd']
        pp['cmd'] = cmd
        pp['ctx'] = ctx
        pp['print_extra_line'] = True

        r = self.cm.access(pp)
        self.cm.catch_error(r)

        return r

