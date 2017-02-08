import discord

from discord.ext import commands

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

class BotCogConverter(commands.Converter):
    def __init__(self, ctx, argument):
        super().__init__(ctx, argument)
        self.alts = []

    def convert(self):
        cog = self.argument.lower()
        cog_name = discord.utils.find(lambda s: s.lower() == cog, self.ctx.bot.cogs)
        if cog_name is not None:
            return cog_name

        if cog in self.alts:
            return cog
        raise commands.BadArgument(f"Cog {cog} not found")

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
        return [cmd.qualified_name.split()[0], *cmd.aliases]
