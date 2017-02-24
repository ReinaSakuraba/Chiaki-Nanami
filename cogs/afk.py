import discord

from discord.ext import commands

from .utils import checks
from .utils.compat import user_color
from .utils.database import Database
from .utils.transformdict import IDAbleDict

_afk_default = { "limit": 5, "messages": {}}

class AFK:
    def __init__(self, bot):
        self.bot = bot
        self.db = Database.from_json("afk.json", default_factory=_afk_default.copy)

    def _set_afk(self, server, member, msg: str):
        server_afk = self.db[server]
        result = member in server_afk
        server_afk["messages"][member] = msg
        return result

    def _del_afk(self, server, member):
        try:
            self.db[server]["messages"].pop(member)
        except KeyError:
            return False
        else:
            return True
            
    async def _afk_embed(self, member, msg):
        avatar = member.avatar_url or member.default_avatar_url
        colour = await user_color(member)
        title = f"{member.display_name} is AFK"
        desc = f"{member} is AFK"
        return (discord.Embed(title=title, description=desc, colour=colour)
               .set_thumbnail(url=avatar)
               .add_field(name="Message", value=msg)
               .set_footer(text=f"ID: {member.id}")
               )
        
    @commands.command(pass_context=True)
    async def afk(self, ctx, *, msg: str=None):
        server = ctx.message.server
        member = ctx.message.author.id
        if msg is None:
            if self._del_afk(server, member):
                await self.bot.say("You are no longer AFK")
        else:
            self._set_afk(server, member, msg)
            await self.bot.say("You are AFK")    
            
    @commands.command(pass_context=True)
    @checks.is_admin()
    async def afklimit(self, ctx, limit: int):
        
        self.db[server]["limit"] = limit
            
    async def on_message(self, message):
        if message.author == self.bot.user:
            return
        mentions = set(message.mentions)
        server = message.server
        if not mentions:
            return
        for user in mentions:
            user_afk_message = self.db[server].get(user)
            if user_afk_message is None:
                continue
            msg = f"{user.mention} is AFK, proabably.\nI think this is their message:"
            afk_embed = await self._afk_embed(user, user_afk_message)
            await self.bot.send_message(message.channel, embed=afk_embed)
                
def setup(bot):
    bot.add_cog(AFK(bot))
