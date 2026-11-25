"""
Guards over every task, tool and category of the repository, for the kinds of bugs the stress test of cMeta 0.37 /
cmeta-aops 0.46 found (2026-10-14). Each test reads the files as they are, so a new task or tool is checked too:

- a parameter annotated `bool` that the code uses as text: download-file's `check_file` is a file name, and once
  the words of the command line were read by annotation, every release download stopped;
- a switch of a task whose run() reads **kwargs that cli_params does not describe: there is no annotation to read,
  so `cx tool setup X --skip_install=no` kept the text "no", which is true;
- a cli_params description the task category cannot read (a type it does not know is silently not converted);
- a search pattern a tool declares that the tool search refuses as a recursive search from a filesystem root:
  lib-openssl was never found in C:\\Program Files\\OpenSSL-Win64 (0.42.0 - 0.46.0).

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import ast
import importlib.util
import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# The Python files of tasks and categories (their own helpers included)
CODE_FILES = sorted(p for p in list(REPO_ROOT.glob('task/*/*.py')) + list(REPO_ROOT.glob('category/*/api/*.py'))
                    if '__pycache__' not in p.parts)

TASK_DESCS = sorted(REPO_ROOT.glob('task/*/_desc.yaml'))
TOOL_DESCS = sorted(REPO_ROOT.glob('tool/*/_desc.yaml'))

# The switches of the tasks whose run() reads **kwargs, as they must be described (the known ones: a switch
# removed from a description by mistake is found here; a new one by the generic rule below)
SWITCHES = {
    'setup': ['detect', 'install', 'build', 'skip_detect', 'skip_install', 'skip_build', 'skip_install_uses',
              'skip_build_uses', 'skip_cache_version_check', 'skip_size_check', 'versions', 'status', 'upgrade',
              'sizes', 'here', 'ignore_install_errors', 'ignore_build_errors', 'custom_install', 'custom_build',
              'add_tool_path_to_env', 'force_add_tool_path_to_env', 'refresh_versions', 'check_update'],
    'clone-git-to-cache': ['version_to_dir', 'skip_checkout_dir'],
    'compile-and-run-program': ['here', 'recompile', 'skip_compile', 'skip_run', 'skip_size_check'],
    'finish-run': ['print_line'],
    'setup-compile': ['profile', 'profile_cuda', 'profile_cuda_kernels'],
    'setup-run': ['run_on_host', 'profile', 'profile_python', 'profile_cuda', 'profile_cuda_kernels'],
    'target': ['ask', 'add_env'],
    'test-session': ['start', 'finish', 'prune', 'migrate', 'list', 'keep', 'all', 'remove_old', 'skip_usage'],
}

# A name with one of these prefixes is a switch wherever a **kwargs task tests it
SWITCH_PREFIXES = ('skip_', 'ignore_', 'force_', 'custom_')

STR_METHODS = {'endswith', 'startswith', 'split', 'rsplit', 'strip', 'lstrip', 'rstrip', 'lower', 'upper', 'replace',
               'format', 'encode', 'splitlines', 'find', 'rfind', 'partition', 'casefold'}

CLI_TYPES = ('bool', 'int', 'float', 'str')


def load_yaml(path):
    return yaml.safe_load(path.read_text(encoding = 'utf-8')) or {}


def is_bool(annotation):
    return (isinstance(annotation, ast.Name) and annotation.id == 'bool') or \
           (isinstance(annotation, ast.Constant) and annotation.value == 'bool')


def text_uses(func, names):
    """The places where func uses one of names as text: a path call, a str method, a string concatenation."""
    out = []
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            f = node.func
            pathy = (isinstance(f, ast.Name) and f.id in ('open', 'Path')) or \
                    (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute) and
                     isinstance(f.value.value, ast.Name) and f.value.value.id == 'os' and f.value.attr == 'path') or \
                    (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in ('os', 'shutil', 'pathlib'))
            if pathy:
                for a in list(node.args) + [k.value for k in node.keywords]:
                    if isinstance(a, ast.Name) and a.id in names:
                        out.append(f'{a.id} in a path call (line {node.lineno})')
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in names \
                and node.attr in STR_METHODS:
            out.append(f'{node.value.id}.{node.attr}() (line {node.lineno})')
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            for a, b in ((node.left, node.right), (node.right, node.left)):
                if isinstance(a, ast.Name) and a.id in names and \
                        (isinstance(b, ast.JoinedStr) or (isinstance(b, ast.Constant) and isinstance(b.value, str))):
                    out.append(f'{a.id} + a string (line {node.lineno})')
    return out


def test_no_bool_parameter_is_used_as_text():
    problems = []
    for path in CODE_FILES:
        tree = ast.parse(path.read_text(encoding = 'utf-8'))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = func.args.posonlyargs + func.args.args + func.args.kwonlyargs
            names = {a.arg for a in args if a.annotation is not None and is_bool(a.annotation)}
            for use in text_uses(func, names) if names else []:
                problems.append(f'{path.relative_to(REPO_ROOT)} {func.name}(): {use}')

    assert not problems, 'a parameter annotated bool is used as text (annotate it str):\n' + '\n'.join(problems)


def kwargs_run(path):
    """run() of a task's api_v1.py and the name of its ** parameter, or (None, None)."""
    tree = ast.parse(path.read_text(encoding = 'utf-8'))
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for f in node.body:
                if isinstance(f, ast.FunctionDef) and f.name == 'run' and f.args.kwarg is not None:
                    return tree, f, f.args.kwarg.arg
    return tree, None, None


