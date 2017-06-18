import asyncio
import contextlib

from ..utils.compat import iter_except
from ..utils.misc import maybe_awaitable

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

        popitem_iter = iter_except(self.sessions.popitem, KeyError)
        stop_tasks = (maybe_awaitable(inst.stop) for _, inst in popitem_iter)
        loop.create_task(asyncio.gather(*stop_tasks))   