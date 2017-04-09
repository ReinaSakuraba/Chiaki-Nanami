import discord
import inspect

from collections import namedtuple
from discord.ext import commands

from .misc import parse_int

class ApproximateUser(commands.MemberConverter):
    async def convert(self):
        arg = self.argument
        bot = self.ctx.bot
        channel = self.ctx.message.channel
        server = self.ctx.message.server
        arg_lower = arg.lower()

        if server:
            def pred(elem):
                return (elem.nick and arg_lower in elem.nick.lower()) or arg_lower in elem.name.lower()

            member_filter = list(filter(pred, server.members))
            filter_length = len(member_filter)
            if filter_length > 1:
                await bot.send_message(channel, (f"(I found {filter_length} occurences of '{arg}'. "
                                                  "I'll take the first result, probably.)"))
            if member_filter:
                return member_filter[0]
        return super().convert()

# Is there any way to make this such that there's no repetition?
class ApproximateRole(commands.RoleConverter):
    async def convert(self):
        arg = self.argument
        bot = self.ctx.bot
        channel = self.ctx.message.channel
        server = self.ctx.message.server
        arg_lower = arg.lower()

        if server:
            def pred(elem):
                return arg_lower in elem.name.lower()

            role_filter = list(filter(pred, server.roles))
            role_length = len(role_filter)
            if role_length > 1:
                await bot.send_message(channel, (f"(I found {role_length} occurences of '{arg}'. "
                                                  "I'll take the first result, probably.)"))
            if role_filter:
                return role_filter[0]
        return super().convert()

NamePair = namedtuple('NamePair', 'name cmd')
class BotCogConverter(commands.Converter):
    def __init__(self, ctx, argument):
        super().__init__(ctx, argument)
        self.alts = []

    def convert(self):
        bot = self.ctx.bot
        cog = self.argument.lower()
        cog_pair = discord.utils.find(lambda s: s[0].lower() == cog, bot.cogs.items())
        if cog_pair is not None:
            return NamePair(*cog_pair)

        cog_alias_pair = discord.utils.find(lambda s: s[0].lower() == cog, bot.cog_aliases.items())
        if cog_alias_pair is not None:
            name = cog_alias_pair[1]
            return NamePair(name, bot.get_cog(name))

        if cog in self.alts:
            return NamePair(cog, None)
        raise commands.BadArgument(f"Modules {cog} not found")

def bot_cog_default(*defaults):
    class DefaultCogConverter(BotCogConverter):
        def __init__(self, ctx, argument):
            super().__init__(ctx, argument)
            self.alts = defaults
    return DefaultCogConverter

class BotCommandsConverter(commands.Converter):
    def convert(self):
        cmd = self.ctx.bot.get_command(self.argument)
        if cmd is None:
            raise commands.BadArgument(f"I don't recognized the {self.argument} command")
        return NamePair([cmd.qualified_name.split()[0], *cmd.aliases], cmd)

class RecursiveBotCommandConverter(commands.Converter):
    def convert(self):
        cmd_path = self.argument
        obj = bot = self.ctx.bot
        if isinstance(cmd_path, str):
            cmd_path = cmd_path.split()
        for cmd in cmd_path:
            try:
                obj = obj.get_command(cmd)
                if obj is None:
                    raise commands.BadArgument(bot.command_not_found.format(self.argument))
            except AttributeError:
                raise commands.BadArgument(bot.command_not_found.format(obj))
        return NamePair([obj.qualified_name.split()[0], *obj.aliases], obj)

def positive(num):
    num = parse_int(num)
    if num is None:
        raise commands.BadArgument(f'"{num}" is not a number.')
    if num >= 0:
        return num
    raise commands.BadArgument(f'Number must be positive')

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

def multi_converter(*types):
    converters = [getattr(commands, f'{typ.__name__}Converter')
                  if getattr(typ, '__module__', '').startswith('discord') else typ for typ in types]
    class MultiConverter(commands.Converter):
        async def convert(self):
            arg = self.argument
            for converter in converters:
                # isinstance(converter, commands.Converter) doesn't work for some reason
                actual_converter = (lambda arg: converter(self.ctx, arg).convert()
                                    if hasattr(converter, 'convert') else converter)
                try:
                    result = actual_converter(arg)
                    if inspect.isawaitable(result):
                        result = await result
                except Exception as e:
                    print(e)
                    continue
                else:
                    return result
            raise commands.BadArgument(f"I couldn't parse {arg} successfully, "
                                       f"given these types: {', '.join([t.__name__ for t in types])}")
    return MultiConverter
