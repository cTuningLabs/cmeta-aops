"""Durable mutable state. Licensed under Apache-2.0; see COPYRIGHT and LICENSE."""

from cmeta.category import InitCategory


class Category(InitCategory):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def create(self, params):
        """Create protected mutable state; explicitly unprotect before deleting it."""
        return self._protected(params, 'create')

    def get(self, params):
        """Find state or create it protected against ordinary removal."""
        return self._protected(params, 'get')

    def _protected(self, params, command):
        request = self._prepare_input_from_params(dict(params), base=True)
        request['command'] = command
        request['meta'] = dict(params.get('meta') or {})
        request['meta'].setdefault('permanent', True)
        return self.cm.access(request)
