import sys
print(sys.executable)
try:
 import googleapiclient
 print('ok', googleapiclient.__file__)
except Exception as e:
 print('err', e)
