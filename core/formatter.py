import discord
import functools
import inspect
import operator
import random

from collections import OrderedDict
from collections.abc import Sequence
from discord.ext import commands
from itertools import chain
from more_itertools import always_iterable

from cogs.utils.context_managers import temp_attr
from cogs.utils.misc import truncate
from cogs.utils.paginator import DelimPaginator

def _unique(iterable):
    return list(OrderedDict.fromkeys(iterable))


# placeholder for later
_default_help = """
*{0.description}*

To invite me to your server, use `->invite`, or just use this link:
<{0.invite_url}>

If you need help with something, or there's some weird issue with me, which will usually happen
(since the owners don't tend to test me a lot), use this link to join the **Official** Chiaki Nanami Server:
https://{0.support_invite}

*Use `->modules` for all the modules with commands.
Or `->commands "module"` for a list of commands for a particular module.*
"""


class ChiakiFormatter(commands.HelpFormatter):
    def get_ending_note(self):
        return f"Type {self.clean_prefix}help command for more info on a command."

    @property
    def description(self):
        description = (self.command.help if not self.is_cog() else inspect.getdoc(self.command)) or 'No description'
        return description.format(prefix=self.clean_prefix)

    @property
    def command_usage(self):
        cmd = self.command
        prefix = self.clean_prefix
        qualified_names = [f"{cmd.full_parent_name} {name}" for name in cmd.all_names]
        if cmd.clean_params:
            usage = cmd.usage
            if isinstance(usage, Sequence):
                return '\n'.join([f'`{prefix}{random.choice(qualified_names)} {u}`' 
                                  for u in always_iterable(usage)])
            # Assume it's invalid; usage must be a sequence (either a tuple, list, or str)
            return 'No example... yet'
        # commands that don't take any arguments don't really need an example generated manually...
        return None

    @property
    def command_checks(self):
        # TODO: Factor in the group stuff later
        return self.command.checks

    @property
    def command_requirements(self):
        command = self.command
        requirements = []
        # All commands in this cog are owner-only anyway.
        if command.cog_name == 'Owner':
            requirements.append('**Bot Owner only**')

        def make_pretty(p):
            return p.replace('_', ' ').title()

        for check in self.command_checks:
            name = getattr(check, '__qualname__', '')

            if name.startswith('is_owner'):
                # the bot owner line must come above every other line, for emphasis.
                requirements.insert(0, '**Bot Owner only**')
            elif name.startswith('has_permissions'): 
                # Here's the biggest hack in history.
                permissions = check.__closure__[0].cell_contents
                pretty_perms = [make_pretty(k) if v else f'~~{make_pretty(k)}~~' 
                                for k, v in permissions.items()]

                perm_names = ', '.join(pretty_perms)
                requirements.append(f'{perm_names} permission{"s" * (len(pretty_perms) != 1)}')
            print(requirements)

        return '\n'.join(requirements)

    def paginate_cog_commands(self, cog_name):
        sorted_commands = sorted(self.context.bot.get_cog_commands(cog_name), key=str)
        formatted_names =  (map('`{}`'.format, cmd.all_names) for cmd in sorted_commands)
        formatted_lines = map(' | '.join, formatted_names)
        headers = (self.description, '', '**List of commands:**')

        return DelimPaginator.from_iterable(chain(headers, formatted_lines), 
                                            prefix='', suffix='', max_size=2048)

    async def bot_help(self):
        bot, func = self.context.bot, self.apply_function
        result = _default_help.format(bot, bot=bot)
        return func(result)

    async def cog_embed(self):
        ctx, cog = self.context, self.command
        cog_name = type(cog).__name__
        paginated_commands = self.paginate_cog_commands(cog_name)

        embed = functools.partial(discord.Embed, colour=ctx.bot.colour)
        embeds = [embed(description=page) for page in paginated_commands.pages]

        embeds[0].title = f'{cog_name} ({self.clean_prefix})'
        embeds[-1].set_footer(text=self.get_ending_note())
        return embeds

    async def command_embed(self):
        command, ctx, func = self.command, self.context, self.apply_function
        bot = ctx.bot
        usages = self.command_usage

        # if usage is truthy, it will immediately return with that usage. We don't want that.
        with temp_attr(command, 'usage', None):
            signature = command.signature

        requirements = self.command_requirements or 'None'
        cmd_name = f"`{self.clean_prefix}{command.full_parent_name} {' / '.join(command.all_names)}`"
        footer = '"{0}" is in the module *{0.cog_name}*'.format(command)

        cmd_embed = discord.Embed(title=func(cmd_name), description=func(self.description), colour=bot.colour)

        if self.has_subcommands():
            command_names = sorted(cmd.name for cmd in command.commands)
            children = ', '.join(command_names) or "No commands... yet."
            cmd_embed.add_field(name=func("Child Commands"), value=func(children), inline=False)

        cmd_embed.add_field(name=func("Requirements"), value=func(requirements))
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
