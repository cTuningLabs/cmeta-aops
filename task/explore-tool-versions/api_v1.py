"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

explore-tool-versions: a tool tried at several versions - its setup in a fresh cache entry and, when asked, a program
run with it - and a verdict recorded per version (works or fails, the class of the error, the machine); then, from
the verdicts of one or many machines, the proposals they support: the next default_version of the tool, or a
limit of its "latest". The proposals are printed for a human to commit; the task never writes a tool's meta.
"""

import copy
import datetime
import json
import os
import platform
import re
import time

from task_c36be4b9314a45e0.api.ctask import InitCTask

SETUP_TASK = 'setup,a2f9b61079ce4333'
TEST_SESSION_TASK = 'test-session'
SESSION_ENV = 'CMETA_TEST_SESSION'
VERDICT_SCHEMA = 1

# The class of a failure from the words of its error, the first that matches; else the stage it failed at
ERROR_CLASSES = (
    ('not available', ('no matching', 'could not find a version', 'no versions of', 'not available',
                       'not found for version', '404')),
    ('checksum', ('sha256', 'sha-256', 'checksum')),
    ('download', ('download', 'http error', 'urlopen', 'timed out', 'connection', 'ssl')),
    ('build', ('compil', 'cmake', 'msbuild', 'ninja', 'linker', 'link error', 'build failed')),
)


def error_class(text, stage):
    """'not available', 'checksum', 'download', 'build', else the stage that failed ('setup' or 'program')."""
    low = str(text or '').lower()
    for name, words in ERROR_CLASSES:
        if any(word in low for word in words):
            return name
    return stage


def first_line(text, limit = 300):
    lines = [line.strip() for line in str(text or '').splitlines() if line.strip()]
    return (lines[0] if lines else '')[:limit]


def as_version(value):
    """A packaging Version, or None."""
    try:
        from packaging.version import Version
        return Version(str(value).strip())
    except Exception:
        return None


def excluded_by(version, limits):
    """The first limit of "latest" (latest_limits of the tool) whose exclude covers the version, or None."""
    v = as_version(version)
    if v is None:
        return None
    from packaging.specifiers import SpecifierSet
    for limit in limits or []:
        try:
            if SpecifierSet(str(limit.get('exclude'))).contains(v, prereleases = True):
                return limit
        except Exception:
            continue
    return None


def entry_uid(path):
    """The UID of a cache entry from its folder (task--setup--<tool>--<uid>), or None."""
    base = os.path.basename(os.path.normpath(path)) if path else ''
    uid = base.rsplit('--', 1)[-1] if '--' in base else ''
    return uid if re.fullmatch(r'[0-9a-f]{16}', uid) else None


def this_host():
    return {'uname': platform.system().lower(), 'arch': platform.machine().lower(), 'os': platform.platform(),
            'hostname': platform.node(), 'python': platform.python_version()}


def chosen_versions(info, versions = None, last = None):
    """
    The versions to try, each with why (a dict, in order), from info - the result of "cx tool setup <tool>
    --versions": the ones given (--versions; the words known and latest go to the setup as they are), else the
    <last> newest released versions the tool lists (its cmd_get_versions), else known (its default_version),
    latest (the newest version "latest" may take) and the newest one when a limit of latest excludes it.
    """
    if versions:
        return {v: 'asked' for v in dict.fromkeys(v.strip() for v in str(versions).split(',') if v.strip())}

    if last:
        listed = sorted({v for v in info.get('versions') or [] if as_version(v) is not None and not as_version(v).is_prerelease},
                        key = as_version, reverse = True)
        return {v: f'#{i + 1} newest of {len(listed)} listed' for i, v in enumerate(listed[:int(last)])}

    chosen = {}
    for version, why in ((info.get('known'), 'known'), (info.get('latest'), 'latest'),
                         (info.get('newest') if info.get('limit') else None, 'newest, excluded from latest')):
        if version:
            chosen[version] = (chosen[version] + ', ' + why) if version in chosen else why
    return chosen


def evidence_of(verdicts):
    """Per tool and version (the one obtained, else asked): the machines it worked on, and the ones it failed on
    with the class of the error - what --promote decides from."""
    table = {}
    for v in verdicts:
        host = v.get('host') or {}
        where = (host.get('uname') or '?') + (f' ({host["hostname"]})' if host.get('hostname') else '')
        row = table.setdefault(v['tool'], {}).setdefault(v.get('obtained') or v.get('version'), {'works': set(), 'fails': set()})
        if v.get('works'):
            row['works'].add(where)
        else:
            cls = v.get('error_class')
            if cls in (None, 'setup', 'program'):
                cls = error_class(v.get('error'), cls or v.get('stage') or 'setup')
            row['fails'].add(f'{where}: {cls}')
    return {tool: {version: {'works': sorted(row['works']), 'fails': sorted(row['fails'])} for version, row in rows.items()}
            for tool, rows in table.items()}


def read_verdicts(sources):
    """Every verdict of the JSONL files named (a folder: its *.jsonl files, recursively)."""
    files = []
    for source in [s.strip() for s in str(sources or '').split(',') if s.strip()]:
        if os.path.isdir(source):
            for folder, _, names in os.walk(source):
                files += [os.path.join(folder, n) for n in sorted(names) if n.endswith('.jsonl')]
        else:
            files.append(source)

    verdicts = []
    for path in files:
        with open(path, encoding = 'utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    record = json.loads(line)
                    if isinstance(record, dict) and record.get('tool') and record.get('version'):
                        verdicts.append(record)
    return verdicts, files


def proposals_of(verdicts, descs, min_os = 2, today = None):
    """
    What the verdicts support, per tool (descs: tool -> its _desc.yaml as a dict):
      - default_version: the newest version obtained that works wherever it was tried, on at least min_os
        operating systems, when it is newer than the tool's default_version (first: the tool had none);
      - latest_limits: a version newer than default_version that failed somewhere for a reason other than "not
        available" and that no limit excludes yet, excluded with the class and the first line of its error, and
        today's date;
      - not available: a version newer than default_version that the channel of some machine does not offer (an
        older uv, a missing release asset) and that did not fail otherwise - a note, not a limit: "latest" there
        never takes a version the channel does not list.
    A verdict counts by the version obtained (the one asked for when nothing was obtained). A failure that the known
    version (default_version) has too, on the same operating system and with the same class of error, says that the
    machine cannot run the tool at all (Ansible on Windows, a missing system library, no NPU), not that the newer
    version is worse: it is neither a limit nor a reason to hold the newer version back.
    """
    today = today or datetime.date.today().isoformat()
    proposals = []

    def classify(r):
        # A generic class (the stage) is read again from the error: verdicts made before a better classifier gain from it
        if not r.get('works') and r.get('error_class') in (None, 'setup', 'program'):
            r['error_class'] = error_class(r.get('error'), r.get('error_class') or r.get('stage') or 'setup')

    by_tool = {}
    for v in verdicts:
        version = v.get('obtained') or v.get('version')
        by_tool.setdefault(v['tool'], {}).setdefault(version, []).append(v)

    for tool in sorted(by_tool):
        desc = descs.get(tool) or {}
        known = desc.get('default_version')
        known_v = as_version(known) if known else None
        limits = desc.get('latest_limits') or []
        if isinstance(limits, dict):
            limits = [limits]

        # The failures of the known version: (operating system, class of the error)
        known_fails = set()
        for version, runs in by_tool[tool].items():
            if known_v is not None and as_version(version) == known_v:
                for r in runs:
                    classify(r)
                    if not r.get('works'):
                        known_fails.add((r.get('host', {}).get('uname'), r.get('error_class')))

        candidates = []
        for version, runs in by_tool[tool].items():
            v = as_version(version)
            if v is None or (known_v is not None and v <= known_v):
                continue
            ok = sorted({r.get('host', {}).get('uname') for r in runs if r.get('works')} - {None})
            for r in runs:
                classify(r)
            bad = [r for r in runs if not r.get('works')
                   and (r.get('host', {}).get('uname'), r.get('error_class')) not in known_fails]
            broken = [r for r in bad if r.get('error_class') != 'not available']
            where = lambda rs: ', '.join(sorted({r.get('host', {}).get('uname') or '?' for r in rs}))
            if broken:
                if not excluded_by(version, limits):
                    worst = broken[0]
                    proposals.append({'tool': tool, 'change': 'latest_limits', 'version': version,
                                      'exclude': f'=={version}',
                                      'reason': f'{worst.get("error_class")} on {where(broken)}: {worst.get("error") or "-"}',
                                      'since': today, 'evidence': len(runs)})
            elif bad:
                # Which machines: the same OS can offer it on one and not on another (an older uv there)
                hosts = lambda rs: ', '.join(sorted({(r.get('host', {}).get('uname') or '?') +
                                                     (f" ({r['host']['hostname']})" if r.get('host', {}).get('hostname') else '')
                                                     for r in rs}))
                proposals.append({'tool': tool, 'change': 'not available', 'version': version, 'on': hosts(bad),
                                  'error': bad[0].get('error'), 'works_on': ok, 'evidence': len(runs)})
            elif len(ok) >= min_os and not v.is_prerelease:
                candidates.append((v, version, ok, len(runs)))

        if candidates:
            v, version, ok, n = max(candidates)
            proposals.append({'tool': tool, 'change': 'default_version', 'from': known, 'to': version,
                              'works_on': ok, 'evidence': n, 'first': not known})

    return proposals


class CTask(InitCTask):
    """
    A tool tried at several versions, or the proposals of the verdicts (--promote).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)

    ############################################################
    def run(self,
            ctx: dict,
            tool: str = None,               # the tool to try (its alias)
            versions: str = None,           # the versions to try, comma-separated: numbers and the words known, latest
            last: int = None,               # else the newest <last> versions the tool publishes
            refresh_versions: bool = False, # ask the channel and upstream again instead of the cached lookup
            program: str = None,            # a program to run with each version (cx program run <program>)
            use_key: str = None,            # the storage key of the tool in that program (default: the tool's alias)
            keep: bool = False,             # keep the cache entries of the setups (removed by default)
            output: str = None,             # the verdicts file (JSONL; default explore-tool-versions-<tool>-<host>-<stamp>.jsonl here)
            promote: bool = False,          # instead: read verdicts and print the proposals they support
            verdicts: str = None,           # with --promote: the JSONL files or folders of verdicts, comma-separated
            min_os: int = 2,                # with --promote: the operating systems a version must work on to become known
    ):
        """
        Without --promote: for each version, "cx tool setup <tool> --version=<version> --new" and, with --program,
        "cx program run <program> --use.<use_key>.version=<version>" (the --use words of this command line go to
        it too); a verdict line per version in the verdicts file, a table, the file attached to the test session
        of the shell (CMETA_TEST_SESSION). The run succeeds whatever the verdicts say.
        With --promote: the evidence of the verdicts per tool, version and machine (evidence_of), then the proposals
        they support (proposals_of), as YAML lines to put in the tools' _desc.yaml.
        """

        con = ctx['control'].get('con', False)

        if promote:
            return self.promote(ctx, con, verdicts, min_os)

        if not tool:
            return self.cm.error('explore-tool-versions: name the tool to try (cx task run explore-tool-versions <tool>)')

        # The versions: the list given, else the newest <last>, else known and latest (and the newest one when a
        # limit excludes it from latest); the lookup is the one of "cx tool setup <tool> --versions"
        r = self.access({'category': 'task', 'command': 'run', 'arg1': SETUP_TASK, 'name': tool,
                         'versions': True, 'refresh_versions': bool(refresh_versions), 'con': False, 'quiet': True})
        info = r if r['return'] == 0 else {}
        if r['return'] > 0 and not versions:
            return self.cm.error(f'explore-tool-versions: the versions of tool "{tool}" are unknown ({r.get("error")}): give --versions')

        limits = info.get('latest_limits') or []
        listed = [v for v in info.get('versions') or [] if as_version(v) is not None and not as_version(v).is_prerelease]
        chosen = chosen_versions(info, versions, last)
        if not chosen:
            return self.cm.error(f'explore-tool-versions: no version of tool "{tool}" to try: give --versions')
        asked = list(chosen)

        host = this_host()
        aops = self.aops_version()
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        hostname = re.sub(r'[^\w.-]', '_', host['hostname'] or host['uname'] or 'host')
        path = os.path.abspath(output or f'explore-tool-versions-{tool}-{hostname}-{stamp}.jsonl')
        key = use_key or tool
        use = copy.deepcopy(ctx['tasks'].get('use') or {})

        if con:
            # Where the versions come from: the lookup of "cx tool setup <tool> --versions" (cached per tool)
            print ('')
            if info:
                lookup = info.get('versions_lookup') or {}
                print (f'cMeta info: {tool}: known {info.get("known") or "-"} (its default_version), '
                       f'latest {info.get("latest") or "-"} ({info.get("latest_source") or "no source"}'
                       + (', cached' if lookup.get('from_cache') else '') + ')'
                       + (f', newest {info["newest"]} (excluded from latest by its latest_limits)' if info.get('limit') else '')
                       + f'; {len(listed)} released version{"s" if len(listed) != 1 else ""} listed (its cmd_get_versions)')
            print (f'cMeta info: trying {len(asked)} version{"s" if len(asked) != 1 else ""}: '
                   + ', '.join(f'{v} ({why})' for v, why in chosen.items())
                   + (f', each with "cx program run {program}"' if program else ''))

        results = []
        for version in asked:
            t0 = time.monotonic()
            verdict = {'schema': VERDICT_SCHEMA, 'tool': tool, 'version': version, 'chosen_as': chosen[version],
                       'obtained': None, 'program': program or None, 'works': False, 'stage': 'setup', 'error_class': None, 'error': None,
                       'limit': None, 'host': host, 'cmeta': getattr(self.cm, '__version__', None), 'aops': aops,
                       'time': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec = 'seconds')}

            r = self.access({'category': 'task', 'command': 'run', 'arg1': SETUP_TASK, 'name': tool,
                             'version': version, 'new': True, 'con': False, 'quiet': True})
            if r['return'] == 0:
                verdict['obtained'] = r.get('version')
                verdict['works'] = True
                if program:
                    u = copy.deepcopy(use)
                    u.setdefault(key, {})['version'] = r.get('version') or version
                    rp = self.access({'category': 'program', 'command': 'run', 'arg1': program, 'use': u,
                                      'con': False, 'quiet': True})
                    if rp['return'] > 0:
                        verdict.update({'works': False, 'stage': 'program', 'error': first_line(rp.get('error')),
                                        'error_class': 'crash' if rp.get('crash') else error_class(rp.get('error'), 'program')})
                    else:
                        verdict['stage'] = 'program'
            else:
                verdict.update({'error': first_line(r.get('error')),
                                'error_class': 'crash' if r.get('crash') else error_class(r.get('error'), 'setup')})

            limit = excluded_by(verdict['obtained'] or version, limits)
            if limit:
                verdict['limit'] = limit.get('exclude')
            verdict['seconds'] = round(time.monotonic() - t0, 1)

            # The setup's entry is ours (--new): removed unless --keep
            uid = entry_uid(r.get('path_cmeta_cache')) if r['return'] == 0 else None
            if uid and not keep:
                rd = self.cm.access({'category': 'cache', 'command': 'delete', 'arg1': uid, 'force': True,
                                     'con': False, 'quiet': True})
                verdict['entry_removed'] = rd['return'] == 0
            elif uid:
                verdict['entry'] = uid

            results.append(verdict)

            # Written as soon as it is made: an interrupted exploration keeps what it found
            try:
                with open(path, 'a', encoding = 'utf-8') as f:
                    f.write(json.dumps(verdict) + '\n')
            except OSError as e:
                return self.cm.error(f'explore-tool-versions: the verdicts could not be written to {path}: {e}')

            if con:
                print (f'  {version:<16} {str(verdict["obtained"] or "-"):<16} {"works" if verdict["works"] else "FAILS":<6} '
                       f'{verdict["seconds"]:>7} s' + (f'  {verdict["error_class"]}: {verdict["error"]}' if not verdict['works'] else '')
                       + (f'  (excluded from latest: {verdict["limit"]})' if verdict['limit'] else ''))

        # The verdicts file, attached to the test session of the shell
        works = [v['version'] for v in results if v['works']]
        fails = [v['version'] for v in results if not v['works']]
        summary = f'explore-tool-versions {tool} on {host["uname"]}: works {", ".join(works) or "-"}; fails {", ".join(fails) or "-"}'

        session = os.environ.get(SESSION_ENV, '').strip()
        attached = False
        if session:
            ra = self.cm.access({'category': 'task', 'command': 'run', 'arg1': TEST_SESSION_TASK, 'id': session,
                                 'attach': path, 'note': summary, 'con': False, 'quiet': True})
            attached = ra['return'] == 0

        if con:
            print ('')
            print (f'cMeta info: {summary}')
            print (f'cMeta info: the verdicts are in {path}' + (f' (attached to test session {session})' if attached else ''))

        return {'return': 0, 'verdicts': results, 'works': works, 'fails': fails, 'output': path}

    ############################################################
    def access(self, ii):
        """cm.access, but an exception of a sub-task is a result with return 1 and crash True (the exploration goes on)."""
        try:
            return self.cm.access(ii)
        except Exception as e:
            return {'return': 1, 'error': f'{type(e).__name__}: {e}', 'crash': True}

    ############################################################
    def promote(self, ctx, con, verdicts, min_os):
        """The proposals of the verdicts in the files or folders named (--verdicts), printed as YAML lines."""
        if not verdicts:
            return self.cm.error('explore-tool-versions --promote: name the verdicts (--verdicts=<file.jsonl|folder>[,...])')

        try:
            records, files = read_verdicts(verdicts)
        except (OSError, ValueError) as e:
            return self.cm.error(f'explore-tool-versions --promote: the verdicts could not be read: {e}')

        descs = {}
        for tool in sorted({r['tool'] for r in records}):
            r = self.cm.access({'category': 'tool', 'command': 'find', 'arg1': tool, 'con': False})
            if r['return'] == 0 and r.get('artifacts'):
                rd = self.cm.utils.files.safe_read_yaml_or_json(os.path.join(r['artifacts'][0]['path'], '_desc'))
                descs[tool] = (rd.get('data') or {}) if rd['return'] == 0 else {}

        evidence = evidence_of(records)
        proposals = proposals_of(records, descs, min_os = int(min_os or 1))

        if con:
            print ('')
            print (f'cMeta info: {len(records)} verdict{"s" if len(records) != 1 else ""} from {len(files)} file{"s" if len(files) != 1 else ""}')

            # The evidence: per tool, each version tried, where it worked and where it failed
            for tool in sorted(evidence):
                print ('')
                print (f'{tool} (default_version {(descs.get(tool) or {}).get("default_version") or "-"}):')
                for version in sorted(evidence[tool], key = lambda x: (as_version(x) is not None, as_version(x) or x), reverse = True):
                    row = evidence[tool][version]
                    print (f'  {version:<14} ' + '; '.join(part for part in (
                        ('works on ' + ', '.join(row['works'])) if row['works'] else '',
                        ('fails on ' + ', '.join(row['fails'])) if row['fails'] else '') if part))

            print ('')
            print ('cMeta info: the proposals (nothing is changed: a person puts the lines into the tool\'s _desc.yaml):')
            if not proposals:
                print ('cMeta info: no change is supported by these verdicts')
            for p in proposals:
                print ('')
                if p['change'] == 'default_version':
                    print (f'tool/{p["tool"]}/_desc.yaml: {p["from"] or "-"} -> {p["to"]} (works on {", ".join(p["works_on"])}; '
                           f'{p["evidence"]} run{"s" if p["evidence"] != 1 else ""}' +
                           ('; a first pin: the tool has no default_version, so this changes what a request without a version installs' if p.get('first') else '') + ')')
                    print (f"  default_version: '{p['to']}'")
                elif p['change'] == 'not available':
                    print (f'tool/{p["tool"]}: note - {p["version"]} is not available on {p["on"]} ({p["error"]})'
                           + (f'; it works on {", ".join(p["works_on"])}' if p['works_on'] else '') + ' - not a limit: update the channel there')
                else:
                    print (f'tool/{p["tool"]}/_desc.yaml: exclude {p["version"]} from latest ({p["evidence"]} run{"s" if p["evidence"] != 1 else ""})')
                    print ('  latest_limits:')
                    print (f"    - exclude: '{p['exclude']}'")
                    print (f"      reason: {json.dumps(p['reason'])}")
                    print (f"      since: '{p['since']}'")

        return {'return': 0, 'proposals': proposals, 'evidence': evidence, 'verdicts': len(records), 'files': files}

    ############################################################
    def aops_version(self):
        """The version of this repository (its _cmr.yaml), or None."""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '_cmr.yaml')
        try:
            with open(path, encoding = 'utf-8') as f:
                m = re.search(r'^version:\s*(\S+)', f.read(), re.M)
            return m.group(1).strip('\'"') if m else None
        except OSError:
            return None