def read_name(node, kw):
    """'x' when node is kw.get('x', ...), kw.pop('x', ...) or kw['x']."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ('get', 'pop') \
            and isinstance(node.func.value, ast.Name) and node.func.value.id == kw and node.args \
            and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == kw \
            and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
        return node.slice.value
    return None


def switches_read(tree, kw):
    """The names a task reads from its ** parameter as switches: with a boolean default, or a switch prefix in a test."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ('get', 'pop') \
                and len(node.args) == 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, bool):
            name = read_name(node, kw)
            if name:
                found.add(name)
        tests = []
        if isinstance(node, (ast.If, ast.While, ast.IfExp)):
            tests.append(node.test)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            tests.append(node.operand)
        if isinstance(node, ast.BoolOp):
            tests += node.values
        for t in tests:
            name = read_name(t, kw)
            if name and name.startswith(SWITCH_PREFIXES):
                found.add(name)
    return found


def test_the_switches_of_kwargs_tasks_are_described():
    problems = []
    for path in sorted(REPO_ROOT.glob('task/*/api_v1.py')):
        tree, run, kw = kwargs_run(path)
        if run is None:
            continue
        task = path.parent.name
        explicit = {a.arg for a in run.args.args + run.args.kwonlyargs}
        desc = load_yaml(path.parent / '_desc.yaml')
        described = desc.get('cli_params') or {}

        for name in sorted(switches_read(tree, kw) - explicit):
            if name not in described:
                problems.append(f'task/{task}: the switch "{name}" is read from **{kw} but not described in cli_params')

        for name in SWITCHES.get(task, []):
            kind = described.get(name)
            kind = kind.get('type') if isinstance(kind, dict) else kind
            if kind != 'bool':
                problems.append(f'task/{task}: cli_params must describe "{name}" as bool (it has {kind!r})')

    assert not problems, '\n'.join(problems)


def test_every_task_with_switches_is_known():
    for task in SWITCHES:
        assert (REPO_ROOT / 'task' / task / 'api_v1.py').is_file(), task


@pytest.mark.parametrize('path', TASK_DESCS, ids = lambda p: p.parent.name)
def test_cli_params_are_readable(path):
    described = load_yaml(path).get('cli_params')
    if described is None:
        return

    assert isinstance(described, dict), 'cli_params is a dict: name -> type, or name -> {type, values, min, max, hint}'
    for name, desc in described.items():
        if isinstance(desc, str):
            assert desc in CLI_TYPES, f'{name}: the type {desc!r} is not one of {CLI_TYPES}'
            continue

        assert isinstance(desc, dict) and desc, f'{name}: a type name or a dict'
        # hint: what the message of a value option given without its value says it takes (category/task/api/v2.py);
        # bare: what the option means given without a value - it may come bare (run-ai's -gw: choose from a list)
        keys = {'type', 'values', 'min', 'max', 'hint', 'bare'}
        assert set(desc) <= keys, f'{name}: unknown keys {set(desc) - keys}'
        for text in ('hint', 'bare'):
            if text in desc:
                assert isinstance(desc[text], str) and desc[text].strip(), f'{name}: {text} is a text'
        if 'type' in desc:
            assert desc['type'] in CLI_TYPES, f'{name}: the type {desc["type"]!r} is not one of {CLI_TYPES}'
        if 'values' in desc:
            assert isinstance(desc['values'], list) and desc['values'], f'{name}: values is a non-empty list'


