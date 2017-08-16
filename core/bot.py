import asyncio
import collections
import contextlib
import discord
import functools
import inspect
import logging
import random

from datetime import datetime
from discord.ext import commands
from more_itertools import always_iterable

from .formatter import ChiakiFormatter

from cogs.utils.database import Database
from cogs.utils.misc import duration_units, file_handler

# The bot's config file
import config

log = logging.getLogger(__name__)
log.addHandler(file_handler('chiakinanami'))


_MINIMAL_PERMISSIONS = [
    'send_messages',
    'embed_links',
    'add_reactions',
    'attach_files'
    "use_external_emojis",
]

_FULL_PERMISSIONS = [
    *_MINIMAL_PERMISSIONS,
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "kick_members",
    "ban_members",
    "create_instant_invite",
    
    "manage_messages",
    "read_message_history",
    
    "connect",
    "speak",
    "mute_members",
    "deafen_members",
    "move_members"
]

def _make_permissions(*permissions):
    perms = discord.Permissions.none()
    perms.update(**dict.fromkeys(permissions, True))
    return perms

_MINIMAL_PERMISSIONS = _make_permissions(*_MINIMAL_PERMISSIONS)
_FULL_PERMISSIONS = _make_permissions(*_FULL_PERMISSIONS)
del _make_permissions


MAX_FORMATTER_WIDTH = 90

def _callable_prefix(bot, message):
    return (*commands.when_mentioned(bot, message),
            *bot.custom_prefixes.get(message.guild, bot.default_prefix))

_chiaki_formatter = ChiakiFormatter(width=MAX_FORMATTER_WIDTH, show_check_failure=True)


class Chiaki(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=_callable_prefix, 
                         formatter=_chiaki_formatter,
                         description=config.description,
                         pm_help=None)

        self.message_counter = 0
        self.custom_prefixes = Database('customprefixes.json')
        self.databases = [self.custom_prefixes, ]
        self.cog_aliases = {}

        self.reset_requested = False

        for ext in config.extensions:
            # Errors should never pass silently, if there's a bug in an extension,
            # better to know now before the bot logs in, because a restart
            # can become extremely expensive later on, especially with the 
            # 1000 IDENTIFYs a day limit.
            self.load_extension(ext)

    async def close(self):
        await self.dump_databases()
        await super().close()

    def add_cog(self, cog):
        members = inspect.getmembers(cog)
        for name, member in members:
            # add any databases
            if isinstance(member, Database):
                self.add_database(member)

        # cog aliases
        for alias in getattr(cog, '__aliases__', ()):
            if alias in self.cog_aliases:
                raise discord.ClientException(f'"{alias}" already has a cog registered')
            self.cog_aliases[alias] = cog

        # add to namespace
        cog.__hidden__ = getattr(cog, '__hidden__', False)
        super().add_cog(cog)

    def remove_cog(self, cog_name):
        cog = self.cogs.get(cog_name)
        if cog is None:
            return
        super().remove_cog(cog_name)

        members = inspect.getmembers(cog)
        for name, member in members:
            # remove any databases
            if isinstance(member, Database):
                self.remove_database(member)

        # remove cog aliases
        self.cog_aliases = {alias: real for alias, real in self.cog_aliases.items() if real is not cog}

    @contextlib.contextmanager
    def temp_listener(self, func, name=None):
        """Context manager for temporary listeners"""
        self.add_listener(func, name)
        try:
            yield
        finally:
            self.remove_listener(func)

    def add_database(self, db):
        self.databases.append(db)
        log.info(f"database {db.name} successfully added")

    def remove_database(self, db):
        if db in self.databases:
            self.loop.create_task(db.dump())
            self.databases.remove(db)
        log.info(f"database {db.name} successfully removed")

    async def dump_databases(self):
        await asyncio.gather(*(db.dump() for db in self.databases))

    async def change_game(self):
        await self.wait_until_ready()
        while True:
            name = random.choice(config.games)
            await self.change_presence(game=discord.Game(name=name))
            await asyncio.sleep(random.uniform(0.5, 10) * 60)

    def run(self):
        super().run(config.token, reconnect=True)

    # ------ Config-related properties ------

    @discord.utils.cached_property
    def minimal_invite_url(self):
        return discord.utils.oauth_url(self.user.id, _MINIMAL_PERMISSIONS)

    @discord.utils.cached_property
    def invite_url(self):
        return discord.utils.oauth_url(self.user.id, _FULL_PERMISSIONS)

    @property
    def default_prefix(self):
        return always_iterable(config.command_prefix)

    @property
    def colour(self):
        return config.colour

    # ------ misc. properties ------

    @property
    def support_invite(self):
        # The following is the link to the bot's support server.
        # You are allowed to change this to be another server of your choice. 
        # However, doing so will instantly void your warranty.
        # Change this at your own peril.
        return 'https://discord.gg/WtkPTmE'

    @property
    def uptime(self):
        return datetime.utcnow() - self.start_time

    @property
    def str_uptime(self):
        return duration_units(self.uptime.total_seconds())

    @property
    def all_cogs(self):
        return collections.ChainMap(self.cogs, self.cog_aliases)
