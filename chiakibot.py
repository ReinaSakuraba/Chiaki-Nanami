import asyncio
import collections
import contextlib
import discord
import functools
import inspect
import logging
import operator
import random
import re
import time

from collections.abc import Sequence
from datetime import datetime
from discord.ext import commands
from itertools import product, takewhile

from cogs.utils.checks import ChiakiCheck
from cogs.utils.compat import always_iterable
from cogs.utils.context_managers import temp_attr
from cogs.utils.database import Database
from cogs.utils.misc import cycle_shuffle, duration_units, file_handler, truncate

log = logging.getLogger(__name__)
log.addHandler(file_handler('chiakinanami'))

default_bot_help = """\
*{0.description}*

To invite me to your server, use `->invite`, or just use this link:
<{0.invite_url}>

*Use `->modules` for all the modules with commands.
Or `->commands "module"` for a list of commands for a particular module.*
"""

_default_config = {
    'colour': "0xFFDDDD",

    'default_command_prefix': '->',
    'default_help': default_bot_help,

    'restart_code': 69,
    'log': False,
}
del default_bot_help

MAX_FORMATTER_WIDTH = 90
# small hacks to make command display all their possible names
commands.Command.all_names = property(lambda self: [self.name, *self.aliases])

def _all_qualified_names(command):
    parent = command.full_parent_name
    parent_name = f'{parent} ' * bool(parent)
    return [f'{parent}{name}' for name in command.all_names]

class ChiakiFormatter(commands.HelpFormatter):
    def get_ending_note(self):
        return f"Type {self.clean_prefix}help command for more info on a command."

    @property
    def description(self):
        description = (self.command.help if not self.is_cog() else inspect.getdoc(self.command)) or 'No description'
        return description.format(prefix=self.context.prefix)

    @property
    def command_usage(self):
        cmd = self.command
        prefix = self.context.prefix
        qualified_names = _all_qualified_names(cmd)
        if cmd.clean_params:
            usage = cmd.usage
            if isinstance(usage, Sequence):
                return '\n'.join([f'`{prefix}{random.choice(qualified_names)} {u}`' for u in always_iterable(usage)])
            # Assume it's invalid; usage must be a sequence (either a tuple, list, or str)
            return 'No example... yet'
        # commands that don't take any arguments don't really need an example generated manually....
        return None

    def command_requirements(self):
        chiaki_checks = [check for check in self.command.checks if isinstance(check, ChiakiCheck)]
        return {key: ', '.join(filter(None, map(operator.attrgetter(key), chiaki_checks))) or 'None' 
                for key in ['roles', 'perms'] }

    def paginate_cog_commands(self, cog_name):
        paginator = commands.Paginator(prefix='', suffix='', max_size=2048)
        paginator.add_line(self.description, empty=True)
        paginator.add_line('**List of commands:**')

        for command in sorted(self.context.bot.get_cog_commands(cog_name), key=operator.attrgetter('name')):
            name, aliases = command.name, ', '.join(command.aliases)
            paginator.add_line(f'`{name}` {f"| `{aliases}`" * bool(aliases)}')

        return paginator

    async def bot_help(self):
        bot, func = self.context.bot, self.apply_function
        default_help = bot.default_help
        result = default_help.format(bot, bot=bot)
        return func(result)

    async def cog_embed(self):
        ctx = self.context
        bot, cog = ctx.bot, self.command
        cog_name = type(cog).__name__
        paginated_commands = self.paginate_cog_commands(cog_name)

        embeds = []
        for i, page in enumerate(paginated_commands.pages):
            module_embed = discord.Embed(description=page, colour=bot.colour)
            if i == 0:
                module_embed.title = f"{cog_name} ({ctx.prefix})"
            embeds.append(module_embed)

        embeds[-1].set_footer(text=self.get_ending_note())
        return embeds

    async def command_embed(self):
        command, ctx, func = self.command, self.context, self.apply_function
        bot = ctx.bot
        usages = self.command_usage

        # if usage is truthy, it will immediately return with that usage. We don't want that.
        with temp_attr(command, 'usage', None):
            signature = command.signature

        requirements = self.command_requirements()
        cmd_name = f"`{ctx.prefix}{command.full_parent_name} {' / '.join(command.all_names)}`"
        footer = '"{0}" is in the module *{0.cog_name}*'.format(command)

        cmd_embed = discord.Embed(title=func(cmd_name), description=func(self.description), colour=bot.colour)

        if self.has_subcommands():
            command_names = sorted(cmd.name for cmd in command.commands)
            children = ', '.join(command_names) or "No commands... yet."
            cmd_embed.add_field(name=func("Child Commands"), value=func(children), inline=False)

        cmd_embed.add_field(name=func("Required Roles"), value=func(requirements['roles']))
        cmd_embed.add_field(name=func("Required Permissions"), value=func(requirements['perms']))
        cmd_embed.add_field(name=func("Structure"), value=f'`{func(signature)}`', inline=False)

        if usages is not None:
            cmd_embed.add_field(name=func("Usage"), value=func(usages), inline=False)
        return cmd_embed.set_footer(text=func(footer))

    async def format_help_for(self, ctx, command, func=lambda s: s):
        self.apply_function = func
        return await super().format_help_for(ctx, command)

    async def format(self):
        if self.is_bot():
            return await self.bot_help()
        elif self.is_cog():
            return await self.cog_embed()
        return await self.command_embed()

