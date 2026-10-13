"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

A guard for a rule of the code of this repository (categories, tasks, tools), as the engine has one for its own:
a duration, a timeout, a deadline or a retry is measured on the monotonic clock (`time.monotonic()`,
`time.perf_counter()`), never on the wall clock (`time.time()`). The wall clock is set while code runs - by NTP,
by a virtual machine's sync with its host: WSL2 was seen stepping it by seconds every 30 s - and a duration
measured on it is wrong, even negative; a timeout or a deadline ends too early or too late.

Every Python file of category/, task/ and tool/ is parsed, and each `time.time()` that is subtracted from, added
to or compared with something is listed. A start that is also a time of day (to find a file written after it)
stays a `time.time()` that nothing subtracts, next to a monotonic start for the duration. Programs (program/)
are not checked: they are the measured code, whose authors choose their clocks.
"""

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

FOLDERS = ('category', 'task', 'tool')

# Not the code of this repository: environments and caches that may sit in a working copy (not "venv": that
# is the name of a task), and the tests, which set the wall clock on purpose
SKIP = {'.venv', 'site-packages', 'node_modules', '__pycache__', 'tests'}

# (the file under the repository, a piece of the source line): the wall clock against a time WRITTEN somewhere
ALLOWED = ()


def is_wall_clock_call(node):
    """`time.time()` or a bare `time()` imported from the time module."""
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr == 'time' and isinstance(f.value, ast.Name) and f.value.id == 'time'
    return isinstance(f, ast.Name) and f.id == 'time'


def wall_clock_arithmetic():
    """(file, line number) -> source line of every subtraction, addition or comparison with the wall clock."""
    found = {}
    for folder in FOLDERS:
        for path in sorted((REPO_ROOT / folder).rglob('*.py')):
            rel = path.relative_to(REPO_ROOT)
            if SKIP.intersection(rel.parts):
                continue

            source = path.read_text(encoding='utf-8', errors='replace')
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue

            lines = source.splitlines()
            for node in ast.walk(tree):
                if not isinstance(node, (ast.BinOp, ast.Compare)):
                    continue
                if isinstance(node, ast.BinOp) and not isinstance(node.op, (ast.Sub, ast.Add)):
                    continue
                if any(is_wall_clock_call(n) for n in ast.walk(node)):
                    found[(rel.as_posix(), node.lineno)] = lines[node.lineno - 1].strip()
    return found


def test_durations_are_measured_on_the_monotonic_clock():
    found = wall_clock_arithmetic()

    wrong = []
    seen_allowed = set()
    for (file, lineno), line in sorted(found.items()):
        ok = False
        for allowed_file, piece in ALLOWED:
            if file == allowed_file and piece in line:
                ok = True
                seen_allowed.add((allowed_file, piece))
        if not ok:
            wrong.append(f'{file}:{lineno}: {line}')

    assert not wrong, ('a duration, deadline or retry measured on the wall clock (use time.monotonic() or '
                       'time.perf_counter(); a time of day that is written down or compared with a file may stay):\n  '
                       + '\n  '.join(wrong))

    # The list above must not go stale: every allowed place is still there
    stale = [f'{f}: {p}' for f, p in ALLOWED if (f, p) not in seen_allowed]
    assert not stale, 'ALLOWED names a place that is gone - remove it:\n  ' + '\n  '.join(stale)


def test_the_guard_sees_a_duration_on_the_wall_clock():
    # The parser finds what it is meant to find - a guard that finds nothing proves nothing
    tree = ast.parse('import time\nstart = time.time()\nseconds = time.time() - start\nlate = time.time() > deadline\n')

    hits = [node.lineno for node in ast.walk(tree) if isinstance(node, (ast.BinOp, ast.Compare))
            and any(is_wall_clock_call(n) for n in ast.walk(node))]

    assert sorted(hits) == [3, 4]
