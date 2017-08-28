import asyncio
import contextlib
import heapq
import logging

from collections import namedtuple
from datetime import datetime
from more_itertools import consume, iter_except

from .misc import duration_units

log = logging.getLogger(__name__)


class TimerEntry(namedtuple('TimerEntry', 'when args')):
    __slots__ = ()

    @property
    def dt(self):
        return datetime.utcfromtimestamp(self.when)


class Scheduler:
    """Manages timing related things.

    This is largely used as a workaround for asyncio.sleep(), as asyncio.sleep()
    cannot sleep for extremely long periods of time.
    """
    MAX_SLEEP_TIME = 60 * 60 * 24   # Timeouts shouldn't exceed one day

    def __init__(self, bot, dispatch=None, *, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()
        self.loop = loop

        self.bot = bot
        self.dispatch = dispatch

        self.pending = asyncio.PriorityQueue()
        self._current = None
        self._next_timestamp = None
        self._runner = self.loop.create_task(self._update())

    def __del__(self):
        self.close()

    async def _update(self):
        while True:
            self._current = timer = await self.pending.get()
            self._next_timestamp = timer.when
            delta = self._next_timestamp - datetime.utcnow().timestamp()
            log.debug('sleeping for %s seconds', delta)

            while delta > 0:
                await asyncio.sleep(min(self.MAX_SLEEP_TIME, delta))
                delta -= self.MAX_SLEEP_TIME
            log.debug('entry %r is done, dispatching now.', timer)
            self.bot.dispatch(self.dispatch, timer)

    def _reset_task(self):
        with contextlib.suppress(BaseException):
            self._runner.cancel()

        self._runner = self.loop.create_task(self._update())

    def add_entry(self, entry):
        """Adds a new timestamp entry for the queue."""
        self.pending.put_nowait(entry)

        if self._next_timestamp and entry.when <= self._next_timestamp:
            self.pending.put_nowait(self._current)
            self._reset_task()

    def remove_entry(self, entry):
        """Removes a timestamp entry from the queue."""
        # Warning: Horribly bad practice, but there's no easy way to do this otherwise

        # The current entry was already popped from the queue, don't try to remove it again.
        if entry != self._current:
            self.pending._queue.remove(entry)
            heapq.heapify(self.pending._queue)
            self.pending.put_nowait(self._current)

        # There are two things that could've happened here:
        # 1. The entry was removed, and the internal list was reset
        # 2. The entry was the current entry, and we did nothing
        # Either way we have to reset the task, as the current one isn't good anymore.
        self._reset_task()

    def stop(self):
        """Stops the scheduler.

        This doesn't clear all the entries, use close() for that.
        """
        if not self._runner.done():
            with contextlib.suppress(BaseException):
                self._runner.cancel()

    def close(self):
        """Closes the running task, and removes all the entries."""
        self.stop()
        consume(iter_except(self.pending.get_nowait, asyncio.QueueEmpty))
        self._current = None

