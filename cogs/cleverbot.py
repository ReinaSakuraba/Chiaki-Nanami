import asyncio

from collections import defaultdict
from discord.ext import commands

from .utils import checks, cleverbot
from .utils.database import Database

class Cleverbot:
    def __init__(self, bot):
        self.bot = bot
        self.sessions = {}
        self.server_disables = Database.from_json("cleverbotdisabled.json")
        self.server_disables.setdefault("disabled", [])

    def _get_session(self, channel):
        if channel not in self.sessions:
            cb = cleverbot.Cleverbot(f"test-{channel.id}",
                                     session=self.bot.http.session,
                                     loop=self.bot.loop)
            self.sessions[channel] = cb
            return cb
        return self.sessions[channel]

    @commands.command(pass_context=True, hidden=True, aliases=['scb'])
    @checks.admin_or_permissions(administrator=True)
    async def setcleverbot(self, ctx, mode: bool):
        """Enables or disables Cleverbot for this server"""
        # In the future when I make a permissions system this will be redone
        server_id = ctx.message.server.id
        disabled = self.server_disables["disabled"]
        if mode:
            if server_id not in disabled:
                await self.bot.say("Cleverbot has already been enabled on this server.")
            else:
                disabled.remove(server_id)
                await self.bot.say("Cleverbot has been re-enabled on this server.")
        else:
            if server_id in disabled:
                await self.bot.say("Cleverbot has already been disabled on this server.")
            else:
                disabled.append(server_id)
                await self.bot.say("Cleverbot has been disabled on this server.")
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

        session = self._get_session(channel)
        await self.bot.send_typing(channel)
        await asyncio.sleep(0.5)
        response = await session.ask(content)
        await self.bot.send_message(channel, f"{author.mention} {response}")

def setup(bot):
    bot.add_cog(Cleverbot(bot))
