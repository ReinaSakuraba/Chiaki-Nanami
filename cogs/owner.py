import argparse
import asyncio
import discord
import inspect
import importlib
import sys
import traceback

from discord.ext import commands

from .utils import checks
from .utils.converter import item_converter
from .utils.context_managers import temp_attr
from .utils.misc import code_msg

class Owner:
    """Owner-only commands"""
    __hidden__ = True

    def __init__(self, bot):
        # We don't do the owner_check right away - it's in setup()
        # The reason why we do this is so that Bot Owner will show up as a requirement
        # As __local_check isn't shown in the actual command
        # TODO: Work with __local_check
        self.bot = bot

    async def _load(self, ctx, ext):
        try:
            self.bot.load_extension(ext)
        except Exception as e:
            print(f'Failed to load extension {ext}\n')
            traceback.print_exc()
            await ctx.send(code_msg(traceback.format_exc(), 'py'))
        else:
            await ctx.send(code_msg(f'load {ext} successful'))

    @commands.command(hidden=True)
    async def debug(self, ctx, *, code: str):
        """Evaluates code."""
        code = code.strip('` ')

        env = {
            'bot': self.bot,
            'ctx': ctx,
            'message': ctx.message,
            'guild': ctx.guild,
            'server': ctx.guild,
            'channel': ctx.channel,
            'author': ctx.author,
            **globals()
        }

        try:
            result = eval(code, env)
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:
            await ctx.send(code_msg(traceback.format_exc(), 'py'))
        else:
            await ctx.send(code_msg(result, 'py'))

    @commands.command(hidden=True)
    async def botav(self, ctx, *, avatar):
        with open(avatar, 'rb') as f:
            await self.bot.user.edit(avatar=f.read())
        await ctx.send('\N{OK HAND SIGN}')

    @commands.command(hidden=True)
    async def reload(self, ctx, cog: str):
        """Reloads a bot-extension (one with a setup method)"""
        self.bot.unload_extension(cog)
        await self._load(ctx, cog)

    @staticmethod
    async def _attempt_external_import(ctx, func, module, *, message):
        try:
            getattr(importlib, func)(module)
        except Exception as e:
            await ctx.send(f"Failed to {message} module")
            raise
        else:
            await ctx.send("\N{THUMBS UP SIGN}")

    @commands.command(hidden=True)
    async def reloadext(self, ctx, module: item_converter(sys.modules)):
        """Attempts to reload a non-extension module (one that doesn't have a setup method)

        Do note that just because you successfully reload the module,
        extensions that have imported said module will not automatically have the new one.
        Make sure you reload them as well.
        """
        await self._attempt_external_import(ctx, 'reload', module, message='reload')

    @commands.command(hidden=True)
    async def loadext(self, ctx, module):
        """Attempts to load a non-extension module (one that doesn't have a setup method)

        Do note that just because you successfully reload the module,
        extensions that have imported said module will not automatically have the new one.
        Make sure you reload them as well.
        """
        await self._attempt_external_import(ctx, 'import_module', module, message='import')

    @commands.command(hidden=True)
    async def load(self, ctx, cog: str):
        """Loads a bot-extension (one with a setup method)"""
        await self._load(ctx, cog)

    @commands.command(hidden=True)
    async def unload(self, ctx, cog: str):
        """Unloads a bot-extension (one with a setup method)"""
        self.bot.unload_extension(cog)
        await ctx.send(f'```Unloaded {cog}```')

    @commands.command(hidden=True, aliases=['kys'])
    async def die(self, ctx):
        """Shuts the bot down"""
        await ctx.bot.logout()

    @commands.command(hidden=True, aliases=['restart'])
    async def reset(self, ctx):
        """Restarts the bot"""
        ctx.bot.reset_requested = True
        await ctx.bot.logout()

    @commands.command(hidden=True)
    async def say(self, ctx, *, msg):
        # make sure commands for other bots (or even from itself) can't be executed
        await ctx.send(f"\u200b{msg}")

    @commands.command(hidden=True)
    async def announce(self, ctx, *, msg):
        """Makes an announcement to all the servers that the bot is in"""
        owner = (await self.bot.application_info()).owner
        for guild in bot.guilds:
            await guild.default_channel.send(server, f"@everyone **Announcement from {owner}\n\"{msg}\"")

    @commands.command(name="sendmessage", hidden=True)
    async def send_message(self, ctx, channel: discord.TextChannel, *, msg):
        """Sends a message to a particular channel"""
        owner = (await self.bot.application_info()).owner
        await channel.send(f"Message from {owner}:\n{msg}")
        await ctx.send(f"Successfully sent message in {channel}: {msg}")

    @commands.command(hidden=True)
    async def do(self, ctx, num: int, *, command):
        """Repeats a command a given amount of times"""
        with temp_attr(ctx.message, 'content', command):
            for i in range(num):
                await self.bot.process_commands(ctx.message)

    @commands.command(hidden=True, aliases=['chaincmd'])
    async def chaincommand(self, ctx, *commands):
        for cmd in commands:
            with temp_attr(ctx.message, 'content', cmd):
                await self.bot.process_commands(ctx.message)
                # prevent rate-limiting.
                await asyncio.sleep(1)

def setup(bot):
    owner = Owner(bot)
    local_check = checks.ChiakiCheck(checks.is_owner_predicate, role="Bot Owner")
    for name, member in inspect.getmembers(owner):
        if isinstance(member, commands.Command):
            member.checks.append(local_check)

    bot.add_cog(owner)
