import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        temp_file = ctx['tasks']['local']['generate-temp-file-target-xpu']['temp_file']
        encoding = ctx['tasks']['local']['encoding']

        if not os.path.isfile(temp_file):
            return self.cm.error(f'temp file "{temp_file}" not found in "{__file__}" ({__name__})')

        r = self.cm.utils.files.read_file(temp_file, encoding = encoding)
        if self.cm.catch_error(r): return r

        data = r['data'].strip()
        ldata = data.lower()

        if 'intel' not in ldata and 'graphics' not in ldata:
            return self.cm.error(f'Intel Graphics is not detected in "{__file__}"')

        features = {'output': data}

        # !FGG: just a prototype - can be extended

        result = {
          'return':0,
          'features': features
        }

        return result
