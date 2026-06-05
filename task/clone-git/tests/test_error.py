from cmeta import CMeta

#cm = CMeta(fail_on_error=True)
cm = CMeta()

r = cm.access({'category':'task',
               'command':'run',
               'arg1':'clone-git',
               'con':True,
    })
cm.catch_error_and_halt(r)
print(r)

