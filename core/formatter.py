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
from cogs.utils.paginator import BaseReactionPaginator, DelimPaginator, page

def _unique(iterable):
    return list(OrderedDict.fromkeys(iterable))


# placeholder for later
_default_help = """
*{0.description}*

To invite me to your server, use `->invite`, or just use this link:
<{0.invite_url}>

If you need help with something, or there's some weird issue with me, which will usually happen
(since the owners don't tend to test me a lot), use this link to join the **Official** Chiaki Nanami Server:
{0.support_invite}

*Use `->modules` for all the modules with commands.
Or `->commands "module"` for a list of commands for a particular module.*
"""


def _clean_prefix(ctx):
    # XXX: Function for getting the clean prefix until I use the actual Context method.
    user = ctx.bot.user
    return ctx.prefix.replace(user.mention, f'@{user.name}')


def _make_command_requirements(command):
    requirements = []
    # All commands in this cog are owner-only anyway.
    if command.cog_name == 'Owner':
        requirements.append('**Bot Owner only**')

    def make_pretty(p):
        return p.replace('_', ' ').title().replace('Guild', 'Server')

    for check in command.checks:
        name = getattr(check, '__qualname__', '')

        if name.startswith('is_owner'):
            # the bot owner line must come above every other line, for emphasis.
            requirements.insert(0, '**Bot Owner only**')
        elif name.startswith('has_permissions'):
            permissions = inspect.getclosurevars(check).nonlocals['perms']
            pretty_perms = [make_pretty(k) if v else f'~~{make_pretty(k)}~~'
                            for k, v in permissions.items()]

            perm_names = ', '.join(pretty_perms)
            requirements.append(f'{perm_names} permission{"s" * (len(pretty_perms) != 1)}')
        print(requirements)

        return '\n'.join(requirements)


class HelpCommandPage(BaseReactionPaginator):
    def __init__(self, ctx, command, func=None):
        super().__init__(ctx)
        self.command = command
        self.func = func
        self._toggle = True

    @page('\N{INFORMATION SOURCE}')
    def default(self):
        self._toggle = toggle = not self._toggle
        meth = self._example if toggle else self._command_info
        return meth()

    def _command_info(self):
        command, ctx, func = self.command, self.context, self.func
        bot = ctx.bot
        clean_prefix = _clean_prefix(ctx)
        # usages = self.command_usage

        # if usage is truthy, it will immediately return with that usage. We don't want that.
        with temp_attr(command, 'usage', None):
            signature = command.signature

        requirements = _make_command_requirements(command) or 'None'
        cmd_name = f"`{clean_prefix}{command.full_parent_name} {' / '.join(command.all_names)}`"

        description = command.help.format(prefix=clean_prefix)
        cmd_embed = discord.Embed(title=func(cmd_name), description=func(description), colour=bot.colour)

        if isinstance(command, commands.GroupMixin):
            command_names = sorted(cmd.name for cmd in command.commands)
            children = ', '.join(command_names) or "No commands... yet."
            cmd_embed.add_field(name=func("Child Commands"), value=func(children), inline=False)

        cmd_embed.add_field(name=func("Requirements"), value=func(requirements))
        cmd_embed.add_field(name=func("Structure"), value=f'`{func(signature)}`', inline=False)

        # if usages is not None:
        #    cmd_embed.add_field(name=func("Usage"), value=func(usages), inline=False)
        footer = f'Module: {command.cog_name} | Click the info button below to see an example.'
        return cmd_embed.set_footer(text=func(footer))

    def _example(self):
        command, bot = self.command, self.context.bot

        embed = discord.Embed(colour=bot.colour).set_author(name=f'Example for {command}')

        try:
            image_url = bot.command_image_urls[self.command.qualified_name]
        except (KeyError, AttributeError):
            error = f"`{self.command}` doesn't have an image.\nContact MIkusaba#4553 to fix that!"
            embed.add_field(name='\u200b', value=error)
        else:
            embed.set_image(url=image_url)

        return embed.set_footer(text='Click the info button to go back.')


class ChiakiFormatter(commands.HelpFormatter):
    def get_ending_note(self):
        return f"Type {self.clean_prefix}help command for more info on a command."

    @property
    def description(self):
        description = (self.command.help if not self.is_cog() else inspect.getdoc(self.command)) or 'No description'
        return description.format(prefix=self.clean_prefix)

    def paginate_cog_commands(self, cog_name):
        visible = (c for c in self.context.bot.get_cog_commands(cog_name)
                   if not (c.hidden or self.show_hidden))
        sorted_commands = sorted(visible, key=str)
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

    async def format_help_for(self, ctx, command, func=lambda s: s):
        self.apply_function = func
        return await super().format_help_for(ctx, command)

    async def format(self):
        if self.is_bot():
            return await self.bot_help()
        elif self.is_cog():
            return await self.cog_embed()
        return HelpCommandPage(self.context, self.command, self.apply_function)
