"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""
from cmeta.category import InitCategory


class Category(InitCategory):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def run(self, params):
        """Run one or several definitions; no name lists them. See cxt sync --info."""
        p = self._prepare_input_from_params(params)
        name = p.pop('arg1', None)
        p.update(category=self.cmeta['uses_categories']['task'], command='run',
                 arg1=self.cmeta['uses_artifacts']['task::sync'], name=name)
        return self.cm.access(p)
