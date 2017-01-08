import asyncio
import colorsys
import discord
import random

from discord.ext import commands

def _load_tanks():
    with open("data/tanks.txt") as f:
        return f.read().splitlines()

TANKS = _load_tanks()
SMASHERS = ("Auto Smasher", "Landmine", "Smasher", "Spike",)
BALL_ANSWERS = ("Yes", "No", "Maybe so", "Definitely", "I think so",
                "Probably", "I don't think so", "Probably not",
                "I don't know", "I have no idea",
                )

class RNG:
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(pass_context=True, name="8ball", aliases=['8'])
    async def ball(self, ctx, *, question: str):
        """...it's a 8-ball"""
        print(question)
        user = ctx.message.author.mention
        if question.endswith('?'):
            qfmt = "{}\n:question:: **{}**\n"
            msg = await self.bot.say(qfmt.format(user,
                                           question))
            await asyncio.sleep(random.uniform(0.5, 1.5))
            answer = random.choice(BALL_ANSWERS)
            afmt =  "{}\n:8ball:: {}"
            for i in range(6):
                await self.bot.edit_message(msg,
                                            afmt.format(msg.content, "." * i))
                await asyncio.sleep(random.uniform(0.25, 0.75))
            
            await self.bot.edit_message(msg, afmt.format(msg.content, answer))
        else:
            await self.bot.say("That's not a question, I think")
    
    @commands.group(pass_context=True, aliases=['rand'])
    async def random(self, ctx):
        pass

    @random.command(aliases=['dice'])
    async def diceroll(self, amt):
        """Rolls a certain number of dice"""
        fmt = "{} " * amt
        await self.bot.say(fmt.format(*[random.randint(1, 6) for _ in range(amt)]))
    
    # diep.io related commands
    def _build(self, points, num_stats, max_stats):
        stats = [0] * num_stats
        while points > 0:
            idx = random.randrange(num_stats)
            if stats[idx] < max_stats:
                stats[idx] += 1
                points -= 1
        return stats

    def _build_str(self, points : int=33, smasher : bool=False):
        stats = (4, 10) if smasher else (8, 7)
        if points > 33:
            return "You have too many points"
        return '/'.join(map(str, self._build(points, *stats)))
    
    @random.command()
    async def build(self, points : int=33):
        """Gives you a random build to try out

        If points is not provided, it defaults to a max-level build (33)"""
        await self.bot.say(self._build_str(points))

    @random.command()
    async def smasher(self, points : int=33):
        """Gives you a random build for the Smasher branch to try out

        If points is not provided, it defaults to a max-level build (33)"""
        await self.bot.say(self._build_str(points, True))

    def _class(self):
        return random.choice(TANKS)

    @random.command(name="class")
    async def class_(self):
        """Gives you a random class to play"""
        await self.bot.say(self._class())

    @random.command()
    async def tank(self, points : int=33):
        """Gives you a random build AND class to play

        If points is not provided, it defaults to a max-level build (33)"""
        cwass = self._class()
        build = self._build_str(points, cwass in SMASHERS)
        await self.bot.say('{} {}'.format(build, cwass))

    @random.command(aliases=['color'])
    async def colour(self):
        colour_long = random.randrange(255 ** 3)
        colour = discord.Colour(colour_long)
        r, g, b = colour.to_tuple()
        colour_embed = discord.Embed(title=str(colour),
                                     colour=colour)
        colour_embed.add_field(name="RGB", value=', '.join(map(str, (r, g, b))))
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        hsv = [round(h * 360, 3), round(s * 100, 3), round(v * 100, 3)]
        colour_embed.add_field(name="HSV", value=', '.join(map(str, hsv)))
        await self.bot.say(embed=colour_embed)


def setup(bot):
    bot.add_cog(RNG(bot))
    

                        
