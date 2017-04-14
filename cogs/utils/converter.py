import argparse
import discord
import inspect
import re

from collections import namedtuple
from discord.ext import commands
from functools import partial

from .compat import ilen
from .context_managers import redirect_exception
from .errors import InvalidUserArgument
from .misc import pairwise, parse_int

# We need this because discord.py rewrite converters no longer puts ctx or arg in __init__
# Thie makes one-lining it near-impossible.
def make_converter(converter, ctx, arg, *converter_args, **converter_kwargs):
    c = converter(*converter_args, **converter_kwargs)
    c.prepare(ctx, arg)
    return c

def type_to_converter(type_):
    """Returns the underlying converter that discord.py uses for converting arguments."""
    if type_ is bool:
        return commands.core._convert_to_bool
    module = getattr(type_, '__module__', '')
    return (getattr(commands, f'{type_.__name__}Converter', type_)
            if module.startswith('discord') and not module.endswith('converter') else _type)

class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise commands.BadArgument(f'Failed to parse args.```\n{message}```')

class ApproximateUser(commands.MemberConverter):
    async def convert(self):
        arg = self.argument
        channel, guild = self.ctx.channel, self.ctx.guild
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
        return super().convert()

# Is there any way to make this such that there's no repetition?
class ApproximateRole(commands.RoleConverter):
    async def convert(self):
        arg = self.argument
        channel, guild = self.ctx.channel, self.ctx.guild
        arg_lowered = arg.lower()

        if guild:
            role_filter = (role for role in guild.roles if arg_lowered in role.name.lower())
            next_role = next(role_filter, None)
            if next_role is not None:
                if next(role_filter, None):
                    await channel.send(f"(I found {ilen(role_filter) + 2} occurences of '{arg}'. "
                                        "I'll take the first result, probably.)")
                return next_role
        return super().convert()

class BotCogConverter(commands.Converter):
    def __init__(self):
        super().__init__()

    def convert(self):
        bot = self.ctx.bot
        lowered = self.argument.lower()

        result = discord.utils.find(lambda k: k.lower() == lowered, bot.all_cogs)
        if result is None:
            raise commands.BadArgument(f"Module {lowered} not found")

        return bot.all_cogs[result]

class BotCommand(commands.Converter):
    def __init__(self, *, recursive=False):
        self.convert = self._recursive_convert if recursive else self._convert

    def _convert(self):
        cmd = self.ctx.bot.get_command(self.argument)
        if cmd is None:
            raise commands.BadArgument(f"I don't recognized the {self.argument} command")
        return cmd

    def _recursive_convert(self):
        cmd_path = self.argument
        obj = bot = self.ctx.bot
        for cmd in cmd_path.split() if isinstance(cmd_path, str) else cmd_path:
            try:
                obj = obj.get_command(cmd)
                if obj is None:
                    raise commands.BadArgument(bot.command_not_found.format(cmd_path))
            except AttributeError:
                raise commands.BadArgument(bot.command_has_no_subcommands.format(obj))
        return obj

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

_time_pattern = ''.join(f'(?:([0-9]{{1,5}})({u1}|{u2}))?' for u1, u2 in pairwise(DURATION_MULTIPLIERS))
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
        return sum(float(amount) * DURATION_MULTIPLIERS[unit] for amount, unit in pairwise(no_nones))

class union(commands.Converter):
    def __init__(self, *types):
        self.types = types

    async def convert(self):
        arg, ctx = self.argument, self.ctx
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
                                    "Available options:\n{', '.join(choices)}")
    return in_converter
