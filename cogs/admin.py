import discord
import inspect
import traceback

from discord.ext import commands
from .utils import checks

class Admin:

    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    async def debug(self, ctx, *, code : str):
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
            return await self.bot.say(python.format(type(e).__name__ + ': ' + str(e)))
            

        await self.bot.say(python.format(result))

    
    @commands.command(hidden=True)
    @checks.is_owner()
    async def playing(self, *, game : str):
        await self.bot.change_presence(game=discord.Game(name=game))
        await self.bot.say("Game changed to {}".format(game))

def setup(bot):
    bot.add_cog(Admin(bot))
