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
from string import ascii_lowercase

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

        return await ctx.disambiguate(list(filter(predicate, guild.roles)))


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

        return await ctx.disambiguate(result)


class TextChannelSearch(commands.TextChannelConverter, Search):
    async def convert(self, ctx, argument):
        bot = ctx.bot

        match = self._get_id_match(argument) or re.match(r'<#([0-9]+)>$', argument)
        result = None
        guild = ctx.guild

        if match is not None:
            return await super().convert(ctx, argument)
        else:
            # not a mention
            lowered = argument.lower()

            def check(c):
                return isinstance(c, discord.TextChannel) and c.name.lower() == lowered

            if guild:
                result = list(filter(check, guild.text_channels))
            else:
                result = list(filter(check, bot.get_all_channels()))

        return await ctx.disambiguate(result)


class UserSearch(commands.UserConverter, Search):
    async def convert(self, ctx, argument):
        match = self._get_id_match(argument) or re.match(r'<@!?([0-9]+)>$', argument)
        state = ctx._state

        if match is not None:
            return await super().convert(ctx, argument)

        # check for discriminator if it exists
        # This should also be an exact match.
        if len(argument) > 5 and argument[-5] == '#':
            return await super().convert(ctx, argument)

        lowered = argument.lower()
        results = [u for u in state._users.values() if u.name.lower() == lowered]

        return await ctx.disambiguate(results)


class GuildSearch(commands.IDConverter, Search):
    async def convert(self, ctx, arg):
        match = self._get_id_match(arg)
        state = ctx._state
        if match:
            guild = ctx.bot.get_guild(int(match.group(1)))
            if guild:
                return guild

        lowered = arg.lower()
        guilds = [g for g in state._guilds.values() if g.name.lower() == lowered]
        return await ctx.disambiguate(guilds)


# A mapping for the discord.py class and it's corresponding searcher.
_type_search_maps = {
    discord.Role: RoleSearch,
    discord.Member: MemberSearch,
    discord.TextChannel: TextChannelSearch,
    discord.User: UserSearch,
    discord.Guild: GuildSearch,

}


# Function for stubbing out the context's disambiguate method
# so it doesn't accidentally do the prompt prematurely.
async def _dummy_disambiguate(matches, *args, **kwargs):
    return matches


class union(Search, commands.Converter):
    def __init__(self, *types, **kwargs):
        # Relying on the fact that Search.__init__ doesn't call super().__init__
        super().__init__(**kwargs)
        self.kwargs = kwargs
        self.types = types

    async def convert(self, ctx, argument):
        choices = []

        with temp_attr(ctx, 'disambiguate', _dummy_disambiguate):
            for searcher in self.searchers:
                try:
                    entries = await searcher(**self.kwargs).convert(ctx, argument)
                except commands.BadArgument:
                    continue
                else:
                    choices.extend(always_iterable(entries))

        return await ctx.disambiguate(choices, '{0} ({0.__class__.__name__})'.format)

    @property
    def searchers(self):
        return list(filter(None, map(_type_search_maps.get, self.types)))
