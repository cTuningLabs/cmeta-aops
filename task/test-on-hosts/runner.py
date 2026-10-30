"""
The runner of test-on-hosts on one host (the standard library only, Python 3.6+): a throwaway cMeta home in
<root>/home with a repository's tree plugged in - unpacked from a tarball, or a folder used as it is - then each
command in <root>/work, one after the other, then <root>/DONE.

    python3 runner.py <root> <tree.tar.gz | tree folder> "<command>" ["<command>" ...]
    python3 runner.py <root> <tree.tar.gz | tree folder> @commands.json     # the commands as a JSON list in <root>

A command is the words after "cx" ("task run explore-tool-versions yq"); one that starts with "!" is a shell
command of the host (bash or cmd), with TREE, WORK and CMETA_HOME set. Each one writes <root>/work/step-<n>.log
and a line of <root>/work/steps.txt ("<n>: exit <code> in <s> s: <command>").
"""

import json
import os
import shutil
import subprocess
import sys
import tarfile
import time


def main():
    root = os.path.abspath(sys.argv[1])
    tree = sys.argv[2]
    commands = sys.argv[3:]

    # A Windows host gets the commands in a file next to the runner: no quoting of cmd.exe or of the Python command
    # line touches them
    if len(commands) == 1 and commands[0].startswith('@'):
        with open(os.path.join(root, commands[0][1:]), encoding = 'utf-8') as f:
            commands = json.load(f)

    home = os.path.join(root, 'home')
    work = os.path.join(root, 'work')

    for path in (home, work, os.path.join(root, 'DONE')):
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
    os.makedirs(home)
    os.makedirs(work)

    # The tree: a tarball made by the task (unpacked here, its one top folder), or a folder of this machine
    if tree.endswith('.tar.gz'):
        with tarfile.open(os.path.join(root, tree)) as tar:
            top = tar.getnames()[0].split('/')[0]
            shutil.rmtree(os.path.join(root, top), ignore_errors = True)
            tar.extractall(root)
        tree = os.path.join(root, top)

    env = dict(os.environ, CMETA_HOME = home, TREE = tree, WORK = work)
    env.pop('CMETA_TEST_SESSION', None)

    steps = os.path.join(work, 'steps.txt')

    def step(n, command, line):
        # One command: its output in step-<n>.log, its exit code and seconds in steps.txt
        t0 = time.monotonic()
        with open(os.path.join(work, 'step-%s.log' % n), 'w') as log:
            code = subprocess.call(line, shell = True, cwd = work, env = env, stdout = log, stderr = subprocess.STDOUT,
                                   stdin = subprocess.DEVNULL)
        with open(steps, 'a') as f:
            f.write('%s: exit %d in %d s: %s\n' % (n, code, round(time.monotonic() - t0), command))

    # A host whose cx sets a home of its own (a wrapper script exporting CMETA_HOME) runs the commands in that home,
    # with what is plugged there: said in steps.txt, and the tree is not plugged into the user's home. An engine
    # older than 0.35.2 has no --print-home and its answer is no folder: the tree is plugged as before
    r = subprocess.run('cx --print-home', shell = True, cwd = work, env = env, stdout = subprocess.PIPE,
                       stderr = subprocess.DEVNULL, stdin = subprocess.DEVNULL, universal_newlines = True)
    lines = r.stdout.strip().splitlines() if r.returncode == 0 else []
    used = lines[-1].strip() if lines else ''
    real = lambda p: os.path.normcase(os.path.realpath(p))

    if used and os.path.isabs(used) and os.path.isdir(used) and real(used) != real(home):
        with open(steps, 'a') as f:
            f.write('home: the host\'s cx keeps its own home %s - the commands run there, with the repositories '
                    'plugged there; the tree is not plugged\n' % used)
    else:
        step('plug', 'repo plug', 'cx repo plug "%s" -q' % tree)

    for n, command in enumerate(commands, 1):
        line = command[1:] if command.startswith('!') else 'cx ' + command
        step(n, command, line)

    with open(os.path.join(root, 'DONE'), 'w') as f:
        f.write('done %s\n' % time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))


if __name__ == '__main__':
    main()
