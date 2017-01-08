import asyncio
import discord
import inspect
import itertools
import random
import re

from discord.ext import commands

from cogs.utils.misc import cycle_shuffle

DEFAULT_CMD_PREFIX = '->'

def cog_prefix(cmd):
    cog = cmd.instance
    return (DEFAULT_CMD_PREFIX if cog is None
            else getattr(type(cog), '__prefix__', DEFAULT_CMD_PREFIX))
            
def str_prefix(cmd):
    prefix = cog_prefix(cmd)
    return prefix if isinstance(prefix, str) else '|'.join(prefix)
            
class ChiakiFormatter(commands.HelpFormatter):
    def _add_subcommands_to_page(self, max_width, commands):
        commands = ((str_prefix(cmd) + name, cmd) for name, cmd in commands 
                    if name not in cmd.aliases)
        super()._add_subcommands_to_page(max_width, commands)
        
    @property
    def true_prefix(self):
        return str_prefix(self.command)
                
    # There is only one line that is changed here...
    # But that line actually affects how the thing is shown in help
    def get_command_signature(self):
        """Retrieves the signature portion of the help page."""
        result = []
        # This is the different line
        # The original was: prefix = self.clean_prefix
        # But since I'm allowing for module
        prefix = self.true_prefix   
        cmd = self.command
        parent = cmd.full_parent_name
        # Another line that was changed, just solely for readibility
        if cmd.aliases:
            aliases = '|'.join(cmd.aliases)
            fmt = '{0}[{1.name}|{2}]'
            if parent:
                fmt = '{0}{3} [{1.name}|{2}]'
            result.append(fmt.format(prefix, cmd, aliases, parent))
        else:
            name = prefix + cmd.name if not parent else prefix + parent + ' ' + cmd.name
            result.append(name)

        params = cmd.clean_params
        if len(params) > 0:
            for name, param in params.items():
                if param.default is not param.empty:
                    # We don't want None or '' to trigger the [name=value] case and instead it should
                    # do [name] since [name=None] or [name=] are not exactly useful for the user.
                    should_print = param.default if isinstance(param.default, str) else param.default is not None
                    if should_print:
                        result.append(f'[{name}={param.default}]')
                    else:
                        result.append(f'[{name}]')
                elif param.kind == param.VAR_POSITIONAL:
                    result.append(f'[{name}...]')
                else:
                    result.append(f'<{name}>')

        return ' '.join(result)      
        
    def format(self):
        """Handles the actual behaviour involved with formatting.
        To change the behaviour, this method should be overridden.
        Returns
        --------
        list
            A paginated output of the help command.
        """
        from discord.ext import commands
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
            prefix = cog_prefix(cmd)
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

def _get_databases(cog):
    return (attr for attr in vars(cog).values() if hasattr(attr, "dump"))
    
class ChiakiBot(commands.Bot):
    def __init__(self, command_prefix, formatter=None, description=None, pm_help=False, **options):
        super().__init__(command_prefix, formatter, description, pm_help, **options)
        self.loop.create_task(self.change_game())
        self.loop.create_task(self.dump_db_cycle())
           
    # literally the only reason why I created a subclass
    def dump_databases(self):
        for cog in self.cogs.values():
            for db in _get_databases(cog):
                db.dump()
                
    async def logout(self):
        self.dump_databases()
        await super().logout()

    def get_member(self, id):
        return discord.utils.get(self.get_all_members(), id=id)
        
    # Just some looping functions
    async def change_game(self):
        await self.wait_until_ready()
        GAME_CHOICES = cycle_shuffle((
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
        ))
        while not self.is_closed:
            name = next(GAME_CHOICES)
            await self.change_presence(game=discord.Game(name=name))
            await asyncio.sleep(random.uniform(0.5, 10) * 60)
    
    async def dump_db_cycle(self):
        await self.wait_until_ready()
        while not self.is_closed:
            self.dump_databases()
            print("all databases successfully dumped")
            await asyncio.sleep(600)
    
def _find_prefix_by_cog(bot, message):
    if not message.content:
        return DEFAULT_CMD_PREFIX
    
    first_word = message.content.split()[0]
    try:
        maybe_cmd = re.search(r'(\w+)', first_word).group(1)
    except AttributeError:
        return DEFAULT_CMD_PREFIX

    cmd = bot.get_command(maybe_cmd)
    if cmd is None:
        return DEFAULT_CMD_PREFIX
    
    return cog_prefix(cmd)

    
 