class ChiakiBot(commands.Bot):
    def __init__(self, command_prefix, formatter=None, description=None, pm_help=False, **options):
        super().__init__(command_prefix, formatter, description, pm_help, **options)
        self.remove_command('help')

        self._config = collections.ChainMap(options.get('config', {}), _default_config)
        self.counter = collections.Counter()
        self.persistent_counter = Database('stats.json')
        self.custom_prefixes = Database('customprefixes.json')
        self.databases = [self.persistent_counter, self.custom_prefixes, ]
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
        self.counter.update(self.persistent_counter)
        self.persistent_counter.update(self.counter)
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

    def add_database(self, db):
        self.databases.append(db)
        log.info(f"database {db.name} successfully added")

    def remove_database(self, db):
        if db in self.databases:
            self.loop.create_task(db.dump())
            self.databases.remove(db)
        log.info(f"database {db.name} successfully removed")

    async def dump_databases(self):
        for db in self.databases:
            await db.dump()

    # Just some looping functions
    async def change_game(self):
        game_choices = cycle_shuffle(self._config['rotating_games'])
        await self.wait_until_ready()
        while not self.is_closed():
            name = next(game_choices)
            await self.change_presence(game=discord.Game(name=name))
            await asyncio.sleep(random.uniform(0.5, 10) * 60)

    async def update_official_invite(self):
        await self.wait_until_ready()
        self.invites_by_bot = [inv for inv in await self.official_guild.invites() if inv.inviter.id == self.user.id]
        if not self.invites_by_bot:
            self.invites_by_bot.append(await official_guild.create_invite())

    async def ping(self, times=1):
        # I prefer using time.perf_counter()
        # Some people use time.monotonic(), 
        # but time.perf_counter() is literally made for timing things.
        start = time.perf_counter()
        await (await self.ws.ping())
        end = time.perf_counter()
        return (end - start) * 1000

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
        return random.choice(self.invites_by_bot)
    official_server_invite = official_guild_invite

    # ------ misc. properties ------

    @discord.utils.cached_property
    def prefix_function(self):
        return functools.partial(self.command_prefix, self)

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
    return bot.custom_prefixes.get(message.guild, bot.default_prefix)

# main bot
def chiaki_bot(config):
    return ChiakiBot(command_prefix=_command_prefix,
                     formatter=ChiakiFormatter(width=MAX_FORMATTER_WIDTH, show_check_failure=True),
                     description=config.pop('description'), pm_help=None,
                     command_not_found="I don't have a command called {}, I think.",
                     config=config
                    )
