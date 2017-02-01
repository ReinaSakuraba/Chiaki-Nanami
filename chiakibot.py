import asyncio
import discord
import inspect
import itertools
import logging
import random
import re

from collections import Counter
from datetime import datetime
from discord.ext import commands

from cogs.utils.database import Database
from cogs.utils.misc import cycle_shuffle, full_succinct_duration

log = logging.getLogger(__name__)
try:
    handler = logging.FileHandler(filename='./logs/chiakinanami.log', encoding='utf-8', mode='w')
except FileNotFoundError:
    os.makedirs("logs", exist_ok=True)
    handler = logging.FileHandler(filename='./logs/chiakinanami.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s/%(levelname)s:%(name)s: %(message)s'))
log.addHandler(handler)

# You are free to change this if you want.
DEFAULT_CMD_PREFIX = '->'
description = '''A test for the Chiaki bot (totally not a ripoff of Nadeko)'''
MAX_FORMATTER_WIDTH = 90

def cog_prefix(cmd, bot, server):
    cog = cmd.instance
    cog_references = bot.custom_prefixes.get(server)
    default_prefix = lambda cog: (DEFAULT_CMD_PREFIX if cog is None else
                                  getattr(cog, '__prefix__', DEFAULT_CMD_PREFIX))
    if cog_references:
        if cog_references.get("use_default"):
            return cog_references.get("default", default_prefix(cog))
        return cog_references.get(type(cog).__name__, default_prefix(cog))
    return default_prefix(cog)

def str_prefix(cmd, bot, server):
    prefix = cog_prefix(cmd)
    return prefix if isinstance(prefix, str) else '|'.join(prefix)

class ChiakiFormatter(commands.HelpFormatter):
    def _add_subcommands_to_page(self, max_width, commands):
        commands = ((str_prefix(cmd) + name, cmd) for name, cmd in commands
                    if name not in cmd.aliases)
        super()._add_subcommands_to_page(max_width, commands)

    @property
    def clean_prefix(self):
        ctx = self.context
        return (super().clean_prefix if self.is_bot() or self.is_cog() else
                str_prefix(self.command, ctx.bot, ctx.message.server))

    def format(self):
        """Handles the actual behaviour involved with formatting.
        To change the behaviour, this method should be overridden.
        Returns
        --------
        list
            A paginated output of the help command.
        """
        from discord.ext import commands
        bot, server = self.context.bot, self.context.message.server
        self._paginator = commands.Paginator()
        # we need a padding of ~80 or so

        description = self.command.description if not self.is_cog() else inspect.getdoc(self.command)
        if description:
            # <description> portion
            self._paginator.add_line(description, empty=True)

        if isinstance(self.command, commands.Command):
            # <signature portion>
            signature = self.get_command_signature()
            self._paginator.add_line(signature, empty=True)

            # <long doc> section
            if self.command.help:
                self._paginator.add_line(self.command.help, empty=True)

            # end it here if it's just a regular command
            if not self.has_subcommands():
                self._paginator.close_page()
                return self._paginator.pages

        max_width = self.max_name_size

        def category(tup):
            cmd = tup[1]
            prefix = cog_prefix(cmd, bot, server)
            # we insert the zero width space there to give it approximate
            # last place sorting position.
            return f'{cmd.cog_name} (Prefix: {prefix})' if cmd.cog_name is not None else '\u200bNo Category:'

        if self.is_bot():
            data = sorted(self.filter_command_list(), key=category)
            for category, commands in itertools.groupby(data, key=category):
                # there simply is no prettier way of doing this.
                commands = list(commands)
                if len(commands) > 0:
                    self._paginator.add_line(category)

                self._add_subcommands_to_page(max_width, commands)
        else:
            prefix = getattr(type(self.command), '__prefix__', DEFAULT_CMD_PREFIX)
            self._paginator.add_line('Commands:')
            self._add_subcommands_to_page(max_width, self.filter_command_list())

        # add the ending note
        self._paginator.add_line()
        ending_note = self.get_ending_note()
        self._paginator.add_line(ending_note)
        return self._paginator.pages

