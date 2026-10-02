import copy
import os
import platform

from task_c36be4b9314a45e0.api.ctask import InitCTask

from . import logic


def host_fingerprint():
    """Cheap facts that differ when a cache entry is used on another machine."""
    return {'node': platform.node(), 'machine': platform.machine(), 'cpus': os.cpu_count()}


def is_stale(result, fp):
    """True when a cached result was made on another machine than the one with fingerprint fp."""
    cached = result.get('host')
    if cached is None:
        # An entry from before the fingerprint: compare the CPU count it recorded
        return result.get('features', {}).get('logical_cpu_count') not in (None, fp['cpus'])
    return cached != fp


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,        # cMeta context
            **kwargs
    ):

        """
        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.


                  os: ['Windows', 'Linux', 'macOS']
        """

        con = ctx['control'].get('con', False)
        quiet = ctx['control'].get('quiet', False)
        verbose = ctx['control'].get('verbose', False)

        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        result = {
          'return':0,
          'features': logic.get_cpu_inventory(),
          'host': host_fingerprint(),
        }

        return result

    ############################################################
    def finish_dynamic_result(self,
                              ctx: dict,
                              result: dict = {},
                              params: dict = {},
    ):
        """
        A cached target keeps the CPU inventory of the run that created the entry, possibly on
        another machine (a copied or shared CMETA_HOME). Probing again takes over a second on
        Windows, so it happens only when cheap facts (host name, architecture, CPU count) differ.
        """

        fp = host_fingerprint()

        if is_stale(result, fp):
            result['features'] = logic.get_cpu_inventory()
            result['host'] = fp

        return {'return': 0, 'result': result}

