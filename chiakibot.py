import asyncio
import collections
import contextlib
import discord
import inspect
import logging
import random
import re

from collections.abc import Sequence
from datetime import datetime
from discord.ext import commands

from cogs.utils.context_managers import temp_attr
from cogs.utils.database import Database
from cogs.utils.misc import cycle_shuffle, duration_units, truncate

log = logging.getLogger(__name__)
try:
    handler = logging.FileHandler(filename='./logs/chiakinanami.log', encoding='utf-8', mode='w')
except FileNotFoundError:
    os.makedirs("logs", exist_ok=True)
    handler = logging.FileHandler(filename='./logs/chiakinanami.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s/%(levelname)s:%(name)s: %(message)s'))
log.addHandler(handler)

default_bot_help = """\
*{0.description}*

To invite me to your server, use `->invite`, or just use this link:
{0.invite_url}

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
# small hack to make command display all their possible names
commands.Command.all_names = property(lambda self: [self.name, *self.aliases])

def _all_qualified_names(self):
    parent = self.full_parent_name
    fmt = '{parent} ' * bool(parent) + '{}'
    return list(map(fmt.format, self.all_names))
commands.Command.all_qualified_names = property(_all_qualified_names)
del _all_qualified_names

class ChiakiFormatter(commands.HelpFormatter):
    def get_ending_note(self):
        command_name = self.context.invoked_with
        return f"Type {self.clean_prefix}help command for more info on a command."

    async def unique_cog_commands(self):
        return [(name, cmd.aliases) for name, cmd in await self.filter_command_list() if name not in cmd.aliases]

    async def command_usage(self, prefix=None):
        cmd, ctx = self.command, self.context
        if prefix is None:
            prefix = await ctx.bot.get_prefix(ctx.message)

        if cmd.clean_params:
            usage = cmd.usage
            if isinstance(usage, Sequence):
                return (f'`{prefix}{random.choice(cmd.all_qualified_names)} {usage}`' if isinstance(usage, str)
                        else '\n'.join([f'`{prefix}{random.choice(cmd.all_qualified_names)} {u}`' for u in usage]))
            # Assume it's invalid; usage must be a sequence (either a tuple, list, or str)
            return 'No example... yet'
        # commands that don't take any arguments don't really need an example generated manually....
        return None

    @property
    def clean_prefix(self):
        ctx = self.context
        return (super().clean_prefix if self.is_bot() or self.is_cog() else
                ctx.bot.str_prefix(self.command, ctx.guild)

    async def bot_help(self):
        bot, func = self.context.bot, self.apply_function
        default_help = bot._config['default_help']
        result = default_help.format(bot, bot=bot))
        return func(result)

    async def cog_embed(self):
        (cog_name, cog), ctx = self.command, self.context
        bot = ctx.bot
        prefix = bot.str_prefix(cog, ctx.guild)
        description = cog.__doc__ or 'No description... yet.'

        with temp_attr(self, 'command', cog):
            commands = await self.unique_cog_commands()

        if not commands:
            raise commands.BadArgument(f"Module {cog_name} has no visible commands.")

        module_embed = discord.Embed(title=f"List of my commands in {cog_name} (Prefix: {prefix})",
                                     description=description, colour=bot.colour)
        for name, aliases in sorted(commands):
            trunc_alias = truncate(', '.join(aliases) or '\u200b', 30, '...')
            module_embed.add_field(name=prefix + name, value=trunc_alias)
        return module_embed.set_footer(text=ctx.bot.formatter.get_ending_note())

    async def command_embed(self):
        command, ctx, func = self.command, self.context, self.apply_function
        bot = ctx.bot
        prefix = bot.str_prefix(command, ctx.guild)
        usages = await self.command_usage(prefix)

        with temp_attr(command, 'usage', None):
            signature = self.get_command_signature()

        requirements = getattr(command.callback, '__requirements__', {})
        required_roles = ', '.join(requirements.get('roles', [])) or 'None'
        required_perms = ', '.join(requirements.get('perms', [])) or 'None'
        cmd_name = f"`{prefix}{command.full_parent_name} {' / '.join(command.all_names)}`"
        footer = '"{0}" is in the module *{0.cog_name}*'.format(command)

        cmd_embed = discord.Embed(title=func(cmd_name), description=func(command.help or 'No description'), colour=bot.colour)

        if self.has_subcommands():
            command_name = sorted({cmd.name for cmd in command.commands.values()})
            children = ', '.join(command_name) or "No commands... yet."
            cmd_embed.add_field(name=func("Child Commands"), value=func(children), inline=False)

        cmd_embed.add_field(name=func("Required Roles"), value=func(required_roles))
        cmd_embed.add_field(name=func("Required Permissions"), value=func(required_perms))
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
        self.commands.pop('help', None)

        self.counter = collections.Counter()
        self.persistent_counter = Database.from_json('stats.json')
        self.custom_prefixes = Database.from_json('customprefixes.json', default_factory=dict)
        self.databases = [self.persistent_counter, self.custom_prefixes, ]
        self.cog_aliases = {}
        self._config = collections.ChainMap(options.get('config', {}), _default_config)

        self.reset_requested = False
        if self._config['restart_code'] == 0:
            raise RuntimeError("restart_code cannot be zero")

    async def logout(self):
        self.counter.update(self.persistent_counter)
        self.persistent_counter.update(self.counter)
        await super().logout()

    def add_cog(self, cog, *aliases, hidden=False):
        if hasattr(cog, '__hidden__'):
            raise discord.ClientException("__hidden__ attribute can't be defined")

        members = inspect.getmembers(cog)
        for name, member in members:
            # add any databases
            if isinstance(member, Database):
                self.add_database(member)

        # cog aliases
        cog_name = type(cog).__name__
        for alias in aliases:
            if alias in self.cog_aliases:
                raise discord.ClientException(f'"{alias}" already has a cog registered')
            self.cog_aliases[alias] = cog_name

        # add to namespace
        cog.__hidden__ = hidden
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
        self.cog_aliases = {alias: real for alias, real in self.cog_aliases.items() if real != cog_name}

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

    async def dump_db_cycle(self):
        while not self.is_closed():
            await asyncio.sleep(60)
            await self.dump_databases()
            print('all databases successfully dumped')

    async def update_official_invite(self):
        await self.wait_until_ready()
        while not self.is_closed():
            self.invites_by_bot = [inv for inv in await self.official_guild.invites() if inv.inviter == self.user]
            if not self.invites_by_bot:
                self.invites_by_bot.append(await official_guild.create_invite())

    # unfortunately we can't use get_prefix as it's a coroutine
    # so we have to do it the suboptimal way...
    def cog_prefix(self, cmd, guild):
        cog = cmd.instance if isinstance(cmd, commands.Command) else cmd
        cog_name = type(cog).__name__ if cog else None
        cog_references = self.custom_prefixes.get(guild)
        default_prefix = lambda cog: getattr(cog, '__prefix__', None) or self.default_prefix
        if cog_references:
            if cog_references.get("use_default"):
                return cog_references.get("default", default_prefix(cog))
            return cog_references.get(cog_name, default_prefix(cog))
        return default_prefix(cog)

    def str_prefix(self, cmd, guild):
        prefix = self.cog_prefix(cmd, guild)
        return prefix if isinstance(prefix, str) else ', '.join(prefix)

    # ------ Config-related properties ------

    @discord.utils.cached_property
    def colour(self):
        colour_converter = commands.ColourConverter()
        colour_converter.prepare(None, self._config['colour'])
        return colour_converter.convert()

    @discord.utils.cached_property
    def permissions(self):
        permissions_dict = self._config['permissions']
        chiaki_permissions = discord.Permissions.none()
        chiaki_permissions.update(**permissions_dict)
        return chiaki_permissions

    @discord.utils.cached_property
    def oauth_url(self):
        return discord.utils.oauth_url(self.user.id, self.permissions)

    @property
    def default_prefix(self):
        return self._config['default_command_prefix']

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

    @property
    def uptime(self):
        return datetime.utcnow() - self.start_time

    @property
    def str_uptime(self):
        return duration_units(self.uptime.total_seconds())

def _find_prefix_by_cog(bot, message):
    custom_prefixes = bot.custom_prefixes.get(message.guild, {})
    default_prefix = custom_prefixes.get("default", bot.default_prefix)

    if not message.content:
        return default_prefix

    if custom_prefixes.get("use_default_prefix", False):
        return default_prefix

    first_word = message.content.split()[0]
    try:
        maybe_cmd = re.search(r'(\w+)$', first_word).group(1)
    except AttributeError:
        return default_prefix

    cmd = bot.get_command(maybe_cmd)
    if cmd is None:
        return default_prefix

    return bot.cog_prefix(cmd, message.guild)

# main bot
def chiaki_bot(config):
    return ChiakiBot(command_prefix=_find_prefix_by_cog,
                     formatter=ChiakiFormatter(width=MAX_FORMATTER_WIDTH, show_check_failure=True),
                     description=config.pop('description'), pm_help=None,
                     command_not_found="I don't have a command called {}, I think.",
                     config=config
                    )
