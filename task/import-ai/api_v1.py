"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

import-ai - import memories and skills into the !AI folder of a cMeta artifact, where "cxt run-ai" reads them
(and, for claude, writes the memory back). The sister task of run-ai.

    cxt import-ai --project=<cref> --plan=<yaml>                 # a curated plan (memories: [...], skills: [...])
    cxt import-ai --project=<cref> --memories="<file>;<folder>"  # Claude-style memory files, or folders of them
    cxt import-ai --project=<cref> --skills="<skill dir>;<folder of skill dirs>"
    cxt import-ai --project=<cref> --claude_folder="<folder>"    # the native Claude Code memory of a folder
    cxt import-ai ... --dry_run                                  # show, copy nothing

Memories are Markdown files with the Claude Code front matter (name, description, metadata.type, ...). They are copied
as they are (the content is never edited; the provenance goes into the import record). The index MEMORY.md keeps its
lines, their order and its headings: a memory without an entry gets one at the end - the line of the source index when
that index has it, else one made from the front matter - and the entry of a memory replaced with --overwrite is
renewed where it stands; a run that imports skills only does not touch the index. Skills are folders with a SKILL.md;
they are copied whole into !AI/skills/<name>/, !AI/.claude-plugin/plugin.json is written for claude, and
!AI/skills/.sources.json records the source of each (run-ai compares the copies with it).
Paths are separated by ";" since folder names may contain commas.
"""

import datetime
import filecmp
import glob
import hashlib
import io
import json
import os
import re
import shutil

import yaml

from task_c36be4b9314a45e0.api.ctask import InitCTask

AI_DIR = '!AI'
MEMORY_DIR = 'memory'
SKILLS_DIR = 'skills'
LOG_DIR = 'log'
INDEX_FILE = 'MEMORY.md'
PLUGIN_DIR = '.claude-plugin'
PLUGIN_FILE = 'plugin.json'
SEP = ';'
# !AI/skills/.sources.json: where each skill was copied from, when, and the hash of what was copied - run-ai compares the
# copy with its source on every run and says when they went apart
SOURCES_FILE = '.sources.json'
CLAUDE_SLUG_MAX = 200     # Claude Code cuts a longer project slug to 200 characters and appends "-<hash of the path>"


def _glob(directory, *pattern):
    """glob.glob in a directory whose own name is taken as it is: a folder called "notes [draft]" is not a pattern."""
    return glob.glob(os.path.join(glob.escape(directory), *pattern))


def _claude_session_cwd(folder):
    """The working directory a session of a Claude project folder recorded ('' when none says)."""
    for fp in sorted(_glob(folder, '*.jsonl')):
        try:
            with io.open(fp, encoding='utf-8', errors='replace') as f:
                for n, line in enumerate(f):
                    if n >= 50:
                        break
                    if '"cwd"' not in line:
                        continue
                    try:
                        cwd = json.loads(line).get('cwd')
                    except (ValueError, AttributeError):
                        continue
                    if cwd:
                        return cwd
        except OSError:
            continue
    return ''


def _front_matter(path):
    """(name, description) from the front matter of a memory or skill file."""
    try:
        with io.open(path, encoding='utf-8', errors='replace') as f:
            head = f.read(6000)
    except Exception:
        return '', ''
    m = re.match(r'^\ufeff?---\s*\n(.*?)\n---', head, re.S)
    if not m:
        return '', ''
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception:
        return '', ''
    if not isinstance(fm, dict):
        return '', ''
    return str(fm.get('name') or ''), ' '.join(str(fm.get('description') or '').split())


def _same_tree(a, b):
    """Do two folders hold the same files with the same content, at every level (caches left out)?"""
    def files(root):
        out = {}
        for d, dirs, names in os.walk(root):
            dirs[:] = [x for x in dirs if x != '__pycache__']
            for n in names:
                if not n.endswith('.pyc'):
                    out[os.path.relpath(os.path.join(d, n), root)] = os.path.join(d, n)
        return out
    fa, fb = files(a), files(b)
    return set(fa) == set(fb) and all(filecmp.cmp(fa[k], fb[k], shallow=False) for k in fa)


def _tree_hash(root):
    """A sha256 of a folder's files (their paths and contents, caches left out) - the same as run-ai's."""
    files = []
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x != '__pycache__']
        files += [os.path.join(d, n) for n in names if not n.endswith('.pyc')]
    h = hashlib.sha256()
    for fp in sorted(files, key=lambda x: os.path.relpath(x, root).replace('\\', '/')):
        h.update(os.path.relpath(fp, root).replace('\\', '/').encode('utf-8') + b'\0')
        with open(fp, 'rb') as f:
            h.update(f.read())
        h.update(b'\0')
    return h.hexdigest()


def _index_lines(index_path):
    """{file.md: the full index line} of a MEMORY.md."""
    out = {}
    if not os.path.isfile(index_path):
        return out
    with io.open(index_path, encoding='utf-8-sig', errors='replace') as f:
        for line in f.read().splitlines():
            m = re.search(r'\]\(([^)/\\:]+\.md)\)', line)
            if m and line.strip().startswith('-'):
                out[m.group(1)] = line.rstrip()
    return out


class CTask(InitCTask):
    """import-ai: import memories and skills into the !AI folder of a cMeta artifact."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    # ------------------------------------------------------------------ the project
    def _resolve_project(self, project):
        if not project or project == '.':
            return os.path.normpath(os.getcwd()), ''
        if '::' not in project:
            return None, '--project must be a cRef "category::artifact" (alias or alias,UID)'
        cat, art = [x.strip() for x in project.split('::', 1)]
        r = self.cm.access({'category': cat, 'command': 'find', 'arg1': art, 'con': False})
        if r.get('return', 1) > 0:
            return None, '--project: %s' % r.get('error', 'not found')
        arts = r.get('artifacts') or []
        if len(arts) != 1:
            return None, '--project "%s" resolves to %d artifacts' % (project, len(arts))
        a = arts[0]
        p = a.get('cmeta_ref_parts') or {}
        cref = '%s,%s::%s,%s' % (p.get('category_alias', cat), p.get('category_uid', ''), p.get('artifact_alias', art), p.get('artifact_uid', ''))
        return os.path.normpath(a['path']), cref

    @staticmethod
    def _claude_memory_dirs(folder):
        """The same rule as claude_project_dirs in run-ai's conversations.py: a slug longer than 200 characters is
        cut to 200 and followed by "-<hash>", so the folders with that prefix are taken, less those whose sessions
        recorded another working directory."""
        base = os.environ.get('CLAUDE_CONFIG_DIR') or os.path.join(os.path.expanduser('~'), '.claude')
        p = os.path.normpath(folder)
        variants = {p}
        if len(p) > 1 and p[1] == ':':
            variants |= {p[0].lower() + p[1:], p[0].upper() + p[1:]}
        out = []
        for v in sorted(variants):
            slug = re.sub(r'[^A-Za-z0-9]', '-', v)
            if len(slug) <= CLAUDE_SLUG_MAX:
                out.append(os.path.join(base, 'projects', slug, MEMORY_DIR))
                continue
            for d in sorted(_glob(os.path.join(base, 'projects'), slug[:CLAUDE_SLUG_MAX] + '-*')):
                m = os.path.join(d, MEMORY_DIR)
                if m in out or not os.path.isdir(d) or len(os.path.basename(d)) <= CLAUDE_SLUG_MAX + 1:
                    continue
                cwd = _claude_session_cwd(d)
                if cwd and os.path.normcase(os.path.normpath(cwd)) != os.path.normcase(p):
                    continue
                out.append(m)
        return out

    @staticmethod
    def _split(value):
        if isinstance(value, (list, tuple)):
            items = []
            for v in value:
                items += [x for x in str(v).split(SEP)]
        else:
            items = str(value or '').split(SEP)
        return [os.path.expanduser(x.strip().strip('"')) for x in items if x.strip()]

    # ------------------------------------------------------------------ run
    def run(self,
            ctx: dict,                  # cMeta context
            project: str = '',          # cRef "category::artifact" of the target (default: the current directory)
            plan: str = '',             # a YAML file: {memories: [files or folders], skills: [skill dirs or folders of them]}
            memories: str = '',         # memory files or folders of memory files, separated by ";"
            skills: str = '',           # skill folders (with SKILL.md) or folders of skill folders, separated by ";"
            claude_folder: str = '',    # folders whose native Claude Code memory is imported, separated by ";"
            overwrite: bool = False,    # replace a memory or skill that is already there (default: identical skipped, newer wins)
            dry_run: bool = False,      # show what would be done, copy nothing
    ):
        """Import memories and skills into the !AI folder of a cMeta artifact."""
        con = ctx['control'].get('con', False)
        path, cref = self._resolve_project(project)
        if path is None:
            return self.cm.error(cref)
        ai_root = os.path.join(path, AI_DIR)
        mem_dir = os.path.join(ai_root, MEMORY_DIR)
        skills_dir = os.path.join(ai_root, SKILLS_DIR)
        log_dir = os.path.join(ai_root, LOG_DIR)
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        # the artifact's alias: its part of the cRef without the UID (an alias may contain commas itself)
        alias = re.sub(r',[0-9a-f]{16}$', '', cref.split('::', 1)[1]) if cref else os.path.basename(path)

        mem_items = self._split(memories)
        skill_items = self._split(skills)
        for folder in self._split(claude_folder):
            dirs = [d for d in self._claude_memory_dirs(folder) if _glob(d, '*.md')]
            if dirs:
                mem_items.append(dirs[0])
            else:
                return self.cm.error('no native Claude memory for the folder "%s" (looked in %s)' % (folder, ', '.join(self._claude_memory_dirs(folder)) or 'the folders of ~/.claude/projects for its shortened slug'))
        if plan:
            try:
                with io.open(plan, encoding='utf-8') as f:
                    p = yaml.safe_load(f) or {}
            except Exception as e:
                return self.cm.error('--plan %s cannot be read: %s' % (plan, e))
            base = os.path.dirname(os.path.abspath(plan))
            for key, items in (('memories', mem_items), ('skills', skill_items)):
                for x in (p.get(key) or []):
                    x = os.path.expanduser(str(x))
                    items.append(x if os.path.isabs(x) else os.path.join(base, x))
            for folder in (p.get('claude_folders') or []):
                dirs = [d for d in self._claude_memory_dirs(str(folder)) if _glob(d, '*.md')]
                if dirs:
                    mem_items.append(dirs[0])
        if not mem_items and not skill_items:
            return self.cm.error('nothing to import: give --plan, --memories, --skills or --claude_folder')

        # ---- the memory files: expand folders, keep the newest when one name comes twice
        files = {}
        missing = []
        for item in mem_items:
            if os.path.isdir(item):
                cands = [fp for fp in sorted(_glob(item, '*.md')) if os.path.basename(fp) != INDEX_FILE]
            elif os.path.isfile(item):
                cands = [item]
            else:
                missing.append(item)
                continue
            for fp in cands:
                name = os.path.basename(fp)
                if name not in files or os.path.getmtime(fp) > os.path.getmtime(files[name]):
                    files[name] = fp
        rows = []        # (what, name, source, decision)
        copied = skipped = replaced = 0
        replaced_names = set()
        for name in sorted(files):
            src = files[name]
            dst = os.path.join(mem_dir, name)
            if os.path.isfile(dst):
                if filecmp.cmp(src, dst, shallow=False):
                    rows.append(('memory', name, src, 'skipped: identical'))
                    skipped += 1
                    continue
                if not overwrite and os.path.getmtime(dst) >= os.path.getmtime(src):
                    rows.append(('memory', name, src, 'skipped: the copy in !AI is newer (--overwrite replaces it)'))
                    skipped += 1
                    continue
                decision = 'replaced (%s)' % ('--overwrite' if overwrite else 'the source is newer')
                replaced += 1
                replaced_names.add(name)
            else:
                decision = 'copied'
                copied += 1
            if not dry_run:
                os.makedirs(mem_dir, exist_ok=True)
                shutil.copy2(src, dst)
            rows.append(('memory', name, src, decision))

        # ---- the index: MEMORY.md stays as its owner keeps it - its lines, their order, its headings. A memory file
        #      that has no entry gets one at the end, and the entry of a memory replaced with --overwrite is renewed
        #      where it stands. A new line is the one of the source index when it has one, else it is made from the
        #      file's front matter. A run that imports no memory (skills only) does not touch the file.
        index_path = os.path.join(mem_dir, INDEX_FILE)
        existing = _index_lines(index_path)
        source_lines = {}
        for name, src in files.items():
            for line_name, line in _index_lines(os.path.join(os.path.dirname(src), INDEX_FILE)).items():
                source_lines.setdefault(line_name, line)
        present = sorted(os.path.basename(fp) for fp in _glob(mem_dir, '*.md') if os.path.basename(fp) != INDEX_FILE) if not dry_run else \
            sorted(set(list(existing.keys()) + list(files.keys())))

        def entry(name):
            if name in source_lines:
                return source_lines[name]
            fm_name, desc = _front_matter(os.path.join(mem_dir, name) if os.path.isfile(os.path.join(mem_dir, name)) else files.get(name, ''))
            return '- [%s](%s) — %s' % (fm_name or os.path.splitext(name)[0], name, desc or 'imported memory')

        old_lines = []
        if os.path.isfile(index_path):
            with io.open(index_path, encoding='utf-8-sig', errors='replace') as f:
                old_lines = f.read().splitlines()
        index_lines = list(old_lines)
        while index_lines and not index_lines[-1].strip():
            index_lines.pop()
        for name in present:
            if name not in existing:
                index_lines.append(entry(name))
            elif overwrite and name in replaced_names:
                index_lines = [entry(name) if line.rstrip() == existing[name] else line for line in index_lines]
        index = [line for line in index_lines if re.search(r'\]\(([^)/\\:]+\.md)\)', line) and line.strip().startswith('-')]
        if files and index_lines != old_lines and not dry_run:
            with io.open(index_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write('\n'.join(index_lines) + '\n')

        # ---- the skills
        skill_dirs = {}
        for item in skill_items:
            if os.path.isfile(os.path.join(item, 'SKILL.md')):
                skill_dirs[os.path.basename(os.path.normpath(item))] = item
            elif os.path.isdir(item):
                found = False
                for d in sorted(_glob(item, '*', 'SKILL.md')):
                    skill_dirs[os.path.basename(os.path.dirname(d))] = os.path.dirname(d)
                    found = True
                if not found:
                    missing.append(item + ' (no SKILL.md in it or below it)')
            else:
                missing.append(item)
        s_copied = s_skipped = s_replaced = 0
        sources_path = os.path.join(skills_dir, SOURCES_FILE)
        sources = {}
        if os.path.isfile(sources_path):
            try:
                with io.open(sources_path, encoding='utf-8-sig') as f:
                    sources = json.load(f)
            except (OSError, ValueError):
                sources = {}
        sources_before = json.dumps(sources, sort_keys=True)

        def remember(name, src):
            sources[name] = {'source': os.path.abspath(src), 'imported': datetime.datetime.now().isoformat(timespec='seconds'),
                             'hash': _tree_hash(src)}

        for name in sorted(skill_dirs):
            src = skill_dirs[name]
            dst = os.path.join(skills_dir, name)
            if os.path.isdir(dst):
                if _same_tree(src, dst):
                    rows.append(('skill', name, src, 'skipped: identical'))
                    s_skipped += 1
                    if (sources.get(name) or {}).get('source') != os.path.abspath(src):
                        remember(name, src)         # a copy made before the sources were recorded, or from elsewhere
                    continue
                if not overwrite:
                    rows.append(('skill', name, src, 'skipped: already there and different (--overwrite replaces it)'))
                    s_skipped += 1
                    continue
                if not dry_run:
                    shutil.rmtree(dst)
                decision = 'replaced (--overwrite)'
                s_replaced += 1
            else:
                decision = 'copied'
                s_copied += 1
            if not dry_run:
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            remember(name, src)
            rows.append(('skill', name, src, decision))
        if json.dumps(sources, sort_keys=True) != sources_before and not dry_run:
            os.makedirs(skills_dir, exist_ok=True)
            with io.open(sources_path, 'w', encoding='utf-8', newline='\n') as f:
                json.dump(sources, f, indent=1, sort_keys=True)
                f.write('\n')
        plugin_written = False
        if (skill_dirs or _glob(skills_dir, '*', 'SKILL.md')) and not os.path.isfile(os.path.join(ai_root, PLUGIN_DIR, PLUGIN_FILE)):
            plugin_written = True
            if not dry_run:
                os.makedirs(os.path.join(ai_root, PLUGIN_DIR), exist_ok=True)
                with io.open(os.path.join(ai_root, PLUGIN_DIR, PLUGIN_FILE), 'w', encoding='utf-8', newline='\n') as f:
                    json.dump({'name': re.sub(r'[^A-Za-z0-9]+', '-', alias).strip('-').lower() or 'project', 'version': '0.1.0',
                               'description': 'The skills of the cMeta artifact %s (its %s/%s folder), written by import-ai' % (cref or alias, AI_DIR, SKILLS_DIR)}, f, indent=1)
                    f.write('\n')

        # ---- the record
        lines = ['# import-ai %s%s' % (stamp, ' (dry run)' if dry_run else ''), '',
                 '| | |', '|---|---|',
                 '| project | `%s`%s |' % (path, (' - `%s`' % cref) if cref else ''),
                 '| memories | %d copied, %d replaced, %d skipped -> `%s` |' % (copied, replaced, skipped, mem_dir),
                 '| skills | %d copied, %d replaced, %d skipped -> `%s`%s |' % (s_copied, s_replaced, s_skipped, skills_dir, '; plugin.json written' if plugin_written else ''),
                 '| index | `%s`: %d entries |' % (index_path, len(index)),
                 '| plan | `%s` |' % (plan or '-'), '',
                 '| what | name | from | decision |', '|---|---|---|---|']
        lines += ['| %s | `%s` | `%s` | %s |' % r for r in rows]
        for m in missing:
            lines.append('| - | | `%s` | not found |' % m)
        record = os.path.join(log_dir, '%s.import.md' % stamp)
        if not dry_run:
            os.makedirs(log_dir, exist_ok=True)
            with io.open(record, 'w', encoding='utf-8', newline='\n') as f:
                f.write('\n'.join(lines) + '\n')
        if con:
            print('')
            print('IMPORT-AI: %s%s' % (path, (' (%s)' % cref) if cref else ''))
            print('  memories: %d copied, %d replaced, %d skipped -> %s (index: %d entries)' % (copied, replaced, skipped, mem_dir, len(index)))
            print('  skills:   %d copied, %d replaced, %d skipped -> %s%s' % (s_copied, s_replaced, s_skipped, skills_dir, '; plugin.json written' if plugin_written else ''))
            for what, name, src, decision in rows:
                if not decision.startswith('skipped: identical'):
                    print('  %-6s %-45s %s  <- %s' % (what, name, decision, src))
            for m in missing:
                print('  NOT FOUND: %s' % m)
            print('  record:   %s' % (record if not dry_run else '(dry run: none)'))
        return {'return': 0, 'project': path, 'cref': cref, 'memories': {'copied': copied, 'replaced': replaced, 'skipped': skipped},
                'skills': {'copied': s_copied, 'replaced': s_replaced, 'skipped': s_skipped}, 'index_entries': len(index),
                'missing': missing, 'record': record if not dry_run else '', 'dry_run': dry_run}
