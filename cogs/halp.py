from .utils.misc import str_swap as _str_swap
from discord.ext import commands
import re

_mentions_transforms = {
    '@everyone': '@\u200beveryone',
    '@here': '@\u200bhere'
}

async def default_help(ctx, func=lambda s:s, *commands : str):
    commands = [s.lower() for s in commands]

    _mention_pattern = re.compile('|'.join(_mentions_transforms.keys()))

    bot = ctx.bot
    destination = ctx.message.author if bot.pm_help else ctx.message.channel

    def repl(obj):
        return _mentions_transforms.get(obj.group(0), '')

    # help by itself just lists our own commands.
    if len(commands) == 0:
        pages = bot.formatter.format_help_for(ctx, bot)
    elif len(commands) == 1:
        # try to see if it is a cog name
        name = _mention_pattern.sub(repl, commands[0])
        command = None
        if name in bot.cogs:
            command = bot.cogs[name]
        else:
            command = bot.commands.get(name)
            if command is None:
                await bot.send_message(destination, bot.command_not_found.format(name))
                return

        pages = bot.formatter.format_help_for(ctx, command)
    else:
        name = _mention_pattern.sub(repl, commands[0])
        command = bot.commands.get(name)
        if command is None:
            await bot.send_message(destination, bot.command_not_found.format(name))
            return

        for key in commands[1:]:
            try:
                key = _mention_pattern.sub(repl, key)
                command = command.commands.get(key)
                if command is None:
                    await bot.send_message(destination, bot.command_not_found.format(key))
                    return
            except AttributeError:
                await bot.send_message(destination, bot.command_has_no_subcommands.format(command, key))
                return

        pages = bot.formatter.format_help_for(ctx, command)

    if bot.pm_help is None:
        characters = sum(map(lambda l: len(l), pages))
        # modify destination based on length of pages.
        if characters > 1000:
            destination = ctx.message.author
        
        print("Hope I made it here")
        for page in pages:
            await bot.send_message(destination, func(page))

class Help:
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(pass_context=True, aliases=['HALP'])
    async def halp(self, ctx, *commands : str):
        await default_help(ctx, str.upper, *commands)

    @commands.command(pass_context=True) 
    async def pleh(self, ctx, *commands : str):
        await default_help(ctx, lambda s: _str_swap(s[::-1], '(', ')'), *commands)

    @commands.command(pass_context=True, aliases=['PLAH'])
    async def plah(self, ctx, *commands : str):
        await default_help(ctx, lambda s: _str_swap(s[::-1].upper(), '(', ')'), *commands)

def setup(bot):
    bot.add_cog(Help(bot))
