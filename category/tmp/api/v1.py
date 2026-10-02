"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.

The tmp category: disposable working folders (sandboxes) as cMeta artifacts, by default in the
local repository, so they can be listed, found by their tags and removed with cMeta:

    cx tmp list                          cx tmp find --tags=test-session
    cx tmp delete <name> --force         cx tmp prune --days=7 [--tags=...] [--force]

The test-session task makes one per session; its record is a log artifact of the same name,
which stays when the sandbox goes.
"""

import datetime

from cmeta.category import InitCategory

class Category(InitCategory):
    """
    """

    def __init__(
        self,
        *args,  # Positional argument value.
        **kwargs,  # Value for kwargs.
    ):
        """
        __init__ function.

        Args:
            *args: Positional argument value.
            **kwargs: Value for kwargs.

        Returns:
            dict: Operation result.

        Raises:
            Exception: Propagated runtime errors, if any.
        """
        super().__init__(*args, module_file_path = __file__, **kwargs)


    ############################################################
    def prune_(
        self,
        ctx: dict,  # cMeta context.
        tags: str = None,  # Only the tmp artifacts with these tags.
        days: float = 7,  # Only those created more than this many days ago.
        force: bool = False,  # Delete them (without it, only list them).
    ):
        """
            List, and with --force delete, the tmp artifacts created more than --days ago.

            Args:
                ctx (dict): cMeta context.
                tags (str | list | None): Only the tmp artifacts with these tags.
                days (float): Only those created more than this many days ago (default 7).
                force (bool): Delete them; without it the command only lists them.

            Returns:
                dict: A cMeta dictionary with the following keys:
                    - **return** (int): 0 if success, >0 if error.
                    - **error** (str): Error message if `return > 0`.
                    - **artifacts** (list): The old tmp artifacts (alias, UID, path, created).
                    - **deleted** (int): How many were deleted.
        """

        con = ctx['control'].get('con', False)

        r = self.cm.access({'category': ctx['category'], 'command': 'find', 'tags': tags})
        if r['return'] > 0: return r

        limit = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days = float(days or 0))

        old = []
        for a in r['artifacts']:
            created = None
            try:
                created = datetime.datetime.fromisoformat(str(a['cmeta'].get('creation_timestamp')))
            except ValueError:
                pass
            if created is None or created.tzinfo is None or created > limit:
                continue
            parts = a['cmeta_ref_parts']
            old.append({'alias': parts.get('artifact_alias'), 'uid': parts.get('artifact_uid'),
                        'repo': parts.get('repo_alias'), 'path': a['path'], 'created': created.isoformat()})

        deleted = 0
        for a in old:
            if force:
                ref = f"{a['repo']}:{a['alias']},{a['uid']}" if a['repo'] else f"{a['alias']},{a['uid']}"
                r = self.cm.access({'category': ctx['category'], 'command': 'delete', 'arg1': ref, 'force': True})
                if r['return'] > 0: return r
                deleted += 1
            if con:
                print (f"{'deleted' if force else 'old'}: {a['alias']} ({a['created'][:10]}) {a['path']}")

        if con:
            print ('')
            print (f'{deleted} deleted' if force else f'{len(old)} tmp artifact(s) older than {days} days; add --force to delete them')

        return {'return': 0, 'artifacts': old, 'deleted': deleted}
