import json
import subprocess
import sys

from functools import partial
from itertools import takewhile

def _load_config():
    with open('config.json') as f:
        return json.load(f)

# Hope I can find a way to not repeat myself here
_config = _load_config()
RESTART_CODE = _config.get('restart_code', 69)

def _runner():
    python = sys.executable
    cmd = (python, 'chiaki.py')
    while True:
        yield subprocess.call(cmd)

def run(log_result=False):
    for i, code in enumerate(takewhile(lambda code: code == RESTART_CODE, _runner()), start=1):
        print(f"Resetting Chiaki Attempt #{i}...")

if __name__ == '__main__':
    run()
