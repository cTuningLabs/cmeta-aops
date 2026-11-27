"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

from pathlib import Path
import os
import logging

class InitCTool:
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

            self.logger.debug(f"Initializing CTool class from: {caller_frame.filename}:{caller_frame.lineno}")

    ############################################################
    def target_backends(self, compute = None):
        """
        Which backend of this tool each compute target selects: {target: backend}, in the order the tool ranks
        them. The tool's own `target_backends` (its _desc.yaml) first; a target of the request that it does not
        list - a target of another repository, a private backend - says it itself: `backends: {<this tool's
        storage key>: <backend>}` in the target's _desc.yaml (task::target--<name>, found by its alias among the
        repositories plugged in). Targets and what they select are data found by query: a tool's code holds no
        list of target names.
        """
        table = dict(self.cdesc.get('target_backends') or {})
        key = str(self.cdesc.get('storage_key') or '')

        for c in compute or []:
            if c in table or not key:
                continue
            r = self.cm.access({'category': 'task,c36be4b9314a45e0', 'command': 'find', 'arg1': 'target--' + str(c),
                                'load_files': ['_desc'], 'con': False})
            if r.get('return', 1) == 0 and len(r.get('artifacts') or []) == 1:
                desc = ((r['artifacts'][0].get('loaded_files') or {}).get('_desc') or {}).get('data') or {}
                backend = (desc.get('backends') or {}).get(key)
                if backend:
                    table[str(c)] = str(backend)

        return table
