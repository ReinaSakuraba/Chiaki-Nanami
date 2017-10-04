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
from cogs.utils.paginator import BaseReactionPaginator, DelimPaginator, ListPaginator, page

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


async def _can_run(command, ctx):
    try:
        return await command.can_run(ctx)
    except commands.CommandError:
        return False


async def _command_formatters(commands, ctx):
    for command in commands:
        fmt = '`{}`' if await _can_run(command, ctx) else '~~`{}`~~'
        yield map(fmt.format, command.all_names)


_note = (
    "You can't commands that have\n"
    "been crossed out (~~`like this`~~)"
)


class CogPages(ListPaginator):
    numbered = None

    # Don't feel like doing an async def __init__ and hacking through that.
    # We have to make this async because we need to make the entries in one go.
    # As we have to check if the commands can be run, which entails querying the
    # DB too.
    @classmethod
    async def create(cls, ctx, cog):
        cog_name = cog.__class__.__name__
        entries = (c for c in ctx.bot.get_cog_commands(cog_name)
                   if not (c.hidden or ctx.bot.formatter.show_hidden))

        formats = _command_formatters(sorted(entries, key=str), ctx)
        lines = [' | '.join(line) async for line in formats]

        self = cls(ctx, lines, colour=ctx.bot.colour)
        self._cog_doc = inspect.getdoc(cog) or 'No description... yet.'
        self._cog_name = cog_name

        return self

    def _create_embed(self, idx, entries):
        return (discord.Embed(colour=self.colour, description=self._cog_doc)
                .set_author(name=self._cog_name)
                .add_field(name='Commands', value='\n'.join(entries))
                .add_field(name='Note', value=_note, inline=False)
                .set_footer(text=f'Currently on page {idx + 1}')
                )


class ChiakiFormatter(commands.HelpFormatter):
    def get_ending_note(self):
        return f"Type {self.clean_prefix}help command for more info on a command."

    async def bot_help(self):
        bot, func = self.context.bot, self.apply_function
        result = _default_help.format(bot, bot=bot)
        return func(result)

    async def format_help_for(self, ctx, command, func=lambda s: s):
        self.apply_function = func
        return await super().format_help_for(ctx, command)

    async def format(self):
        if self.is_bot():
            return await self.bot_help()
        elif self.is_cog():
            return await CogPages.create(self.context, self.command)
        return HelpCommandPage(self.context, self.command, self.apply_function)
