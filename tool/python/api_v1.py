import os

from tool_c393ba5c6fa14f66.api.ctool import InitCTool

class CTool(InitCTool):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def sort_paths(self,
                   ctx: dict,
                   paths: dict,
    ):
        """
        """

        if self.cm.debug:
            self.logger.debug("RUNNING TOOL python api_v1 sort_paths")


        r = {'return':1, 'error':'xyz'}

        if self.cm.catch_error(r): return r

        print (paths)
        input('xyz')


        return {'return':0}
