"""
Copyright (C) 2025-2026 Grigori Fursin and cTuning Labs. 
All rights reserved.

Proprietary and confidential.
This software may not be copied, modified, distributed, or used
without explicit permission from the copyright holder.
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

