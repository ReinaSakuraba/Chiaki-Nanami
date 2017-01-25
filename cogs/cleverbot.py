from discord.ext import commands

from .utils import checks, cleverbot
from .utils.database import Database
from .utils.misc import convert_to_bool

class Cleverbot:
    def __init__(self, bot):
        self.bot = bot
        self.cb_session = cleverbot.Cleverbot('test', session=bot.http.session, loop=bot.loop)
        self.server_disables = Database.from_json("cleverbotdisabled.json")
        self.server_disables.setdefault("disabled", [])

    @commands.command(pass_context=True, hidden=True, aliases=['scb'])
    @checks.admin_or_permissions(administrator=True)
    async def setcleverbot(self, ctx, mode):
        """Enables or disabled Cleverbot for this server"""
        # In the future when I make a permissions system this will be redone
        print(mode)
        mode = convert_to_bool(mode)
        server_id = ctx.message.server.id
        disabled = self.server_disables["disabled"]
        if mode:
            if server_id not in disabled:
                await self.bot.say("Cleverbot has already been enabled on this server")
            else:
                disabled.remove(server_id)
                await self.bot.say("Cleverbot has been re-enabled on this server")
        else:
            if server_id in disabled:
                await self.bot.say("Cleverbot has already been disabled on this server")
            else:
                disabled.append(server_id)
                await self.bot.say("Cleverbot has been disnabled on this server")
            pass

    async def on_message(self, message):
        bot_user = self.bot.user
        author = message.author
        content = message.content
        channel = message.channel
        server = message.server

        if server and server.id in self.server_disables["disabled"]:
            return
        if author == bot_user:  # prevent circular cleverbotting
            return
        mentions = [bot_user.mention]
        if server:
            mentions.append(server.me.mention)
        for mention in mentions:
            if content.startswith(mention):
                content = content.replace(mention, '', 1)
                break
        else:
            return

        await self.bot.send_typing(channel)
        response = await self.cb_session.ask(content)
        await self.bot.send_message(channel, f"{author.mention} {response}")

def setup(bot):
    bot.add_cog(Cleverbot(bot))
