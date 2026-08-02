"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def init(self,
             ctx: dict,
             params: dict,
    ):
        """
        We need this function to resolve name if not provided,
        to be able to customize storage_key and cache_artifact properly.

        We can also add extra checks on unified params here.
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TASK list-git-tags init")

        r = self.cm.check_params(params, [
                'url', 'sort', 'limit', 'output_file',
            ], __name__)
        if self.cm.catch_error(r): return r

        r = self.cm.utils.files.gen_temp_filepath()
        if self.cm.catch_error(r): return r

        tmp_file = r['filepath']

        ctx['tasks']['local']['tmp_file'] = tmp_file

        return {'return':0}

    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            url: str = None,    
            sort: bool = True,
            limit: int = None,
            output_file: str = None,
    ):

        """
        Clone git repo.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK list-git-tags run")

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        result = {'return':0}

        tmp_file = ctx['tasks']['local']['tmp_file']

        r = self.cm.utils.read_file(tmp_file)
        if self.cm.catch_error(r): return r

        os.remove(tmp_file)

        data = r['data']

        lines = data.splitlines()

        tags = []
        versions = []

        for l in lines:
            j = l.find('refs/tags/')
            if j>0:
                tag = l[j+10:].strip()

                v = None
                j = self.cm.utils.common.first_digit_pos(tag)
                if j>=0:
                    v = tag[j:].strip()

                x = {'tag': tag, 'version':v}

                tags.append(tag)
                versions.append(x)

        if sort:
            if versions:
                sort_keys = ['@version-']

                dversions = sorted(
                   versions,
                   key=lambda v: self.cm.utils.common.build_sort_key(v, sort_keys),
                )

                versions = [x['version'] for x in dversions]
                tags = [x['tag'] for x in dversions]

        result['data'] = data
        result['tags'] = tags
        result['versions'] = versions

        l = 0
        if con and tags:
            print ('')
            for t in tags:
                l += 1

                if limit and l>int(limit):
                    break

                print (t)

        if output_file:
           r = self.cm.utils.files.write_file(output_file, '\n'.join(tags))
           if self.cm.catch_error(r): return r

        return result

