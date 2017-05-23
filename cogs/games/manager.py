import asyncio
import contextlib

def _iter_except(func, *exceptions, start=None):
    'Yield a function repeatedly until it raises an exception'
    try:
        if start is not None:
            yield start()
        while True:
            yield func()
    except exceptions:
        pass

class SessionManager:
    def __init__(self):
        self.sessions = {}

    def session_exists(self, key):
        return key in self.sessions

    def get_session(self, key):
        return self.sessions.get(key)

    @contextlib.contextmanager
    def temp_session(self, key, value):
        """Context-manager to make a temporary session."""
        self.sessions[key] = value
        try:
            yield value
        finally:
            self.sessions.pop(key, None)

    def cancel_all(self, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        popitem_iter = _iter_except(self.sessions.popitem, KeyError)
        stop_tasks = (inst.stop(force=True) for _, inst in popitem_iter)
        loop.create_task(asyncio.gather(*stop_tasks))   