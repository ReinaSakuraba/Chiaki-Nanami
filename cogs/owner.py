import argparse
import copy
import discord
import importlib
import inspect
import sys
import traceback

from discord.ext import commands

from .utils import checks
from .utils.converter import item_converter
from .utils.misc import code_msg

class Owner:
    """Owner-only commands"""
    __prefix__ = ">>>"
    def __init__(self, bot):
        self.bot = bot

    async def _load(self, ext):
        try:
            self.bot.load_extension(ext)
        except Exception as e:
            print(f'Failed to load extension {ext}\n')
            traceback.print_exc()
            await self.bot.say(code_msg(traceback.format_exc(), 'py'))
        else:
            await self.bot.say(code_msg(f'load {ext} successful'))

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    async def debug(self, ctx, *, code: str):
        """Evaluates code."""
        code = code.strip('` ')
        python = '```py\n{}\n```'
        result = None

        env = {
            'bot': self.bot,
            'ctx': ctx,
            'message': ctx.message,
            'server': ctx.message.server,
            'channel': ctx.message.channel,
            'author': ctx.message.author,
            **globals()
        }

        try:
            result = eval(code, env)
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:
            exc_fmt = "{0.__class__.__name__}: {0}"
            return await self.bot.say(python.format(traceback.format_exc()))

        await self.bot.say(python.format(result))

    @commands.command(hidden=True)
    @checks.is_owner()
    async def editbot(self, *args: str):
        parser = argparse.ArgumentParser(description="Edit me in cool ways")
        bot = self.bot
        args = parser.parse_args(args)

    @commands.command(hidden=True)
    @checks.is_owner()
    async def botav(self, *, new_avatar: str):
        with open(new_avatar, 'rb') as f:
            await self.bot.edit_profile(avatar=f.read())

    async def _attempt_external_import(self, func, module, *, message):
        try:
            getattr(importlib, func)(module)
        except Exception as e:
            await self.bot.say(f"Failed to {message} module")
            raise
        else:
            await self.bot.say("\N{THUMBS UP SIGN}")

    @commands.command(hidden=True)
    async def reloadext(self, module: item_converter(sys.modules)):
        """Attempts to reload a non-extension module (one that doesn't have a setup method)

        Do note that just because you successfully reload the module,
        extensions that have imported said module will not automatically have the new one.
        Make sure you reload them as well.
        """
        await self._attempt_external_import('reload', module, message='reload')

    @commands.command(hidden=True)
    async def loadext(self, module):
        """Attempts to load a non-extension module (one that doesn't have a setup method)

        Do note that just because you successfully reload the module,
        extensions that have imported said module will not automatically have the new one.
        Make sure you reload them as well.
        """
        await self._attempt_external_import('import_module', module, message='import')

    @commands.command(hidden=True)
    @checks.is_owner()
    async def reload(self, cog: str):
        """Reloads a bot-extension (one with a setup method)"""
        self.bot.unload_extension(cog)
        await self._load(cog)

    @commands.command(hidden=True)
    @checks.is_owner()
    async def load(self, cog: str):
        """Loads a bot-extension (one with a setup method)"""
        await self._load(cog)

    @commands.command(hidden=True)
    @checks.is_owner()
    async def unload(self, cog: str):
        """Unloads a bot-extension (one with a setup method)"""
        self.bot.unload_extension(cog)

    @commands.command(hidden=True, aliases=['kys'])
    @checks.is_owner()
    async def die(self):
        """Shuts the bot down"""
        await self.bot.logout()

    @commands.command(hidden=True)
    @checks.is_owner()
    async def say(self, *, msg):
        # make sure commands for other bots (or even from itself) can't be executed
        await self.bot.say(f"\u200b{msg}")

    @commands.command(hidden=True)
    @checks.is_owner()
    async def announce(self, *, msg):
        """Makes an announcement to all the servers that the bot is in"""
        owner = (await self.bot.application_info()).owner
        for server in bot.servers:
            await self.bot.send_message(server, f"@everyone **Announcement from {owner}\n\"{msg}\"")

    @commands.command(name="sendmessage", hidden=True)
    @checks.is_owner()
    async def send_message(self, channel: discord.Channel, *, msg):
        """Sends a message to a particular channel"""
        owner = (await self.bot.application_info()).owner
        await self.bot.send_message(channel, f"Message from {owner}:\n{msg}")
        await self.bot.say(f"Successfully sent message in {channel}: {msg}")

    @commands.command(name='testcommands', pass_context=True, aliases=['tcmd'])
    async def test_commands(self, ctx):
        message = copy.copy(ctx.message)


def setup(bot):
    bot.add_cog(Owner(bot), hidden=True)
