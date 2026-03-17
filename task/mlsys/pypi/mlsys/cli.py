"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.
"""

import sys
import subprocess

def main_mlsys() -> int:
    """
        Entry point for the 'mlsys' command-line interface.

        Returns:
            int: Exit code (0 for success, non-zero for errors).

        Args:
            None.
        Raises:
            Exception: Propagated runtime errors, if any.
    """
    args = sys.argv

    return main(args = args)

def main(
    args = None,  # CLI positional arguments passed to the entry point.
) -> int:
    """
        Main function for CLI entry point. Processes sys.argv and calls CMeta.

        Parses command-line arguments from sys.argv, processes them through the CMeta
        framework, and handles the results including error checking and exit codes.

        Returns:
            int: Exit code (0 for success, non-zero for errors).

        Args:
            args: CLI positional arguments passed to the entry point.
        Raises:
            Exception: Propagated runtime errors, if any.
    """

    args = ['cmeta', 'task', 'run', 'mlsys'] + sys.argv[1:]

    result = subprocess.run(args)

    returncode = result.returncode

    return returncode
