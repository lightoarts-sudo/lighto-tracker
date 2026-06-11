import sys
try:
    import googleapiclient
    print("OK")
except ImportError as e:
    print(f"Not installed: {e}")
    sys.exit(1)