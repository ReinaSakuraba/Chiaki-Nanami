"""Converters that provide a "search" functionality

In order to create case-insensitive converters, we need to be able to handle 
conflicts. This becomes especially important when dealing with users, because two
users can have the exact same name, which will confuse and potentially frustrate
people when the wrong user is chosen.
"""

import asyncio
import discord
import re

from discord.ext import commands
from more_itertools import always_iterable

from .context_managers import temp_attr
from .formats import human_join, pluralize
from .misc import REGIONAL_INDICATORS

# Avoid excessive dot-lookup every time a member is attempted to be converted
_get_from_guilds = commands.converter._get_from_guilds


class Search:
    def __init__(self, *, max_choices=10, timeout=120, delete_message=True):
        self.max_choices = max_choices
        self.timeout = timeout
        self.do_delete = delete_message

    @staticmethod
    def _format_choices(emojis, choices):
        return '\n'.join(map('{0} = {1}'.format, emojis, choices))

    async def search(self, ctx, arg, choices, *, thing):
        num_choices = len(choices)
        choices = choices[:self.max_choices]
        emojis = REGIONAL_INDICATORS[:len(choices)]

        description = self._format_choices(emojis, choices)
        pluralized = pluralize(**{thing: num_choices})
        field_value = 'Please click one of the reactions below.'
        embed = (discord.Embed(colour=0x00FF00, description=description)
                .set_author(name=f'{pluralized} have been found for "{arg}"')
                .add_field(name='Instructions', value=field_value)
                )

        async def _put_reactions(message):
            for e in emojis:
                await message.add_reaction(e)

        message = await ctx.send(embed=embed)
        future = asyncio.ensure_future(_put_reactions(message))

        def check(reaction, user):
            return (reaction.message.id == message.id
                    and user.id == ctx.author.id
                    and reaction.emoji in emojis)

        try:
            reaction, user = await ctx.bot.wait_for('reaction_add', timeout=self.timeout, check=check)
            return choices[emojis.index(reaction.emoji)]
        finally:
            if not future.done():
                future.cancel()

            if self.do_delete:
                await message.delete()


class RoleSearch(commands.IDConverter, Search):
    """Converter that allows for case-insensitive discord.Role conversion."""
    async def convert(self, ctx, argument):
        guild = ctx.guild
        if not guild:
            raise commands.NoPrivateMessage()

        # Let ID's and mentions take priority
        match = self._get_id_match(argument) or re.match(r'<@&([0-9]+)>$', argument)
        if match:
            predicate = lambda r, id=int(match.group(1)): r.id == id
        else:
            predicate = lambda r, arg=argument.lower(): r.name.lower() == arg

        results = list(filter(predicate, guild.roles))
        if not results:
            raise commands.BadArgument('Role "{}" not found.'.format(argument))
        if len(results) == 1:
            return results[0]

        return await self.search(ctx, argument, results, thing='role')


class MemberSearch(commands.MemberConverter, Search):
    """Converter that allows for case-insensitive discord.Member conversion."""
    async def convert(self, ctx, argument):
        guild = ctx.guild
        bot = ctx.bot
        match = self._get_id_match(argument) or re.match(r'<@!?([0-9]+)>$', argument)

        # IDs must be unique, we won't allow conflicts here.
        if match is not None:
            return await super().convert(ctx, argument)

        # not a mention or ID...
        if guild:
            # The trailing comma is because the result expects a sequence
            # This will transform result into a tuple, which is important.
            # Because len(discord.Member) will error.
            result = guild.get_member_named(argument),
            # Will only be False if only the name was provided, or a user with 
            # the same nickname as another user's fullname was provided. 
            # (eg if someone nicknames themself "rjt#2336", and rjt#2336 was in 
            # the server)
            if str(result[0]) != argument:
                lowered = argument.lower()
                def predicate(m):
                    # We can't just do lowered in (m.nick.lower(), m.name.lower())
                    # because m.nick can be None
                    return (m.nick and lowered == m.nick.lower()) or lowered == m.name.lower()

                # filter it out from here
                result = list(filter(predicate, guild.members))

        else:
            # We can't use the "fuzzy" match here, due to potential conflicts 
            # and duplicate results.
            result = _get_from_guilds(bot, 'get_member_named', argument), # See comment in "if guild:"

        if not result:
            raise commands.BadArgument(f'Member "{argument}" not found')
        elif len(result) == 1:
            return result[0]
        return await self.search(ctx, argument, result, thing='member')

# A mapping for the discord.py class and it's corresponding searcher.
_type_search_maps = {
    discord.Role: RoleSearch,
    discord.Member: MemberSearch,
}

class union(Search, commands.Converter):
    def __init__(self, *types, **kwargs):
        # Relying on the fact that Search.__init__ doesn't call super().__init__
        super().__init__(**kwargs)
        self.kwargs = kwargs
        self.types = types

    @staticmethod
    def _format_choices(emojis, choices):
        return '\n'.join(map('{0} = {1} ({1.__class__.__name__})'.format, emojis, choices))

    # stubbing out each converters' search so it doesn't accidentally do the
    # reaction thing prematurely.
    async def search(self, ctx, argument, choices, *, thing):
        return choices

    async def convert(self, ctx, argument):
        choices = []
        for searcher in self.searchers:
            try:
                with temp_attr(searcher, 'search', self.search):
                    entries = await searcher(**self.kwargs).convert(ctx, argument)
            except commands.BadArgument:
                continue
            else:
                choices.extend(always_iterable(entries))

        if not choices:
            type_names = (getattr(t, '__name__', t.__class__.__name__) for t in self.types)
            message = f'"{argument}" is neither a {human_join(type_names, final="nor")}.'
            raise commands.BadArgument(message)
        if len(choices) == 1:
            return choices[0]
        return await super().search(ctx, argument, choices, thing='entry')

    @property
    def searchers(self):        
        return list(filter(None, map(_type_search_maps.get, self.types)))

