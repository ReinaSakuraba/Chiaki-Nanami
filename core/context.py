import collections
import sys

from discord.ext import commands


class _ContextSession(collections.namedtuple('_ContextSession', 'ctx')):
    __slots__ = ()

    def __await__(self):
        return self.ctx._acquire().__await__()

    async def __aenter__(self):
        return await self.ctx._acquire()

    async def __aexit__(self, exc_type, exc, tb):
        return await self.ctx._release(exc_type, exc, tb)


class Context(commands.Context):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session = None

    @property
    def clean_prefix(self):
        """The cleaned up invoke prefix. (mentions are @name instead of <@id>)."""
        user = self.bot.user
        return self.prefix.replace(user.mention, f'@{user.name}')

    @property
    def db(self):
        """The bot's database connection interface, if applicable."""
        return getattr(self.bot, 'db', None)

    async def _acquire(self):
        if self.session is None:
            self.session = await self.db.get_session().__aenter__()
        return self.session

    def acquire(self):
        """Acquires a database session.

        Can be used in an async context manager: ::
            async with ctx.acquire():
                await ctx.db.execute(...)
        or: ::
            await ctx.acquire()
            try:
                await ctx.db.execute(...)
            finally:
                await ctx.release()
        """
        # DatabaseInterface.get_session doesn't support a timeout kwarg sadly...
        return _ContextSession(self)

    async def _release(self, exc_type, exc, tb):
        """Internal method used for properly propagating the exceptions
        in the session's __aexit__.

        This is the method that is called automatically by the bot,
        NOT Context.release.
        """
        if self.session is not None:
            suppress = await self.session.__aexit__(exc_type, exc, tb)
            self.session = None
            return suppress

    async def release(self):
        """Closes the current database session.

        Useful if needed for "long" interactive commands where
        we want to release the connection and re-acquire later.
        """
        return await self._release(*sys.exc_info())
