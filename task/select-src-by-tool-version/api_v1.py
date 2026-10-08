"""
Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

import os
import re
import shlex

from task_c36be4b9314a45e0.api.ctask import InitCTask

COMPARATOR = re.compile(r'^\s*(>=|<=|==|!=|>|<|=)?\s*([0-9][0-9A-Za-z.\-+]*)\s*$')

# What each comparator accepts of compare_versions(version, reference): '<', '=' or '>'
ACCEPTS = {'>=': '>=', '<=': '<=', '>': '>', '<': '<', '==': '=', '=': '=', '!=': '<>'}


def version_matches(version, spec, compare):
    """
    True when the version satisfies the spec: comparators joined by commas, all of which must
    hold ('>=1.0.0', '>=0.26.2,<1.0.0', '1.1.0'). compare(a, b) returns '<', '=' or '>'.
    An empty spec matches every version.
    """
    for part in str(spec or '').split(','):
        if not part.strip():
            continue
        m = COMPARATOR.match(part)
        if not m:
            raise ValueError(f'version rule "{part.strip()}" is not <comparator><version>')
        if compare(str(version), m.group(2)) not in ACCEPTS[m.group(1) or '==']:
            return False
    return True


def select_rule(version, rules, compare):
    """The first rule whose 'version' spec the version satisfies (a rule without one always does), or None."""
    for rule in rules or []:
        if version_matches(version, rule.get('version'), compare):
            return rule
    return None


class CTask(InitCTask):
    """
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def run(self,
            ctx: dict,                  # cMeta context
            tool: str = None,           # The tool whose version decides: its key in the global context (mojo, python, gcc ...)
            version: str = None,        # A version given directly instead of the tool's
            rules: list = None,         # [{'version': '>=1.0.0', 'src_dir': 'src-v2'}, ...]: the first that matches wins
            program_path: str = None,   # The program artifact: '{{local.selected-program.path}}'
            src_file_names = None,      # The program's source files: '{{local.src_file_names}}'
    ):

        """
        Select the source folder of a program by the version of a tool.

        Returns:
            dict: A cMeta dictionary with the following keys:
                - **return** (int): 0 if success, >0 if error.
                - **error** (str): Error message if `return > 0`.
                - **tool_version** (str): the version that was compared.
                - **src_dir** (str): the selected folder, when a rule matched.
                - **rule** (dict): the rule that matched, when one did.

            When a rule matches, the local context of the pipeline gets src_dir, src_path and the
            source file lists made from them (add_to_local); otherwise nothing changes and the
            program keeps its default sources.
        """

        con = ctx['control'].get('con', False)
        verbose = ctx['control'].get('verbose', False)
        space = '  ' * ctx['tasks']['nested_call'] if verbose else ''

        if not version:
            if not tool:
                return self.cm.error(f'"tool" or "version" is needed in "{__file__}"')
            version = ctx['tasks']['global'].get(tool, {}).get('version')
            if not version:
                return self.cm.error(f'the version of tool "{tool}" is not known: this step must come after the setup of the tool in "{__file__}"')

        def compare(a, b):
            r = self.cm.utils.common.compare_versions(a, b)
            if r['return'] > 0:
                raise ValueError(r.get('error', f'versions "{a}" and "{b}" cannot be compared'))
            return r['comparison']

        try:
            rule = select_rule(version, rules, compare)
        except ValueError as e:
            return self.cm.error(f'{e} in "{__file__}"')

        result = {'return': 0, 'tool_version': str(version)}
        if not rule:
            return result

        src_dir = rule.get('src_dir')
        if not src_dir:
            return self.cm.error(f'the rule {rule} has no "src_dir" in "{__file__}"')
        if not program_path:
            program_path = ctx['tasks']['local'].get('selected-program', {}).get('path')
        if not program_path:
            return self.cm.error(f'"program_path" is needed (the program artifact) in "{__file__}"')

        src_path = os.path.join(program_path, src_dir.replace('//', os.sep))
        if not os.path.isdir(src_path):
            return self.cm.error(f'the source folder "{src_path}" of the rule {rule} does not exist')

        add_to_local = {'src_dir': src_dir, 'src_path': src_path}

        if src_file_names is None:
            src_file_names = ctx['tasks']['local'].get('src_file_names')
        if isinstance(src_file_names, str):
            src_file_names = shlex.split(src_file_names)
        if rule.get('src_file_names'):
            src_file_names = rule['src_file_names']
            add_to_local['src_file_names'] = list(src_file_names)
        if src_file_names:
            names = [n.replace('//', os.sep) for n in src_file_names]
            for name in names:
                if not os.path.isfile(os.path.join(src_path, name)):
                    return self.cm.error(f'the source file "{name}" is not in "{src_path}" (rule {rule})')
            add_to_local['src_file_names_str'] = ' '.join(names)
            add_to_local['src_file_names_str_with_path'] = ' '.join(os.path.join(src_path, n) for n in names)
            add_to_local['src_file_names_list'] = list(src_file_names)

        if con:
            what = f'{tool} {version}' if tool else f'version {version}'
            print(f'{space}INFO: sources from "{src_dir}": {what} matches "{rule.get("version", "any version")}"')

        result.update({'src_dir': src_dir, 'rule': rule, 'add_to_local': add_to_local})
        return result
