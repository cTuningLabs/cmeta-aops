"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. All rights reserved.
License: Proprietary - contact the author for licensing information.
"""

from pathlib import Path
import os
import logging

class InitCTask:
    """
    """

    ############################################################
    def __init__(self,
                 cm = None,
                 module_file_path = None,
                 logger: logging.Logger = None):

        self.cm = cm

        file_path = Path(module_file_path)

        module_name = file_path.stem

        path_parts = file_path.parts
        
        task_module_name = '#' + path_parts[-3] + '#' + path_parts[-2] + '.' + module_name

        module_path = os.path.dirname(module_file_path)
        path = os.path.dirname(module_path)

        self.module_file_path = module_file_path
        self.module_path = module_path
        self.module_name = module_name
        self.path = path
        self.task_module_name = task_module_name

        # Create a child logger that inherits CMeta's configuration
        self.logger = logger if logger is not None else self.cm.logger.getChild(self.task_module_name)

        if self.cm.debug:
            import inspect

            stack = inspect.stack()

            caller_frame = stack[1]

            self.logger.debug(f"Initializing CTask class from: {caller_frame.filename}:{caller_frame.lineno}")


    ############################################################
    def customize_cache_artifact(self, *args, **params):
        return {'return':0}

