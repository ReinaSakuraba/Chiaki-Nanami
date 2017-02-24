import discord
import json
import operator
import random

from discord.ext import commands

from .utils import errors

class OtherStuffs:
    def __init__(self, bot):
        self.bot = bot
        with open(r'data\copypastas.json', encoding='utf-8') as f:
            self.copypastas = json.load(f)

    def _get_pastas(self, idx):
        try:
            return self.copypastas[idx]
        except IndexError:
            raise errors.ResultsNotFound(f"There is no category with an index of {idx}")

    @commands.group(pass_context=True, invoke_without_command=True)
    async def copypasta(self, ctx, idx: int, *, name=None):
        """Returns a copypasta from an index and name"""

        copypasta_group = self._get_pastas(idx)
        category, copypastas = copypasta_group['category'], copypasta_group['copypastas']
        if name is None:
            name = random.choice(list(copypastas.keys()))
        try:
            pasta = copypastas[name.title()]
        except KeyError:
            raise errors.InvalidUserArgument(f"Category \"{category}\" doesn't have pasta called \"{name}\"")
        embed = discord.Embed(title=f"{category} {name}", description=pasta, colour=0x00FF00)
        await self.bot.say(embed=embed)

    @copypasta.command(name="listgroups", pass_context=True)
    async def copypasta_listgroups(self, ctx):
        embed = discord.Embed(title="All the categories (and their indices)")
        for i, pasta in enumerate(map(operator.itemgetter('category'), self.copypastas)):
            embed.add_field(name=str(i), value=pasta)
        await self.bot.say(embed=embed)

    @copypasta.command(name="listpastas", pass_context=True)
    async def copypasta_listpastas(self, ctx, idx: int):
        group = self._get_pastas(idx)
        category, copypastas = group['category'], group['copypastas']
        embed = discord.Embed(title=category)
        for pasta in copypastas:
            embed.add_field(name=pasta, value='\u200b')
        await self.bot.say(embed=embed)

def setup(bot):
    bot.add_cog(OtherStuffs(bot))