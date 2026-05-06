import sys

print('Hello World from Python!')

args = sys.argv[1:]
if len(args)>0:
    print ('')
    print ('Command line arguments:')
    print ('')
    for arg in args:
    	print(arg)

