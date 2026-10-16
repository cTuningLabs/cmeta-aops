"""cMeta as a tool in the selected Python.

Authors: Grigori Fursin. Licensed under Apache-2.0; see LICENSE in the repo root.
"""

import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool


class CTool(InitCTool):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path=__file__, **kwargs)

    def check_params(self, ctx, params, cparams=None):
        options = params.get('with') or {}
        if options.get('file') and options.get('url'):
            return self.cm.error('cmeta: choose with.file or with.url, not both')
        if options.get('url_tag') and not options.get('url'):
            return self.cm.error('cmeta: with.url_tag requires with.url')
        if params.get('version') and (options.get('file') or options.get('url')):
            return self.cm.error('cmeta: a source selects its version; use with.url_tag for a Git ref')
        # A source explicitly requested on a cache miss must be installed even if
        # an unrelated distribution happens to have the same version number.
        if options.get('file') or options.get('url'):
            params['skip_detect'] = True
        return {'return': 0}

    def customize_install_cmd(self, ctx, install_cmd, params, env=None, timeout=None, uninstall_cmd=None):
        options = params.get('with') or {}
        quote = self.cm.utils.files.quote_path
        source = options.get('file') or options.get('url')
        if str(options.get('url', '')).startswith('git+'):
            result = self.cm.access(dict(category='task,c36be4b9314a45e0', command='run',
                arg1='setup,a2f9b61079ce4333', name='git,959d8c0fbc004bd0', ctx=ctx,
                quiet=ctx['control'].get('quiet', False), con=ctx['control'].get('con', False)))
            if self.cm.catch_error(result, fail16=True):
                return result
        if options.get('file'):
            source = os.path.abspath(os.path.expanduser(source))
        elif options.get('url_tag'):
            source += '@' + options['url_tag']
        upgrading = params.get('control', {}).get('upgrade', False)
        if source:
            # Put flags before the source so pip's -e consumes that source.
            install_cmd = '{{global.python.qpath}} -m pip install ' + (options.get('flags', '') + ' ' if options.get('flags') else '') + quote(source)
        elif not params.get('version') and not upgrading:
            install_cmd = '{{global.python.qpath}} -m pip install ' + quote('cmeta==' + self.cdesc['default_version'])
        if upgrading:
            install_cmd += ' --upgrade'
        if options.get('flags') and not source:
            install_cmd += ' ' + options['flags']
        return {'return': 0, 'install_cmd': install_cmd}
