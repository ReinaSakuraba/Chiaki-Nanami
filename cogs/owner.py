import discord
import inspect
import traceback

from discord.ext import commands
from .utils import checks
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
            print('Failed to load extension {}\n'.format(ext))
            traceback.print_exc()
            await self.bot.say(code_msg(traceback.format_exc()))
        else:
            await self.bot.say("```\nload {} successful```".format(ext))

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

    @commands.command(hidden=True, aliases=['sbg'])
    @checks.is_owner()
    async def setbotgame(self, *, game: str):
        """Changes the playing status (the "playing <game> thing under the user's name)"""
        await self.bot.change_presence(game=discord.Game(name=game))
        await self.bot.say("Game changed to {}".format(game))

    @commands.command(hidden=True)
    @checks.is_owner()
    async def reload(self, cog: str):
        self.bot.unload_extension(cog)
        await self._load(cog)

    @commands.command(hidden=True)
    @checks.is_owner()
    async def load(self, cog: str):
        await self._load(cog)

    @commands.command(hidden=True)
    @checks.is_owner()
    async def load(self, cog: str):
        self.bot.load_extension(cog)

    @commands.command(hidden=True)
    @checks.is_owner()
    async def botav(self, *, new_avatar: str):
        with open(new_avatar, 'rb') as f:
            await self.bot.edit_profile(avatar=f.read())
            
    @commands.command(hidden=True)
    @checks.is_owner()
    async def close(self):
        pass
        
def setup(bot):
    bot.add_cog(Owner(bot))