class ChiakiBot(commands.Bot):
    def __init__(self, command_prefix, formatter=None, description=None, pm_help=False, **options):
        super().__init__(command_prefix, formatter, description, pm_help, **options)

        self.loop.create_task(self.change_game())
        self.loop.create_task(self.dump_db_cycle())
        self.loop.create_task(self._start_time())

        self.commands_counter = Counter()
        self.persistent_counter = Database.from_json("stats.json")
        self.custom_prefixes = Database.from_json("customprefixes.json", default_factory=dict)
        self.databases = [self.persistent_counter, self.custom_prefixes, ]
        self.unloads = []

    async def _start_time(self):
        await self.wait_until_ready()
        self.start_time = datetime.now()

    async def logout(self):
        self.commands_counter.update(self.persistent_counter)
        self.persistent_counter.update(self.commands_counter)
        await self.dump_databases()
        await super().logout()

    def run(self, *args, **kwargs):
        try:
            self.loop.run_until_complete(self.start(*args, **kwargs))
        except KeyboardInterrupt:
            self.loop.run_until_complete(self.logout())
            pending = asyncio.Task.all_tasks(loop=self.loop)
            gathered = asyncio.gather(*pending, loop=self.loop)
            # Do not cancel the tasks. It will interfere with database dumping
            self.loop.run_until_complete(gathered)
        finally:
            print('loop closed...')
            self.loop.close()

    def add_cog(self, cog):
        members = inspect.getmembers(cog)
        for name, member in members:
            # add any databases
            if isinstance(member, Database):
                self.add_database(member)
        super().add_cog(cog)

    def remove_cog(self, name):
        cog = self.cogs.get(name, None)
        if cog is None:
            return
        members = inspect.getmembers(cog)
        for name, member in members:
            # remove any databases
            if isinstance(member, Database):
                self.remove_database(member)
        super().remove_cog(name)

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
        if db not in self.databases:
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
        await self.wait_until_ready()
        GAME_CHOICES = cycle_shuffle([
        'Gala Omega',
        'Dangan Ronpa: Trigger Happy Havoc',
        'Super Dangan Ronpa 2',
        'NDRV3',
        'with Hajime Hinata',
        'with hope',
        'hope',
        'without despair',
        'with Nadeko',
        'with Usami',

        # Useful stuff
        '->help',
        '->invite',
        ])
        while not self.is_closed:
            name = next(GAME_CHOICES)
            await self.change_presence(game=discord.Game(name=name))
            await asyncio.sleep(random.uniform(0.5, 10) * 60)

    async def dump_db_cycle(self):
        await self.wait_until_ready()
        while not self.is_closed:
            await self.dump_databases()
            print("all databases successfully dumped")
            await asyncio.sleep(600)

    @property
    def uptime(self):
        return datetime.now() - self.start_time

    @property
    def str_uptime(self):
        return full_succinct_duration(self.uptime.total_seconds())

    @property
    def invite_url(self):
        chiaki_permissions = discord.Permissions(2146823295)
        return discord.utils.oauth_url(self.user.id, chiaki_permissions)

    @property
    def default_prefix(self):
        return DEFAULT_CMD_PREFIX

    @property
    def default_prefixes(self):
        return {cog_name: getattr(cog, '__prefix__', DEFAULT_CMD_PREFIX)
                for cog_name, cog in self.cogs.items()}


def _find_prefix_by_cog(bot, message):
    custom_prefixes = bot.custom_prefixes.get(message.server, {})
    default_prefix = custom_prefixes.get("default", DEFAULT_CMD_PREFIX)

    if not message.content:
        return default_prefix

    first_word = message.content.split()[0]
    try:
        maybe_cmd = re.search(r'(\w+)$', first_word).group(1)
    except AttributeError:
        return default_prefix

    cmd = bot.get_command(maybe_cmd)
    if cmd is None:
        return default_prefix

    return cog_prefix(cmd, bot, message.server)

# main bot
def chiaki_bot():
    return ChiakiBot(command_prefix=_find_prefix_by_cog,
                     formatter=ChiakiFormatter(width=MAX_FORMATTER_WIDTH),
                     description=description, pm_help=None
                    )
