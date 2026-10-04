"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

Deadlines for a phase of a pipeline: a task opens one (the compile phase of a program with
--compile_timeout) in ctx['tasks']['deadlines'], a stack that every task of the run sees, since
ctx is shared with the nested tasks (the task engine copies only ctx['control'] and the params).
task/cmd gives each command min(its own timeout, the time left to the nearest deadline) and fails
at once when none is left, so a build that a tool runs inside the phase is stopped too. The task
closes the deadline when the phase ends, also on errors. Without a deadline nothing changes.
"""

import time

KEY = 'deadlines'


def seconds(value):
    """The seconds of a timeout option, or None for no limit (None, "", 0, "0", False)."""
    if value in (None, '', 0, '0', False):
        return None
    return max(1, int(float(value)))


def open_deadline(ctx, name, timeout, option):
    """Opens a deadline of `timeout` seconds (a timeout option's value) named for its phase; returns
    the entry (to close it) or None when the value means no limit."""
    limit = seconds(timeout)
    if limit is None:
        return None
    entry = {'name': name, 'seconds': limit, 'until': time.time() + limit, 'option': option}
    ctx.setdefault('tasks', {}).setdefault(KEY, []).append(entry)
    return entry


def close_deadline(ctx, entry):
    """Closes a deadline opened with open_deadline (nothing for None)."""
    if entry is None:
        return
    stack = ctx.get('tasks', {}).get(KEY)
    if stack and entry in stack:
        stack.remove(entry)
    if stack == []:
        del ctx['tasks'][KEY]


def nearest(ctx):
    """The open deadline that ends first, or None."""
    stack = ctx.get('tasks', {}).get(KEY) or []
    return min(stack, key = lambda e: e['until']) if stack else None


def time_left(entry, now = None):
    """The seconds left to a deadline, rounded up, at least 0."""
    left = entry['until'] - (time.time() if now is None else now)
    return max(0, int(left) + (1 if left > int(left) else 0))


def describe(entry):
    """'the compile deadline of 3600 s (--compile_timeout)'"""
    return f"the {entry['name']} deadline of {entry['seconds']} s ({entry['option']})"