# cli_help: what the words and the commands MEAN, for people (the cMeta CLI builder, help) - never read by the engine,
# so a mistake there changes no run; this guard keeps it readable. The keys of a word's entry and of a command's:
HELP_WORD_KEYS = {'desc', 'title', 'group', 'example', 'default', 'conflicts', 'needs', 'multiple', 'values_from', 'bare',
                  'refresh', 'position', 'tags', 'inherits', 'programs', 'if_read', 'hide', 'artifact', 'artifact_tags',
                  'type', 'values', 'min', 'max', 'choice', 'order', 'harness_takes', 'values_also'}
# choice: what the word changes - what is built, what is run, both, or true for a choice without a stage; false: a
# control, for a word a program reads itself (the page would take it for a choice of the stage that reads it)
CHOICE_STAGES = ('build', 'run')
# the lists a page asks for: the targets a program supports, its commands, its inputs, its models, its compilers, the
# harnesses the graph declares (cx task harnesses; harness_takes: only those whose task takes these words; values_also:
# the word's own other values)
VALUES_FROM = ('targets', 'cmds', 'datasets', 'models', 'compilers', 'harnesses')
HELP_COMMAND_KEYS = {'title', 'desc', 'artifact', 'task', 'passthrough', 'arg1', 'main', 'without', 'only', 'params'}
HELP_CATEGORY_KEYS = {'title', 'one', 'desc', 'order', 'hide'}
HELP_DESCS = sorted(TASK_DESCS + list(REPO_ROOT.glob('program/*/_desc.yaml')))
CATEGORY_DESCS = sorted(REPO_ROOT.glob('category/*/_desc.yaml'))


def check_help_word(where, name, entry):
    if isinstance(entry, str):
        assert entry.strip(), f'{where} {name}: an empty line of help'
        return
    assert isinstance(entry, dict) and entry, f'{where} {name}: a line of text or a dict'
    assert set(entry) <= HELP_WORD_KEYS, f'{where} {name}: unknown keys {set(entry) - HELP_WORD_KEYS}'
    if 'desc' in entry:
        assert isinstance(entry['desc'], str) and entry['desc'].strip(), f'{where} {name}: desc is a text'
    if 'type' in entry:
        assert entry['type'] in CLI_TYPES, f'{where} {name}: the type {entry["type"]!r} is not one of {CLI_TYPES}'
    for key in ('conflicts', 'needs', 'tags', 'values', 'inherits', 'programs'):
        if key in entry:
            assert isinstance(entry[key], list) and entry[key], f'{where} {name}: {key} is a non-empty list'
    if 'if_read' in entry:
        assert isinstance(entry['if_read'], bool), f'{where} {name}: if_read is true or false'
    if 'group' in entry:
        assert entry['group'] in ('main', 'more'), f'{where} {name}: group is main or more'
    if 'values_from' in entry:
        assert entry['values_from'] in VALUES_FROM, f'{where} {name}: values_from is one of {VALUES_FROM}'
    if 'choice' in entry and entry['choice'] is not False:
        stages = entry['choice'] if isinstance(entry['choice'], list) else [entry['choice']]
        ok = bool(stages) and all(s is True or s in CHOICE_STAGES for s in stages)
        assert ok, f'{where} {name}: choice is true, false, build, run or [build, run]'
    if 'order' in entry:
        number = isinstance(entry['order'], (int, float)) and not isinstance(entry['order'], bool)
        assert number, f'{where} {name}: order is a number'


@pytest.mark.parametrize('path', HELP_DESCS, ids = lambda p: p.parent.parent.name + '/' + p.parent.name)
def test_cli_help_of_tasks_and_programs_is_readable(path):
    described = load_yaml(path).get('cli_help')
    if described is None:
        return
    assert isinstance(described, dict), 'cli_help is a dict: word -> a line of text, or a dict'
    params = load_yaml(path).get('cli_params') or {}
    for name, entry in described.items():
        check_help_word(path.parent.name, name, entry)
        # what the engine reads stays in cli_params: the help may not say otherwise
        own = params.get(name)
        if isinstance(entry, dict) and isinstance(own, (str, dict)):
            own = {'type': own} if isinstance(own, str) else own
            for key in ('type', 'values', 'min', 'max'):
                if key in entry and key in own:
                    assert entry[key] == own[key], f'{path.parent.name} {name}: cli_help says {key} differently from cli_params'


