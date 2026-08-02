"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

from pathlib import Path
import os
import logging

class InitCProgram:
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
        
        task_module_name = '___' + path_parts[-3] + '___.' + path_parts[-2] + '.' + module_name

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

            self.logger.debug(f"Initializing CProgram class from: {caller_frame.filename}:{caller_frame.lineno}")

    ############################################################
    def init_call(self,
                  ctx,
                  category = None,
                  command = None,
                  task = None,
        ):

        params = {}

        params['category'] = category if category else ctx['category']
        params['command'] = command if command else 'run'
        if task: params['arg1'] = task

        ctx_control = ctx['control']

        for key in ['con', 'verbose', 'quiet']:
            if key in ctx_control:
                params[key] = ctx_control[key]
            
        return {'return':0, 'params': params}

 
