import asyncio
import colorsys
import contextlib
import discord
import random
import secrets
import string
import uuid

from discord.ext import commands

from .utils.converter import attr_converter, number
from .utils.errors import InvalidUserArgument, private_message_only
from .utils.misc import str_join

try:
    import webcolors
except ImportError:
    webcolors = None
else:
    def _color_distance(c1, c2):
        return sum((v1 - v2) ** 2 for v1, v2 in zip(c1, c2))

    def closest_colour(requested_colour):
        min_colours = {name: _color_distance(webcolors.hex_to_rgb(key), requested_colour)
                       for key, name in webcolors.css3_hex_to_names.items()}
        return min(min_colours, key=min_colours.get)

    def get_colour_name(requested_colour):
        try:
            return webcolors.rgb_to_name(requested_colour)
        except ValueError:
            return closest_colour(requested_colour)

with contextlib.suppress(FileNotFoundError):
    with open(r'data\tanks.txt') as f:
        _back_up_tanks = f.read().splitlines()

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

_available_distributions = {
    'uniform': random.uniform,
    'int': random.randint,
    'range': random.randrange,
    'triangular': random.triangular,
    }

class RNG:
    __aliases__ = "Random",

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="8ball", aliases=['8'])
    async def ball(self, ctx, *, question: str):
        """...it's a 8-ball"""
        if not question.endswith('?'):
            raise InvalidUserArgument(f"{ctx.author.mention}, that's not a question, I think.")

        eight_ball_field_name = '\N{BILLIARDS} 8-ball'
        eight_ball_embed = (discord.Embed(colour=random.randint(0, 0xFFFFFF))
                           .add_field(name='\N{BLACK QUESTION MARK ORNAMENT} Question', value=question)
                           .add_field(name=eight_ball_field_name, value='\u200b', inline=False)
                           )
        msg = await ctx.send(content=ctx.author.mention, embed=eight_ball_embed)
        async with ctx.typing():
            for answer in ('...\N{THINKING FACE}', random.choice(BALL_ANSWERS)):
                await asyncio.sleep(random.uniform(0.75, 1.25) * 2)
                await msg.edit(embed=eight_ball_embed.set_field_at(-1, name=eight_ball_field_name, value=answer, inline=False))

        # TODO: Embeds
        # question_fmt = f"{ctx.author.mention}\n\N{BLACK QUESTION MARK ORNAMENT}: **{question}**"
        # msg = await ctx.send(question_fmt)
        # async with ctx.typing():
        #     for answer in ('...\N{THINKING FACE}', random.choice(BALL_ANSWERS)):
        #         await asyncio.sleep(random.uniform(0.75, 1.25) * 2)
        #         await msg.edit(content=f"{question_fmt}\n\N{BILLIARDS}: {answer}")

    @commands.command(usage='Nadeko;Salt;PvPCraft;mee6;Chiaki Nanami')
    async def choose(self, ctx, *, choices: str):
        """Chooses between a list of choices separated by semicolons"""
        with ctx.channel.typing():
            msg = await ctx.send('\N{THINKING FACE}')
            await asyncio.sleep(random.uniform(0.25, 1))
            await msg.edit(content=random.choice(choices.split(';')))

    @commands.group(aliases=['rand'], invoke_without_command=True)
    async def random(self, ctx, lo: number, hi: number=None, dist='range'):
        """Super-command for all the random commands. Or generates a value between lo and hi given"""
        distribution = _available_distributions.get(dist)
        if distribution is None:
            raise commands.BadArgument(f"{dist} is not a distribution for random numbers")

        if hi is None:
            lo, hi = 0, lo
        result = distribution(lo, hi)

        msg = await ctx.send(f"Your random {distribution.__name__} number between is...")
        await asyncio.sleep(random.uniform(0, 1))
        await msg.edit(msg.content + f'**{result}!!**')

    @random.command(aliases=['dists'])
    async def distributions(self, ctx):
        """Shows all the distributions one can use for the random command"""
        dists = ', '.join(_available_distributions)
        await ctx.send(f"Available random distributions```\n{dists}```")

    @random.command(aliases=['dice'], enabled=False)
    async def diceroll(self, ctx, amt):
        """Rolls a certain number of dice"""
        fmt = "{} " * amt
        await ctx.send(fmt.format(*[random.randint(1, 6) for _ in range(amt)]))

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
    async def build(self, ctx, points : int=33):
        """Gives you a random build to try out

        If points is not provided, it defaults to a max-level build (33)"""
        await ctx.send(self._build_str(points))

    @random.command()
    async def smasher(self, ctx, points : int=33):
        """Gives you a random build for the Smasher branch to try out

        If points is not provided, it defaults to a max-level build (33)"""
        await ctx.send(self._build_str(points, True))

    def _class(self):
        return random.choice(self.bot.get_cog("WRA").all_tanks() or _back_up_tanks)

    @random.command(name="class")
    async def class_(self, ctx):
        """Gives you a random class to play"""
        await ctx.send(self._class())

    @random.command()
    async def tank(self, ctx, points : int=33):
        """Gives you a random build AND class to play

        If points is not provided, it defaults to a max-level build (33)"""
        cwass = self._class()
        build = self._build_str(points, cwass in SMASHERS)
        await ctx.send(f'{build} {cwass}')

    @random.command(aliases=['color'])
    async def colour(self, ctx):
        """Generates a random colo(u)r."""
        colour = discord.Colour(random.randint(0, 0xFFFFFF))
        rgb = colour.to_rgb()
        h, s, v = colorsys.rgb_to_hsv(*(v / 255 for v in rgb))
        hsv = h * 360, s * 100, v * 100

        colour_embed = (discord.Embed(title=str(colour), colour=colour)
                       .add_field(name="RGB", value='%d, %d, %d' % rgb)
                       .add_field(name="HSV", value='%.03f, %.03f, %.03f' % hsv)
                       )
        if webcolors:
            colour_embed.description = get_colour_name(rgb)
        await ctx.send(embed=colour_embed)

    @commands.cooldown(rate=10, per=5, type=commands.BucketType.guild)
    @random.command()
    async def uuid(self, ctx):
        """Generates a random uuid.

        Because of potential abuse, this commands has a 5 second cooldown
        """
        await ctx.send(uuid.uuid4())

    @random.command(aliases=['pw'])
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
        await ctx.send(password)

    @random.command()
    async def maze(self, ctx, w: int=5, h: int=5):
        """Generates a random maze"""
        maze = '\n'.join(_make_maze(w, h))
        try:
            await ctx.send(f"```\n{maze}```")
        except discord.HTTPException:
            await ctx.send(f"The maze you've generated (**{w}** by **{h}**) is too large")

def setup(bot):
    bot.add_cog(RNG(bot))
