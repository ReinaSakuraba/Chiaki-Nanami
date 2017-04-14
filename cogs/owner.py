import argparse
import asyncio
import copy
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
        self.bot = bot

    async def __local_check(self, ctx):
        return await checks.is_owner_predicate(ctx)

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

    @commands.command(hidden=True, enabled=False)
    async def editbot(self, ctx, *args: str):
        """Edits the bot's profile"""
        parser = argparse.ArgumentParser(description="Edit me in cool ways")
        bot_user = self.bot.user
        parser.add_argument('--avatar', '--av', nargs='?', default=None)
        parser.add_argument('--name', '-n', nargs='?', default=bot.user.name)
        try:
            namespace = parser.parse_args(args)
        except (Exception, SystemExit) as e:
            return await ctx.send(f"Failed to parse args. Exception:\n```py\n{type(e).__name__}: {e}```")

        if args.avatar:
            with open(args.avatar, 'rb') as f:
                namespace['avatar'] = f.read()
        else:
            namespace['avatar'] = bot_user.avatar

        user_edit_namespace = {k: namespace[k] for k in ['avatar', 'name']}
        try:
            await bot_user.edit(**user_edit_namespace)
        except Exception as e:
            pass
        else:
            await ctx.send(":ok_hand:")

    @commands.command(hidden=True)
    async def reload(self, ctx, cog: str):
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
        await self._attempt_external_import(ctx, 'reload', module, message='reload')

    @commands.command(hidden=True)
    async def loadext(self, ctx, module):
        await self._attempt_external_import(ctx, 'import_module', module, message='import')

    @commands.command(hidden=True)
    async def load(self, ctx, cog: str):
        await self._load(ctx, cog)

    @commands.command(hidden=True)
    async def unload(self, ctx, cog: str):
        self.bot.unload_extension(cog)
        await ctx.send(f'```Unloaded {cog}```')

    @commands.command(hidden=True, aliases=['kys'])
    async def die(self):
        await self.bot.logout()

    @commands.command(hidden=True, aliases=['restart'])
    async def reset(self):
        self.bot.reset_requested = True
        await self.bot.logout()

    @commands.command(hidden=True)
    async def say(self, ctx, *, msg):
        # make sure commands for other bots (or even from itself) can't be executed
        await ctx.send(f"\u200b{msg}")

    @commands.command(hidden=True)
    async def announce(self, *, msg):
        owner = (await self.bot.application_info()).owner
        for guild in bot.guilds:
            await guild.default_channel.send(server, f"@everyone **Announcement from {owner}\n\"{msg}\"")

    @commands.command(name="sendmessage", hidden=True)
    async def send_message(self, channel: discord.TextChannel, *, msg):
        owner = (await self.bot.application_info()).owner
        await channel.send(f"Message from {owner}:\n{msg}")
        await ctx.send(f"Successfully sent message in {channel}: {msg}")

    @commands.command(hidden=True)
    async def do(self, ctx, num: int, *, command):
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
    bot.add_cog(Owner(bot))
