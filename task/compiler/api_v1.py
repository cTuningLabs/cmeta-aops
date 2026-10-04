"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import platform
import copy
import re

from task_c36be4b9314a45e0.api.ctask import InitCTask


def version_numbers(version):
    """The integers of a version, to sort by: '13.3.0' -> [13, 3, 0]."""
    return [int(x) for x in re.findall(r'\d+', str(version or ''))]


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
        """

        # Checking even for cached entries!
        r = self.cm.check_params(params, [
                'lang',
                'extra_tags',
                'extra_match',
                'name',
                'text',
                'compute',
                'copy_to_storage_key',
                'with',
                'tool_with',
                'version',
            ], __name__)
        if self.cm.catch_error(r): return r

        # "with" for the setup of the compiler tool, e.g. the JDK vendor of javac: only the keys that
        # have a value. It is not part of the cache identity: a program that passes it runs this step
        # without the cache (test-nmm-java-cpu --jdk), so the runs without it keep their entry
        tool_with = params.get('tool_with')
        if isinstance(tool_with, dict):
            tool_with = {k: v for k, v in tool_with.items() if v not in (None, '')}
            if tool_with:
                params['tool_with'] = tool_with
            else:
                del params['tool_with']

        return {'return':0}

    ############################################################
    def _tool_query(self, params, uname):
        """
        What the compiler tool of a request must carry: the tags (lang-<lang> and extra_tags) and the
        match (the OS, the compute targets and extra_match). run() selects a tool with them, and
        filter_cache_artifacts checks the tool of a cached compiler with them.
        """

        lang = params.get('lang')
        extra_tags = params.get('extra_tags')
        extra_match = params.get('extra_match')
        compute = params.get('compute')

        tool_tags = [f'lang-{lang}']

        tool_match = {} if extra_match is None or extra_match == '' else copy.deepcopy(extra_match)
        tool_constraints = tool_match.setdefault('constraints', {})
        supports_os = tool_constraints.setdefault('supports_os', [])

        if uname not in supports_os:
            supports_os.append(uname)

        if not compute:
            compute = ['cpu']
        elif type(compute) == str:
            compute = compute.split(',')

        supports_compute = tool_constraints.setdefault('supports_compute', [])
        for c in compute:
            if c not in supports_compute:
                supports_compute.append(c)

        if extra_tags and type(extra_tags) == str:
            extra_tags = self.cm.utils.common.split(extra_tags)

        if extra_tags:
            tool_tags += [t for t in extra_tags if t not in tool_tags]

        return tool_tags, tool_match

    ############################################################
    def _narrow_use_version(self, ctx, name, version):
        """
        The compiler of this run is decided: a version range set for its tool (ctx['tasks']['use']
        [<tool>]['version'] - the limits of a CUDA toolkit from tool/nvcc, or a --use.<tool>.version
        range) that the decided version satisfies narrows to that version, so that the setup of the
        compiler and of the tools it uses (the Visual Studio of msvc) follow it instead of asking which
        of several installations within the range.
        """

        if not name or not version:
            return

        use = ctx.get('tasks', {}).get('use')
        spec = (use.get(name) or {}).get('version') if isinstance(use, dict) else None
        if not spec or str(spec) == str(version):
            return

        r = self.cm.repos.match_version_func(str(spec), str(version))
        if r.get('return', 0) == 0 and r.get('matched', False):
            use[name]['version'] = version

    ############################################################
    def _tool_meta(self, name):
        """The meta (_cmeta) of the compiler tool with this alias, or None when the index has none."""

        r = self.cm.access({'category': self.cmeta['uses_categories']['tool'],
                            'command': 'find',
                            'arg1': name})
        if r['return'] > 0 or not r.get('artifacts'):
            return None

        return r['artifacts'][0].get('cmeta') or {}

    ############################################################
    def filter_cache_artifacts(self,
                               ctx: dict,
                               artifacts: list,
                               tmp_artifacts: list,
                               params: dict,
                               path: str = None,
                               **extra,
    ):
        """
        Called by the task engine with the cached compilers that match the request (lang, compute, and
        name and version when given), before it offers them (interactive) or takes the first (quiet).
        Entries the request cannot use are dropped:
          * a compiler whose version is outside the limit the run sets for its tool
            (ctx['tasks']['use'][<tool>]['version']: the host compilers a CUDA toolkit accepts, set by
            tool/nvcc, or a --use.<tool>.version), unless the request names a version itself - the
            limit is then reported where it comes from, with the way out;
          * a compiler whose tool lacks the request's extra_tags or fails its extra_match (neither is
            part of the cache identity, so such entries matched before).
        Then the choice among the rest, without a prompt where there is nothing to ask:
          * a compiler tool already set up in this run (the toolkit of the cuda target, a C compiler of
            the same family) keeps the entries of its version only: the run stays consistent;
          * entries of one compiler and version (made for different compute lists: cuda, then
            cuda+vulkan) are the same compiler: the one made for this request's compute, else the
            most specific one, is taken;
          * for the host compiler of nvcc (extra_match carries supports_nvcc_os), the compiler whose
            tool the repository ranks first (sort in _cmeta.yaml: msvc, gcc, clang - the compiler of
            the OS) is taken, then the newest version, said in an INFO line: the order of a selection
            among the tools on a machine without cached compilers.
        Other requests with several different compilers left keep the engine's choice (a question, or
        the newest in quiet mode).
        """

        control = ctx.get('control', {})
        con = control.get('con', False)
        verbose = control.get('verbose', False)
        ctx_tasks = ctx.get('tasks', {})
        space = '  ' * ctx_tasks.get('nested_call', 0) if verbose else ''

        _global = ctx_tasks.get('global', {})
        uname = _global.get('host', {}).get('os', {}).get('uname') or platform.system().lower()
        use = ctx_tasks.get('use') or {}

        lang = params.get('lang')
        version = params.get('version')
        extra_match = params.get('extra_match')
        extra_match = extra_match if isinstance(extra_match, dict) else {}

        compute = params.get('compute') or _global.get('target', {}).get('compute') or ['cpu']
        compute = compute.split(',') if isinstance(compute, str) else list(compute)

        tool_tags, tool_match = self._tool_query(params, uname)
        check_tool = bool(params.get('extra_tags')) or bool(extra_match)

        metas = {}

        def meta_of(tool_name):
            if tool_name not in metas:
                metas[tool_name] = self._tool_meta(tool_name)
            return metas[tool_name]

        def params_of(a):
            return a.get('cmeta', {}).get('params', {})

        def compiler_of(a):
            p = params_of(a)
            return (p.get('name'), str(p.get('version')))

        def why_unusable(a):
            p = params_of(a)
            tool_name = p.get('name')
            tool_version = p.get('version')

            spec = (use.get(tool_name) or {}).get('version') if tool_name else None
            if spec and tool_version and not version:
                r = self.cm.repos.match_version_func(str(spec), str(tool_version))
                if r.get('return', 0) == 0 and not r.get('matched', False):
                    return f'version {tool_version} is outside "{spec}"'

            if check_tool and tool_name:
                meta = meta_of(tool_name)
                if meta is not None:
                    if not all(t in meta.get('tags', []) for t in tool_tags):
                        return f'tool "{tool_name}" lacks the tags {tool_tags}'
                    if not self.cm.utils.common.matches_query(meta, tool_match,
                                                              match_version_func = self.cm.repos.match_version_func,
                                                              match_empty_version = True):
                        return f'tool "{tool_name}" does not match {tool_match}'

            return None

        def set_up_in_run(a):
            p = params_of(a)
            g = _global.get(p.get('name')) if p.get('name') else None
            return isinstance(g, dict) and g.get('version') is not None and str(g.get('version')) == str(p.get('version'))

        kept = [a for a in artifacts if why_unusable(a) is None]
        kept_tmp = [a for a in tmp_artifacts if why_unusable(a) is None]

        if len(kept) > 1 and not version and any(set_up_in_run(a) for a in kept):
            kept = [a for a in kept if set_up_in_run(a)]

        if len(kept) > 1 and len({compiler_of(a) for a in kept}) == 1:
            def rank_same(a):
                c = params_of(a).get('compute') or []
                c = c if isinstance(c, list) else [c]
                return (0 if sorted(map(str, c)) == sorted(map(str, compute)) else 1, len(c), str(a.get('path')))

            kept = sorted(kept, key = rank_same)

            if con and verbose:
                name, v = compiler_of(kept[0])
                print (f"{space}INFO: {len(kept)} cache entries of {name} {v}: taking the one made for {params_of(kept[0]).get('compute')}")

            kept = kept[:1]

        host_of_nvcc = 'supports_nvcc_os' in (extra_match.get('constraints') or {})

        if host_of_nvcc and len(kept) > 1:
            def rank(a):
                p = params_of(a)
                sort = (meta_of(p.get('name')) or {}).get('sort')
                return (sort if isinstance(sort, (int, float)) else 10**9,
                        [-x for x in version_numbers(p.get('version'))],
                        str(p.get('name')))

            kept = sorted(kept, key = rank)

            if con:
                name, v = compiler_of(kept[0])
                others = []
                for a in kept[1:]:
                    x = ' '.join(compiler_of(a))
                    if x not in others and x != f'{name} {v}':
                        others.append(x)
                print (f"{space}INFO: {len(kept)} cached {lang} compilers suit nvcc: taking {name} {v} "
                       f"({', '.join(others)} also would; --use.compiler-{lang}.name=<tool> picks another)")

            kept = kept[:1]

        return {'return':0, 'artifacts': kept, 'tmp_artifacts': kept_tmp}

    ############################################################
    def run(self,
            ctx,
            **params,
    ):
        """
        """

        lang = params.get('lang')
        extra_tags = params.get('extra_tags')
        extra_match = params.get('extra_match')
        name = params.get('name')
        text = params.get('text')
        compute = params.get('compute')
        version = params.get('version')
        _with = params.get('with', {})

        if not lang:
            return self.cm.error(f'"lang" is not specified in "{__file__}"')

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        ctx_tasks = ctx['tasks']
        nested_call = ctx_tasks.setdefault('nested_call', 0)
        space = '  ' * nested_call if verbose else ''

        result = {'return':0}

        uname = ctx['tasks']['global']['host']['os']['uname']

        # The same tags and match that filter_cache_artifacts checks a cached compiler's tool with
        tool_tags, tool_match = self._tool_query(params, uname)
        tool_constraints = tool_match['constraints']

        if text and con:
            print ('')
            print (f'{space}{text}')

        ###########################################################################################
        # SELECT TOOL ARTIFACT
        if not name:
            p = {'category': self.cmeta['uses_categories']['utils'],
                 'command': 'select_artifact',
                 'select_category': self.cmeta['uses_categories']['tool'],
                 'select_tags': tool_tags,
                 'select_match': tool_match,
                 'con': con,
                 'quiet': quiet,
                 'verbose': verbose,
                 'space': space,
                 'print_extra_line': True,
            }

            r = self.cm.access(p)
            if self.cm.catch_error(r, fail16=True): 
                if r['return'] == 16:
                    if tool_constraints:
                        r['error'] += f' and constraints "{tool_constraints}"'
                    r['return'] = 99
                return r

            artifact = r['artifact']

            name = artifact['cmeta_ref_parts']['artifact_alias']

        # Setup compiler (note that there is duplicate in finish_dynamic_result too!) to update cache params
        # Don't forget CXT here to update global context for further tasks and tools in a higher level pipeline
        p = {'ctx': ctx,
             'category': self.category_alias + ',' + self.category_uid,
             'command': 'run',
             'arg1': 'setup,a2f9b61079ce4333',
             'name': name,
             'con': con,
             'quiet': quiet,
             'verbose': verbose,
        }

        if version:
            p['version'] = version

        if params.get('tool_with'):
            p['with'] = params['tool_with']

        r = self.cm.access(p)
        if self.cm.catch_error(r, fail16=True): return r

        version = r.get('version')
        constraints = r.get('constraints',{})
        constraints_compute = constraints.get('supports_compute')

        self._narrow_use_version(ctx, name, version)

        result.update(r)

        result['tool'] = {
          'name': name,
          'tags': tool_tags,
          'match': tool_match,
        }

        _update_params = {
          'name': name,
        }

        if version: _update_params['version'] = version
        if constraints_compute: _update_params['supported_compute'] = constraints_compute

        result['_update_params'] = _update_params

        return result

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        """

        name = result['tool']['name']

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        version = result.get('version')

        _result = {'return':0}

        # A range set for this compiler's tool follows the version decided here (see _narrow_use_version)
        self._narrow_use_version(ctx, name, version)

        # Setup compiler dynamically (for ENV if needed)
        # Don't forget CXT here to update global context for further tasks and tools in a higher level pipeline
        p = {'ctx': ctx,
             'category': self.category_alias + ',' + self.category_uid,
             'command': 'run',
             'arg1': 'setup,a2f9b61079ce4333',
             'name': name,
             'con': con,
             'quiet': quiet,
             'verbose': verbose,
        }

        if version: p['version'] = version

        if params.get('tool_with'):
            p['with'] = params['tool_with']

        r = self.cm.access(p)
        if self.cm.catch_error(r, fail16=True): 
            r['return'] = 99
            return r

        result.update(r)

        _with = params.get('with', {})

        _fast = _with.get('fast', False)
        _static = _with.get('static', False)
        _debug = _with.get('debug', False)
        _openmp = _with.get('openmp', False)
        _profile = _with.get('profile', False)

        compiler_flags = []

        flags = result.get('features', {}).get('flags',{})

        if _static:
            x = flags.get('static_build_debug') if _debug else flags.get('static_build')
        else:
            x = flags.get('dynamic_build_debug') if _debug else flags.get('dynamic_build')

        if x and x not in compiler_flags:
            compiler_flags.append(x)

        if _openmp:
            openmp_flag = flags.get('openmp')
            if not openmp_flag:
                return self.cm.error(f'openmp requested but flag is not defined in compiler meta in "{__file__}" ({__name__})')
        
            if openmp_flag not in compiler_flags:
                compiler_flags.append(openmp_flag)

        result['compiler_flags'] = compiler_flags

        _result['result'] = result

        return _result

