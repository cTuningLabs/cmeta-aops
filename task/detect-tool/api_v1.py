import os

from task_c36be4b9314a45e0.api.ctask import InitCTask

class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def customize_cache_artifact(self,
                                 state,
                                 cache_alias_template,
                                 cache_alias_extra,
                                 cache_meta,
                                 cache_tags,
                                 cache_params,
                                 params,
                                 **extra,
        ):

        result = {'return':0}

        return result

    ############################################################
    def run(self,
            state: dict,            # cMeta state
            tool_name: str = None,  # Tool name
            tool_tags: str = None,  # Tool tags
    ):

        """
        Detect tool.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
        """

        self.logger.debug("RUNNING TASK detect-tool run")

        con = state['control'].get('con', False)
        quiet = state['control'].get('quiet', False)
        verbose = state['control'].get('verbose', False)
        result = {'return': 0}

        # Select tool
        ###########################################################################################
        # SELECT TOOL ARTIFACT

        # Call base find function to find an artifact with a website
        p = {'category':'utils,234ce5e3262e4d52',
             'command':'select_artifact',
             'select_category':'tool,c393ba5c6fa14f66',
             'select_artifact':tool_name,
             'select_tags':tool_tags,
             'con':con,
             'quiet':quiet}

        r = self.cm.access(p)
        if r['return']>0: 
            ret = r['return']
            if ret == 16: ret = 1
            return self.cm._error(r['error'], ret, None, self.cm.fail_on_error)

        input('xyz')

        artifact = r['artifact']

        artifact_path = artifact['path']
        cmeta = artifact['cmeta']
        cmeta_ref_parts = artifact['cmeta_ref_parts']





        return result
