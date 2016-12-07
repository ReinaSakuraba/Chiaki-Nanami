from .utils.aitertools import ACountdown
from discord.ext import commands

class Timer:
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(pass_context=True)
    async def countdown(self, ctx, delay : int, *, msg : str):
        bot = self.bot
        await bot.delete_message(ctx.message)
        message = await bot.say("Counting down...")
        async for i in ACountdown(delay):
            await bot.edit_message(message, i)
        await bot.delete_message(message)
        await bot.say(msg)

def setup(bot):
    bot.add_cog(Timer(bot))
