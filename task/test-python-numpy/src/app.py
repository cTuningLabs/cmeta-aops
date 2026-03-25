import sys
import numpy as np

sys.stdout.flush()

if '--extra_line=True' in sys.argv:
    for _ in range(100):
        print ('')

print ('')
print ('*'*40)
print ("Python version:", sys.version)
print ("Python executable path:", sys.executable)
print ("NumPy version:", np.__version__)
print ('*'*40)
print ('')

sys.stdout.flush()
