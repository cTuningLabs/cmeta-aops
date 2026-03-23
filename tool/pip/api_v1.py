import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def init(self,
             ctx: dict,
             params: dict = {},
    ):
        """
        Mostly used to update storage_key
        We need to check package before further key expansions from desc
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL python api_v1 init")

        result = {'return':0}

        _with = params.setdefault('with', {})

        package = _with.get('package')
        if not _with:
            package = params.get('arg3')
            if package:
                _with['package'] = params.pop('arg3')

        if not package:
            return self.cm.error(f'"package" is not defined in {__file__}. Set it with --with.package=')

        return result

    ############################################################
    def check_params(self,
                     ctx: dict,
                     params: dict = {},
                     cparams: dict = {},
    ):
        """
        """
        if self.cm.debug:
            self.logger.debug("RUNNING TOOL python api_v1 check_params")

        result = {'return':0}

        return result

    ############################################################
    def customize_install_cmd(self,
                              ctx: dict,
                              install_cmd: str = None,
                              params: dict = {},
                              *misc: dict,
    ):
        """
        """

        result = {'return':0}

        _with = params.get('with', {})

        package_file = _with.get('package_file')
        if package_file:
            # substitute package with package file in install_cmd
            result['install_cmd'] = install_cmd.replace('{{params.with.package}}', '{{params.with.package_file}}')

        return result

    ############################################################
    def customize_cache_artifact(self,
                                 ctx,
                                 result,
                                 params,
                                 cache_tags,
                                 cache_params,
        ):

        if self.cm.debug:
            self.logger.debug("RUNNING TASK tool python customize_cache_artifact")

        _with = params.get('with', {})
#        if _with:
#            cache_params_with = cache_params.setdefault('with',{})
#            cache_params_with.update(_with)

        package = _with['package']

        cache_extra_alias = result['cache_extra_alias']
        cache_extra_alias += self.cache_sep + package
        result['cache_extra_alias'] = cache_extra_alias

        return {'return':0}
