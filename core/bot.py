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

log = logging.getLogger(__name__)
log.addHandler(file_handler('chiakinanami'))

_default_bot_help = """\
*{0.description}*

To invite me to your server, use `->invite`, or just use this link:
<{0.invite_url}>

*Use `->modules` for all the modules with commands.
Or `->commands "module"` for a list of commands for a particular module.*
"""

_default_config = {
    'colour': "0xFFDDDD",

    'default_command_prefix': '->',
    'default_help': _default_bot_help,

    'restart_code': 69,
    'log': False,
}
del _default_bot_help

MAX_FORMATTER_WIDTH = 90
# small hacks to make command display all their possible names
commands.Command.all_names = property(lambda self: [self.name, *self.aliases])

class ChiakiBot(commands.Bot):
    def __init__(self, command_prefix, formatter=None, description=None, pm_help=False, **options):
        super().__init__(command_prefix, formatter, description, pm_help, **options)
        self.remove_command('help')

        self._config = collections.ChainMap(options.get('config', {}), _default_config)
        self.message_counter = 0
        self.custom_prefixes = Database('customprefixes.json')
        self.databases = [self.custom_prefixes, ]
        self.cog_aliases = {}

        self.reset_requested = False
        if self._config['restart_code'] == 0:
            raise RuntimeError("restart_code cannot be zero")

        self.loop.create_task(self._set_colour())

    # commands.ColourConverter.convert() is now a coro, 
    # so we have to set the colour this way
    async def _set_colour(self):
        self.colour = await commands.ColourConverter().convert(None, self._config['colour'])

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

    def load_extension(self, name):
        try:
            super().load_extension(name)
        except Exception as e:
            log.error(f"{type(e).__name__}: {e}")
            raise
        else:
            log.info(f"{name} successfully loaded")

    def unload_extension(self, name):
        try:
            super().unload_extension(name)
        except Exception as e:
            log.error(f"{type(e).__name__}: {e}")
            raise
        else:
            log.info(f"{name} successfully unloaded")

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

    # Just some looping functions
    async def change_game(self):
        await self.wait_until_ready()
        while True:
            name = random.choice(self._config['rotating_games'])
            await self.change_presence(game=discord.Game(name=name))
            await asyncio.sleep(random.uniform(0.5, 10) * 60)

    async def update_official_invite(self):
        await self.wait_until_ready()
        self.invites_by_bot = [inv for inv in await self.official_guild.invites() if inv.inviter.id == self.user.id]
        if not self.invites_by_bot:
            self.invites_by_bot.append(await official_guild.create_invite())

    # ------ Config-related properties ------

    @discord.utils.cached_property
    def permissions(self):
        permissions_dict = dict.fromkeys(self._config['permissions'], True)
        chiaki_permissions = discord.Permissions.none()
        chiaki_permissions.update(**permissions_dict)
        return chiaki_permissions

    @discord.utils.cached_property
    def oauth_url(self):
        return discord.utils.oauth_url(self.user.id, self.permissions)
    invite_url = oauth_url

    @property
    def default_prefix(self):
        return always_iterable(self._config['default_command_prefix'])

    @property
    def default_help(self):
        return self._config['default_help']

    @property
    def official_guild(self):
        id = self._config.get('official_guild') or self._config['official_server']
        return self.get_guild(id)
    official_server = official_guild

    @property
    def official_guild_invite(self):
        return self._config.get('official_server_invite') or random.choice(self.invites_by_bot)
    official_server_invite = official_guild_invite

    # ------ misc. properties ------

    @property
    def uptime(self):
        return datetime.utcnow() - self.start_time

    @property
    def str_uptime(self):
        return duration_units(self.uptime.total_seconds())

    @property
    def all_cogs(self):
        return collections.ChainMap(self.cogs, self.cog_aliases)

def _command_prefix(bot, message):
    prefixes = bot.custom_prefixes.get(message.guild, bot.default_prefix)
    return commands.when_mentioned_or(*prefixes)(bot, message)

# main bot
def chiaki_bot(config):
    """Factory function to create the bot"""
    return ChiakiBot(command_prefix=_command_prefix,
                     formatter=ChiakiFormatter(width=MAX_FORMATTER_WIDTH, show_check_failure=True),
                     description=config.pop('description'), pm_help=None,
                     command_not_found="I don't have a command called {}, I think.",
                     config=config
                    )
