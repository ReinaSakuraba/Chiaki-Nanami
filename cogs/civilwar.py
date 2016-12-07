import discord
from discord.ext import commands
import random
        
class CivilWar:
    """Managing civil wars"""
    def __init__(self, bot):
        self.bot = bot
        self.name = ""
        self.cwrole = None
        self.num_teams = self.max_players = 0
        self.teams = {}
        self.players = []

    def _started(self):
        return self.cwrole is not None
    
    @commands.group(pass_context=True, aliases=['cw'])
    async def civilwar(self, ctx):
        pass
    
    @commands.group(pass_context=True, aliases=['cw'])
    async def setteams(self, ctx, *teams : str):
        teams = set(teams)
        if not self._started():
            return self.bot.say("You can't set any teams without a civil war!")
        self.num_teams = len(teams)
        for team in teams:
            t = discord.Role(

    @civilwar.command(pass_context=True)
    async def start(self, ctx, name, max_players=20):
        if self._started():
            return self.bot.say("A civil war has already been registered for this server")
        self.cwrole = discord.Role(name)

    @civilwar.command(aliases=['srclr'])
    async def setrolecolor(self, color : discord.Colour):
        if not self._started():
            return self.bot.say("There is no role to set color to")
        self.cwrole.color = color

    @civilwar.command(aliases=['srclr'])
    async def setteamcolor(self, team : discord.Role, color : discord.Colour):
        if not self._started():
            return self.bot.say("There is no team to set color to")
        elif team not in self.teams:
            return self.bot.say("Team {} doesn't exist")
        team.color = color

    @civilwar.command(pass_context=True)
    async def register(self, ctx):
        user = ctx.message.author
        if self.cwrole in user.roles:
            return self.bot.say("{} is already registered!")
        user.roles.append(self.cwrole)

    @civilwar.command(pass_context=True)
    async def unregister(self, ctx):
        user = ctx.message.author
        if self.cwrole not in user.roles:
            return self.bot.say("{} isn't even registered!")
        user.roles.remove(self.cwrole)

    @civilwar.command(pass_context=True)
    async def end(self, ctx):
        ctx.message.server._remove_role(self.role)
        await self.bot.say("Civil war {} ended".format(self.name))  
    
def setup(bot):
    bot.add_cog(DiepioCivilWar(bot))
