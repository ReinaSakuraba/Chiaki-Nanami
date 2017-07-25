import argparse
import discord
import inspect
import re

from collections import namedtuple
from contextlib import suppress
from discord.ext import commands
from functools import partial
from more_itertools import grouper, ilen

from .context_managers import redirect_exception
from .errors import InvalidUserArgument
from .misc import parse_int


_pairwise = partial(grouper, 2)

class NoBots(commands.BadArgument):
    """Exception raised in CheckedMember when the author passes a bot"""

class NoOfflineMembers(commands.BadArgument):
    """Exception raised in CheckedMember when the author passes a user who is offline"""

class NoSelfArgument(commands.BadArgument):
    """Exception raised in CheckedMember when the author passes themself as an argument"""


# Custom ArgumentParser because the one in argparse raises SystemExit upon failure, 
# which kills the bot
class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise commands.BadArgument(f'Failed to parse args.```\n{message}```')


class ApproximateUser(commands.MemberConverter):
    async def convert(self, ctx, arg):
        channel, guild = ctx.channel, ctx.guild
        arg_lower = arg.lower()

        if guild:
            def pred(elem):
                return (elem.nick and arg_lower in elem.nick.lower()) or arg_lower in elem.name.lower()

            filtered = filter(pred, guild.members)
            next_member = next(filtered, None)
            if next_member is not None:
                if next(filtered, None):
                    await channel.send(f"(I found {ilen(filtered) + 2} occurences of '{arg}'. "
                                        "I'll take the first result, probably.)")
                return next_member
        return await super().convert(ctx, arg)


# Is there any way to make this such that there's no repetition?
class ApproximateRole(commands.RoleConverter):
    async def convert(self, ctx, arg):
        channel, guild = ctx.channel, ctx.guild
        arg_lowered = arg.lower()

        if guild:
            role_filter = (role for role in guild.roles if arg_lowered in role.name.lower())
            next_role = next(role_filter, None)
            if next_role is not None:
                if next(role_filter, None):
                    await channel.send(f"(I found {ilen(role_filter) + 2} occurences of '{arg}'. "
                                        "I'll take the first result, probably.)")
                return next_role
        return await super().convert(ctx, arg)


class CheckedMember(commands.MemberConverter):
    def __init__(self, *, offline=True, bot=True, include_self=False):
        super().__init__()
        self.self = include_self
        self.offline = offline
        self.bot = bot

    async def convert(self, ctx, arg):
        member = await super().convert(ctx, arg)
        if member.status is discord.Status.offline and not self.offline:
            raise NoOfflineMembers(f'{member} is offline...')
        if member.bot and not self.bot:
            raise NoBots(f"{member} is a bot. You can't use a bot here.")
        if member == ctx.author:
            raise NoSelfArgument("You can't use yourself. lol.")

        return member


class BotCogConverter(commands.Converter):
    async def convert(self, ctx, arg):
        bot = ctx.bot
        lowered = arg.lower()

        result = discord.utils.find(lambda k: k.lower() == lowered, bot.all_cogs)
        if result is None:
            raise commands.BadArgument(f"Module {lowered} not found")

        return bot.all_cogs[result]


class BotCommand(commands.Converter):
    async def convert(self, ctx, arg):
        cmd = ctx.bot.get_command(arg)
        if cmd is None:
            raise commands.BadArgument(f"I don't recognized the {arg} command")
        return cmd


def non_negative(num):
    num = parse_int(num)
    if num is None:
        raise commands.BadArgument(f'"{num}" is not a number.')
    if num >= 0:
        return num
    raise commands.BadArgument(f'Number cannot be negatives')


def attr_converter(obj, msg="Cannot find attribute {attr}."):
    def attrgetter(attr):
        if attr.startswith('_'):
            raise commands.BadArgument("That is not a valid attribute... ")
        try:
            return getattr(obj, attr)
        except AttributeError:
            raise commands.BadArgument(msg.format(attr=attr))
    return attrgetter


def number(s):
    for typ in (int, float):
        try:
            return typ(s)
        except ValueError:
            continue
    raise commands.BadArgument(f"{s} is not a number.")


def item_converter(d, *, key=lambda k: k, error_msg="Couldn't find key \"{arg}\""):
    def itemgetter(arg):
        with redirect_exception((Exception, error_msg.format(arg=arg)), cls=commands.BadArgument):
            return d[key(arg)]
    return itemgetter


DURATION_MULTIPLIERS = {
    'y': 60 * 60 * 24 * 365, 'yr' : 60 * 60 * 24 * 365,
    'w': 60 * 60 * 24 * 7,   'wk' : 60 * 60 * 24 * 7,
    'd': 60 * 60 * 24,       'day': 60 * 60 * 24,
    'h': 60 * 60,            'hr' : 60 * 60,
    'm': 60,                 'min': 60,
    's': 1,                  'sec': 1,
}

_time_pattern = ''.join(f'(?:([0-9]{{1,5}})({u1}|{u2}))?' for u1, u2 in _pairwise(DURATION_MULTIPLIERS))
_time_compiled = re.compile(f'{_time_pattern}$')

def duration(string):
    try:
        return float(string)
    except ValueError as e:
        match = _time_compiled.match(string)
        if match is None:
            # cannot use commands.BadArgument because on_command_error will say the command's __cause__
            # rather than the actual error.
            raise InvalidUserArgument(f'{string} is not a valid time.') from e
        no_nones = filter(None, match.groups())
        return sum(float(amount) * DURATION_MULTIPLIERS[unit] for amount, unit in _pairwise(no_nones))


class union(commands.Converter):
    def __init__(self, *types):
        self.types = types

    async def convert(self, ctx, arg):
        for type_ in self.types:
            try:
                # small hack here because commands.Command.do_conversion expects a Command instance
                # even though it's not used at all
                return await ctx.command.do_conversion(ctx, type_, arg)
            except Exception as e:
                continue
        raise commands.BadArgument(f"I couldn't parse {arg} successfully, "
                                   f"given these types: {', '.join([t.__name__ for t in self.types])}")


def in_(*choices):
    def in_converter(arg):
        lowered = arg.lower()
        if lowered in choices:
            return lowered
        raise commands.BadArgument(f"{lowered} is not valid option. "
                                   f"Available options:\n{', '.join(choices)}")
    return in_converter


def ranged(low, high=None, *, type=int):
    'Converter to check if an argument is in a certain range INCLUSIVELY'
    if high is None:
        low, high = 0, low

    def ranged_argument(arg):
        result = type(arg)
        if low <= result <= high:
            return result
        raise commands.BadArgument(f'Value must be between {low} and {high}, '
                                   f'or equal to {low} or {high}.')
    return ranged_argument
