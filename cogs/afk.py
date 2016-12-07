import discord

from discord.ext import commands
from .utils.transformdict import IDAbleDict
from .utils.database import Database, DB_FILE_PATH

AFK_FILE_NAME = "afk.json"
class AFK:
    def __init__(self, bot):
        self.bot = bot
        self.db = Database.from_json(DB_FILE_PATH + AFK_FILE_NAME)

    def _set_afk(self, server : discord.Server,
                 member : discord.Member, msg : str):
        if self.db.get_storage(server) is None:
            self.db[server] = IDAbleDict()
        self.db[server][member] = msg

    def _del_afk(self, server : discord.Server, member : discord.Member):
        if self.db.get_storage(server) is None:
            self.db[server] = IDAbleDict()
        try:
            self.db[server].pop(member)
        except KeyError:
            return False
        else:
            return True
        
    @commands.command(pass_context=True)
    async def afk(self, ctx, *, msg : str=None):
        server = ctx.message.server
        member = ctx.message.author
        if msg is None:
            if self._del_afk(server, member):
                await self.bot.say("You are no longer AFK")
        else:
            self._set_afk(server, member, msg)
            await self.bot.say("You are AFK")

            
    async def on_message(self, message):
        if message.author == self.bot.user:
            return
        mentions = set(message.mentions)
        server = message.server
        if not mentions:
            return
        fmt = "{} is afk, proabably.\nI think this is their message:\n{}"
        for user in mentions:
            try:
                user_afk_message = self.db[server][user]
            except KeyError:
                continue
            else:
                afk_message = fmt.format(user.mention, user_afk_message)
                await self.bot.send_message(message.channel, afk_message)
                
def setup(bot):
    afk = AFK(bot)
    bot.add_listener(afk.on_message, "on_message")
    bot.add_cog(afk)
