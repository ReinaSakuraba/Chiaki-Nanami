import discord
import hashlib
import json
import operator
import functools
import random

from collections import namedtuple
from discord.ext import commands

from .utils import errors
from .utils.converter import item_converter

with open(r'data\copypastas.json', encoding='utf-8') as f:
    _copypastas = json.load(f)

UserInfoNums = namedtuple('UserInfo', ['id', 'discriminator', 'avatar', 'created_at'])
UserInfoNums.rating = property(lambda self: sum(self))

def _user_info(user):
    return UserInfoNums(user.id,
                        int(user.avatar or user.default_avatar.value, 16),
                        int(hashlib.md5(str(user).encode('utf-8')).hexdigest(), 16),
                        user.created_at.timestamp()
                        )

_special_pairs = {}


@functools.lru_cache(maxsize=2 ** 20)
def _calculate_compatibilty(info1, info2):
    id_pair = frozenset((info1, info2))
    if id_pair in _special_pairs:
        return _special_pairs[id_pair]

    # User inputted themself as the second argument
    if len(id_pair) == 1:
        return 0

    r = random.randrange
    return (round((info1.rating + info2.rating + r(10000))) >> r(25, 100)) % 100

class OtherStuffs:
    def __init__(self, bot):
        self.bot = bot

    def __unload(self):
        # unload the cache if necessary...
        _calculate_compatibilty.cache_clear()
        pass

    @commands.group(invoke_without_command=True)
    async def copypasta(self, ctx, copy_pasta: item_converter(_copypastas, key=int), *, name=None):
        """Returns a copypasta from an index and name"""
        category, copypastas = copy_pasta['category'], copy_pasta['copypastas']
        if name is None:
            name = random.choice(list(copypastas.keys()))
        try:
            pasta = copypastas[name.title()]
        except KeyError:
            raise errors.InvalidUserArgument(f"Category \"{category}\" doesn't have pasta called \"{name}\"")
        embed = discord.Embed(title=f"{category} {name}", description=pasta, colour=0x00FF00)
        await ctx.send(embed=embed)

    @copypasta.command(name="listgroups")
    async def copypasta_listgroups(self, ctx):
        embed = discord.Embed(title="All the categories (and their indices)")
        for i, pasta in enumerate(map(operator.itemgetter('category'), self.copypastas)):
            embed.add_field(name=str(i), value=pasta)
        await ctx.send(embed=embed)

    @copypasta.command(name="listpastas")
    async def copypasta_listpastas(self, ctx, pastas: item_converter(_copypastas, key=int)):
        category, copypastas = pastas['category'], pastas['copypastas']
        embed = discord.Embed(title=category)
        for pasta in copypastas:
            embed.add_field(name=pasta, value='\u200b')
        await ctx.send(embed=embed)

    @commands.command(usage=['rjt#2336, Nelyn#7808', 'Danny#0007 Jake#0001'])
    async def ship(self, ctx, user1: discord.Member, user2: discord.Member=None):
        """Determines if two users are compatible with one another.

        If only one user is specified, it determines *your* compatibility with that user.
        """
        if user2 is None:
            user1, user2 = ctx.author, user1

        # In order to keep the modification that comes with changing avatar / name
        # we have to use a tuple of these stats.
        # Using the actual User object won't work if we're gonna take advantage of functools.lru_cache
        # Because a change in avatar or username won't create a new result
        rating = _calculate_compatibilty(_user_info(user1), _user_info(user1))
        ship_embed = (discord.Embed(title='Ship', description=f'{user1.mention} x {user2.mention}?', colour=0xff80aa)
                     .add_field(name='Test', value=str(rating))
                     )
        await ctx.send(embed=ship_embed)

def setup(bot):
    bot.add_cog(OtherStuffs(bot))