@pytest.mark.parametrize('path', CATEGORY_DESCS, ids = lambda p: p.parent.name)
def test_cli_help_of_categories_is_readable(path):
    described = load_yaml(path).get('cli_help')
    if described is None:
        return
    assert isinstance(described, dict), 'cli_help is a dict: category -> its words, <command> -> its help'
    for name, entry in described.items():
        if name == 'category':
            assert isinstance(entry, dict) and set(entry) <= HELP_CATEGORY_KEYS, f'category: keys {set(entry) - HELP_CATEGORY_KEYS}'
            continue
        if isinstance(entry, str):
            assert entry.strip(), f'{name}: an empty line of help'
            continue
        assert isinstance(entry, dict), f'{name}: a line of text or a dict'
        assert set(entry) <= HELP_COMMAND_KEYS, f'{name}: unknown keys {set(entry) - HELP_COMMAND_KEYS}'
        if 'only' in entry:
            assert entry['only'] in CHOICE_STAGES, f'{name}: only is build or run (the one stage the command does)'
        for word, help_entry in (entry.get('params') or {}).items():
            check_help_word(name, word, help_entry)


def test_the_switches_of_setup_say_what_they_do():
    """Every word of task::setup (the words of cx tool setup | install | upgrade | run) has its line of help."""
    desc = load_yaml(REPO_ROOT / 'task' / 'setup' / '_desc.yaml')
    missing = sorted(set(desc.get('cli_params') or {}) - set(desc.get('cli_help') or {}))
    assert not missing, f'words of task::setup without cli_help: {missing}'


def test_cli_params_match_the_engine():
    """The types this guard allows are those the engine converts (when the engine has the reading)."""
    cli = pytest.importorskip('cmeta.utils.cli')
    if not hasattr(cli, 'CLI_TYPES'):
        pytest.skip('needs cMeta 0.37 or newer')
    assert set(CLI_TYPES) <= set(cli.CLI_TYPES)


@pytest.fixture(scope = 'module')
def tool_api():
    path = REPO_ROOT / 'category' / 'tool' / 'api' / 'v1.py'
    spec = importlib.util.spec_from_file_location('cmeta_aops_tool_api_v1_guards', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def declared_patterns(desc):
    """Every search pattern a tool declares: names, extra_paths and only_paths, for every OS."""
    out = []

    def add(value):
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            for v in value:
                add(v)
        elif isinstance(value, dict):
            for v in value.values():
                add(v)

    for key in ('names', 'extra_paths', 'only_paths'):
        add(desc.get(key))
    return out


def test_no_declared_search_pattern_is_refused(tool_api):
    """
    A pattern the search refuses can never find anything. A template stands for a real folder of the machine
    ({{...}} -> a folder below the root); what is refused then is a pattern that recurses from a root by itself.
    """
    problems = []
    for path in TOOL_DESCS:
        for pattern in declared_patterns(load_yaml(path)):
            if '**' not in pattern:
                continue
            concrete = re.sub(r'\{\{[^}]*\}\}', '/opt/a-tool-home', pattern)
            if not tool_api.glob_pattern_is_safe(concrete):
                problems.append(f'tool/{path.parent.name}: "{pattern}"')

    assert not problems, 'declared search patterns the tool search refuses:\n' + '\n'.join(problems)


# A parameter of run() named like a control word of the task category (save, path, new, info, tags, ...) never
# reaches run(): the category keeps those words for itself. The two that do work, by their own route:
CONTROL_WORD_EXCEPTIONS = {
    ('run-ai', 'new'): 'run() also reads it from the control of the task (cparams)',
    ('scan-git-secrets', 'path'): 'the control path is the working directory of the task, which is what it scans',
}


def control_words():
    """The control words of the task category (control1 and control2 of category/task/api/v2.py)."""
    tree = ast.parse((REPO_ROOT / 'category' / 'task' / 'api' / 'v2.py').read_text(encoding = 'utf-8'))
    words = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Attribute) \
                and node.targets[0].attr in ('control1', 'control2'):
            words |= {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    return words


def test_no_task_parameter_is_named_like_a_control_word():
    """explore-tool-versions (then explore-versions) had "save" (2026-10-14): --save=<file> saved the context of the run instead."""
    words = control_words()
    assert {'save', 'path', 'new', 'info', 'tags'} <= words

    problems = []
    for path in sorted(REPO_ROOT.glob('task/*/api_v1.py')):
        tree = ast.parse(path.read_text(encoding = 'utf-8'))
        for func in ast.walk(tree):
            if isinstance(func, ast.FunctionDef) and func.name == 'run':
                names = {a.arg for a in func.args.args + func.args.kwonlyargs} - {'self', 'ctx'}
                for name in sorted(names & words):
                    if (path.parent.name, name) not in CONTROL_WORD_EXCEPTIONS:
                        problems.append(f'task/{path.parent.name}: run() parameter "{name}" is a control word of the task category')

    assert not problems, '\n'.join(problems)
