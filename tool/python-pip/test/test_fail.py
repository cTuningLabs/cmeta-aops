"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs.

Licensed under the Apache License, Version 2.0.
See the COPYRIGHT and LICENSE files in the project root for details.
"""

from cmeta import CMeta

#cm = CMeta(debug=True)
cm = CMeta(fail_on_error=True)

r = cm.access({'category': 'task',
               'command': 'run',
               'arg1': 'setup',
               'arg2': 'python',
               'update': True,
               'con': True,
    })
print (r)

