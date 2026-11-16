"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

program.output: the reference outputs of a program - an artifact per program (the alias of the program, or the one
its output_check names), a folder per case inside, each with case.json (the key of the case: command, dataset,
sub-dataset, file and the parameters that matter; the facts of the recording; every output file with its size and
digests) and the output files themselves when small. compile-and-run-program records and compares them
(cx program run <program> <target> --check_output).
"""

from cmeta.category import InitCategory


class Category(InitCategory):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)
