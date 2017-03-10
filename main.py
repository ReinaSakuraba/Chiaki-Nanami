import subprocess
import sys

from functools import partial

def run(log_result=False):
    python = sys.executable
    cmd = (python, 'chiaki.py')
    for _ in iter(partial(subprocess.call, cmd), 0):
        print("Resetting Chiaki...")

if __name__ == '__main__':
    run()
