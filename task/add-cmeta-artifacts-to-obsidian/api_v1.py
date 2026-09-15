"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import shutil

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            category: str = None,
            artifact: str = None, 
            target_path: str = None,
            force: bool = False,
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.


        """
        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * (ctx['tasks']['nested_call'] + 1) if verbose else ''

        _global = ctx['tasks']['global']
        _aggregated = ctx['tasks']['aggregated']

        # Check params
        if target_path is None:
            return self.cm.error(f'specify "target_path" with Obsidian vault to create symbolic links for cMeta artifacts')

        if os.path.isdir(target_path):
            clean = False

            if force:
                clean = True
            else:
                if con:
                   print ('')
                   print (f'Target path exists: {target_path}')
                   print ('')

                   x = input('Would you like to delete and rebuild it (y/N): ').strip().lower()

                   if x in ['y', 'yes']:
                       clean = True

            if clean:
                print ('')
                print (f'Cleaning "{target_path}"')
                print ('')

                shutil.rmtree(target_path)
        
        os.makedirs(target_path, exist_ok = True)


        # List all cMeta artifacts
        rr = self.cm.access({
            'category': 'utils,234ce5e3262e4d52',
            'command': 'artifacts',
            'con': con,
            'arg1': category,
            'arg2': artifact,
            'con': con,
            'verbose': verbose,
        })
        if rr['return']>0: return rr

        artifacts = rr.get('artifacts', [])

        for a in artifacts:
            path = a['path']

            artifact = os.path.basename(path)

            # Check shards
            sharding_slices_num = a.get('sharding_slices_num', 0)

            r = self.cm.utils.files.remove_dirs_from_path(path, sharding_slices_num + 1)
            if r['return']>0: return r

            category_path = r['path']

            category_alias = os.path.basename(category_path)

            target_path_artifact = os.path.join(target_path, category_alias, artifact)

            if con:
                print (f'  * Linking "{target_path_artifact}" -> "{path}"')

            parent = os.path.dirname(target_path_artifact)
            os.makedirs(parent, exist_ok=True)

            if not os.path.isdir(target_path_artifact):

                os.symlink(
                    path,
                    target_path_artifact,
                    target_is_directory=True,
                )

        return {'return':0}

