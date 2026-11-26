"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The summaries of what Nsight Systems recorded of a run's marked part (task/setup-run, --profile_cuda_range): the
reports it left in this folder - cuda_profile.nsys-rep, or one per range, cuda_profile.<n>.nsys-rep, when the end
of a range is "repeat" - each given to the command that follows the range. A program that never met its range
leaves no report: said in words, exit 1.

    python nsys_range_reports.py <the range as asked> <nsys> stats [options] --report <report>

A file of its own because the lines of a run are both run one by one and kept as a script: a loop over files is
written differently in the two on Windows (%f, %%f).
"""

import os
import re
import subprocess
import sys

NUMBERED = re.compile(r'^cuda_profile\.(\d+)\.nsys-rep$')


def reports(folder):
    """The reports of a ranged run in a folder: the numbered ones in their order, else the one report, else none."""
    numbered = sorted((int(m.group(1)), name) for name in os.listdir(folder) for m in [NUMBERED.match(name)] if m)
    if numbered:
        return [name for _, name in numbered]
    return ['cuda_profile.nsys-rep'] if os.path.isfile(os.path.join(folder, 'cuda_profile.nsys-rep')) else []


def main(argv):
    if len(argv) < 3:
        print('usage: nsys_range_reports.py <range> <nsys> stats [options]', file = sys.stderr)
        return 2
    asked, command = argv[1], argv[2:]
    found = reports(os.getcwd())
    if not found:
        print(f'cMeta notice: Nsight Systems recorded nothing - the program never met the range {asked}!', file = sys.stderr)
        return 1
    for name in found:
        if len(found) > 1:
            print(f'cMeta info: the range {asked}, report {name}', flush = True)
        code = subprocess.call(command + [name], stdin = subprocess.DEVNULL)
        if code != 0:
            return code
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
