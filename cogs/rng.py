import asyncio
import colorsys
import discord
import random
import string
import uuid

try:
    import secrets
except ImportError:  # unlikely but whatevs
    secrets = random.SystemRandom()

from discord.ext import commands

from .utils.errors import InvalidUserArgument, private_message_only
from .utils.misc import str_join

SMASHERS = ("Auto Smasher", "Landmine", "Smasher", "Spike",)
BALL_ANSWERS = ("Yes", "No", "Maybe so", "Definitely", "I think so",
                "Probably", "I don't think so", "Probably not",
                "I don't know", "I have no idea",
                )

_default_letters = string.ascii_letters + string.digits
def _password(length, alphabet=_default_letters):
    return ''.join(secrets.choice(alphabet) for i in range(length))

def _make_maze(w=16, h=8):
    randrange, shuffle = random.randrange, random.shuffle
    vis = [[0] * w + [1] for _ in range(h)] + [[1] * (w + 1)]
    ver = [["|  "] * w + ['|'] for _ in range(h)] + [[]]
    hor = [["+--"] * w + ['+'] for _ in range(h + 1)]

    def walk(x, y):
        vis[y][x] = 1

        d = [(x - 1, y), (x, y + 1), (x + 1, y), (x, y - 1)]
        shuffle(d)
        for (xx, yy) in d:
            if vis[yy][xx]: continue
            if xx == x: hor[max(y, yy)][x] = "+  "
            if yy == y: ver[y][max(x, xx)] = "   "
            walk(xx, yy)

    walk(randrange(w), randrange(h))
    return(''.join(a + ['\n'] + b) for (a, b) in zip(hor, ver))

class RNG:
    def __init__(self, bot):
        self.bot = bot

    @commands.command(pass_context=True, name="8ball", aliases=['8'])
    async def ball(self, ctx, *, question: str):
        """...it's a 8-ball"""
        if question.endswith('?'):
            qfmt = "\n:question:: **{}**\n"
            msg = await self.bot.reply(qfmt.format(question))
            await asyncio.sleep(random.uniform(0.5, 1.5))
            afmt =  "{}\n:8ball:: {}"
            for i in range(4):
                await self.bot.edit_message(msg, afmt.format(msg.content, "." * i))
                await asyncio.sleep(random.uniform(0.75, 1.25))
            answer = random.choice(BALL_ANSWERS)
            await self.bot.edit_message(msg, afmt.format(msg.content, f"***__{answer    }__***"))
        else:
            await self.bot.say("That's not a question, I think")

    @commands.group(pass_context=True, aliases=['rand'])
    async def random(self, ctx):
        """Super-command for all the random commands"""
        if ctx.invoked_subcommand is None:
            is_alias = lambda cmd: any(cmd in c.aliases for c in ctx.command.commands.values())
            subcommands = '\n'.join([cmd for cmd in ctx.command.commands if not is_alias(cmd)])
            await self.bot.say(f"```\nAvailable info commands:\n{subcommands}```")

    @random.command(aliases=['dice'], enabled=False)
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
        if points <= 33:
            return '/'.join(map(str, self._build(points, *stats)))
        raise InvalidUserArgument(f"You have too many points ({points})")

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
        return random.choice(self.bot.get_cog("WRA").all_tanks())

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
        await self.bot.say(f'{build} {cwass}')

    @random.command(aliases=['color'])
    async def colour(self):
        """Generates a random colo(u)r."""
        colour_long = random.randrange(255 ** 3)
        colour = discord.Colour(colour_long)
        r, g, b = colour.to_tuple()
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        hsv = [round(h * 360, 3), round(s * 100, 3), round(v * 100, 3)]

        colour_embed = (discord.Embed(title=str(colour), colour=colour)
                       .add_field(name="RGB", value=str_join(', ', (r, g, b)))
                       .add_field(name="HSV", value=str_join(', ', hsv))
                       )
        await self.bot.say(embed=colour_embed)

    @commands.cooldown(rate=10, per=5, type=commands.BucketType.server)
    @random.command()
    async def uuid(self):
        """Generates a random uuid.

        Because of potential abuse, this commands has a 5 second cooldown
        """
        await self.bot.say(uuid.uuid4())

    @random.command(pass_context=True, aliases=['pw'])
    @private_message_only("Why are you asking for a password in public...?")
    async def password(self, ctx, n: int=8, *rest: str):
        """Generates a random password

        Don't worry, this uses a cryptographically secure RNG.
        However, you can only execute this in private messages
        """
        if n < 8:
            raise InvalidUserArgument(f"How can you expect a secure password in just {n} characters?")

        rest = list(map(str.lower, rest))
        letters = _default_letters
        if 'symbols' in rest:
            letters += string.punctuation
        if 'microsoft' in rest:
            symbol_deletion = dict.fromkeys(map(ord, string.punctuation), None)
            letters = letters.translate(symbol_deletion)
        password = _password(n, letters)
        print(password)
        await self.bot.say(password)

    @random.command(pass_context=True)
    async def maze(self, ctx, w: int=5, h: int=5):
        """Generates a random maze"""
        maze = '\n'.join(_make_maze(w, h))
        try:
            await self.bot.say(f"```\n{maze}```")
        except discord.HTTPException:
            await self.bot.say(f"The maze you've generated (**{w}** by **{h}**) is too large")


def setup(bot):
    bot.add_cog(RNG(bot))
