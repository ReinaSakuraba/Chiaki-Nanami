import contextlib
import discord
import enum

from collections import defaultdict, deque
from datetime import datetime
from discord.ext import commands

from .utils import errors
from .utils.compat import user_color
from .utils.database import Database
from .utils.misc import duration_units


class AFKConfig(enum.IntEnum):
    MAX_MESSAGES = 5
    MAX_INTERVAL = 10 * 60

_default_afk_config = {
    'send_afk_message': True,
}

class AFK:
    def __init__(self, bot):
        self.bot = bot
        self.afks = Database("afk.json")
        self.afk_configs = Database('afk-config.json', default_factory=_default_afk_config.copy)
        self.user_message_queue = defaultdict(deque)

    async def _get_afk_embed(self, member):
        message = self.afks.get(member)
        if message is None:
            return None

        avatar = member.avatar_url_as(format=None)
        colour = await user_color(member)
        title = f"{member.display_name} is AFK"

        embed = (discord.Embed(description=message, colour=colour)
                .set_author(name=title, icon_url=avatar)
                .set_footer(text=f"ID: {member.id}")
                )

        with contextlib.suppress(IndexError):
            embed.timestamp = self.user_message_queue[member.id][-1]
        return embed


    def _has_messaged_too_much(self, author):
        message_queue = self.user_message_queue[author.id]
        if len(message_queue) <= AFKConfig.MAX_MESSAGES:
            return False

        delta = (message_queue.popleft() - datetime.now()).total_seconds()
        return delta >= AFKConfig.MAX_INTERVAL

    def _remove_afk(self, author):
        old_message = self.afks.pop(author, None)
        self.user_message_queue[author.id].clear()
        return old_message is not None

    def _afk_messages_enabled(self, server):
        return self.afk_configs[server]['send_afk_message']

    @commands.command()
    async def afk(self, ctx, *, message: str=None):
        """Sets your AFK message"""
        member = ctx.author
        if message is None:
            msg = "You are no longer AFK" if self._remove_afk(member) else "You need a message... I think."
            await ctx.send(msg)
        else:
            self.afks[member] = message
            await ctx.send("You are AFK")

    @commands.command(name='afksay')
    @commands.has_permissions(manage_guild=True)
    async def afk_say(self, ctx, send_afk_message: bool):
        """Sets whether or not I should say the user's AFK message when mentioned.

        This is useful in places where the AFK message might be extremely spammy.
        This is server-wide at the moment
        """
        self.afk_configs[ctx.guild]['send_afk_message'] = send_afk_message
        await ctx.send('\N{THUMBS UP SIGN}')

    async def check_user_message(self, message):
        author, server = message.author, message.guild
        if author.id == self.bot.user.id:
            return

        if author not in self.afks:
            return

        self.user_message_queue[author.id].append(message.created_at)
        if self._has_messaged_too_much(author):
            self._remove_afk(author)
            await message.channel.send(f"{author.mention}, you are no longer AFK as you have messaged "
                                       f"{AFKConfig.MAX_MESSAGES} times in less than "
                                       f"{duration_units(AFKConfig.MAX_INTERVAL)}.")

    async def check_user_mention(self, message):
        if not self._afk_messages_enabled(message.guild):
            return

        if message.author.id == self.bot.user.id:
            return

        for user in message.mentions:
            afk_embed = await self._get_afk_embed(user)
            if afk_embed is not None:
                 await message.channel.send(embed=afk_embed)

    async def on_message(self, message):
        await self.check_user_message(message)
        await self.check_user_mention(message)

def setup(bot):
    bot.add_cog(AFK(bot))
