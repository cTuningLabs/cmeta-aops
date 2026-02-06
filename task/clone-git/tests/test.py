from cmeta import CMeta
cm = CMeta(debug=True)
r = cm.access({'category': 'task', 'command':'run', 'arg1':'git-clone', 'url':'https://github.com/ctuninglabs/cmeta', 'directory':'x', 'clean':True})
print (r)
