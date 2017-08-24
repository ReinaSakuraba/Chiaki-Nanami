import asyncio
import contextlib
import discord
import inspect
import io
import textwrap
import traceback

from discord.ext import commands

from .utils.context_managers import temp_attr


class Owner:
    """Owner-only commands"""
    __hidden__ = True

    def __init__(self, bot):
        self.bot = bot
        self._last_result = None

    async def __local_check(self, ctx):
        return await ctx.bot.is_owner(ctx.author)

    def _create_env(self, ctx):
        return {
            'bot': self.bot,
            'ctx': ctx,
            'message': ctx.message,
            'guild': ctx.guild,
            'server': ctx.guild,
            'channel': ctx.channel,
            'author': ctx.author,
            **globals()
        }

    @commands.command(hidden=True)
    async def debug(self, ctx, *, code: str):
        """Evaluates code."""
        code = code.strip('` ')

        env = self._create_env(ctx)
        try:
            result = eval(code, env)
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:
            await ctx.send(f'```py\n{traceback.format_exc()}```')
        else:
            await ctx.send(f'```py\n{result}```')

    @staticmethod
    def cleanup_code(body):
        # remove ```py\n```
        if body.startswith('```') and body.endswith('```'):
            return '\n'.join(body.split('\n')[1:-1])

        # remove `foo`
        return body.strip('` \n')

    @staticmethod
    def get_syntax_error(e):
        if e.text is None:
            return '```py\n{0.__class__.__name__}: {0}\n```'.format(e)
        return '```py\n{0.text}{1:>{0.offset}}\n{2}: {0}```'.format(e, '^', type(e).__name__)

    @commands.command(hidden=True, name='eval', aliases=['exec'])
    async def _eval(self, ctx, *, body: str):
        """Evaluates more code"""
        env = {**self._create_env(ctx), '_': self._last_result}
        body = self.cleanup_code(body)
        to_compile = f'async def func():\n{textwrap.indent(body, "  ")}'

        try:
            exec(to_compile, env)
        except SyntaxError as e:
            return await ctx.send(self.get_syntax_error(e))

        func = env['func']
        with io.StringIO() as stdout:
            try:
                with contextlib.redirect_stdout(stdout):
                    ret = await func()
            except Exception as e:
                value = stdout.getvalue()
                await ctx.send(f'```py\n{value}{traceback.format_exc()}\n```')
            else:
                value = stdout.getvalue()
                with contextlib.suppress(discord.HTTPException):
                    await ctx.message.add_reaction('\u2705')

                if ret is None:
                    if value:
                        await ctx.send(f'```py\n{value}\n```')
                else:
                    self._last_result = ret
                    await ctx.send(f'```py\n{value}{ret}\n```')

    @commands.command(hidden=True)
    async def botav(self, ctx, *, avatar):
        with open(avatar, 'rb') as f:
            await self.bot.user.edit(avatar=f.read())
        await ctx.send('\N{OK HAND SIGN}')

    @commands.command(hidden=True)
    async def load(self, ctx, cog: str):
        """Loads a bot-extension (one with a setup method)"""
        ctx.bot.load_extension(cog)
        await ctx.send('Ok onii-chan~')

    @commands.command(hidden=True)
    async def unload(self, ctx, cog: str):
        """Unloads a bot-extension (one with a setup method)"""
        ctx.bot.unload_extension(cog)
        await ctx.send('Ok onii-chan~')

    @commands.command(hidden=True)
    async def reload(self, ctx, cog: str):
        """Reloads a bot-extension (one with a setup method)"""
        ctx.bot.unload_extension(cog)
        ctx.bot.load_extension(cog)
        await ctx.send('Ok onii-chan~')

    @load.error
    @unload.error
    @reload.error
    async def load_error(self, ctx, error):
        traceback.print_exc()
        await ctx.send("Baka! You didn't code me properly  >///<")

    @commands.command(hidden=True, aliases=['kys'])
    async def die(self, ctx):
        """Shuts the bot down"""
        await ctx.send("Bye... Please don't forget about me.")
        await ctx.bot.logout()

    @commands.command(hidden=True, aliases=['restart'])
    async def reset(self, ctx):
        """Restarts the bot"""
        ctx.bot.reset_requested = True
        await ctx.send("Sleepy... zZzzzzZ...")
        await ctx.bot.logout()

    @commands.command(hidden=True)
    async def say(self, ctx, *, msg):
        await ctx.message.delete()
        # make sure commands for other bots (or even from itself) can't be executed
        await ctx.send(f"\u200b{msg}")

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
    bot.add_cog(Owner(bot))
