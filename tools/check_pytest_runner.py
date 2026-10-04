import os
import sys

# ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pytest_runner import run_pytest_for_target


class DummySocket:
    def emit(self, event, data, room=None):
        print(f"EMIT {event}: {data}")


sock = DummySocket()
run_pytest_for_target(sock, 'local', 'left_leg')
import time
# give the thread some time to run
time.sleep(2)
print('checker done')
