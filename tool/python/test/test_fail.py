from cmeta import CMeta

#cm = CMeta(debug=True)
cm = CMeta(fail_on_error=True)

r = cm.access({'category': 'task',
               'command': 'run',
               'arg1': 'setup-tool',
               'arg2': 'python',
               'update': True,
               'con': True,
    })
print (r)
