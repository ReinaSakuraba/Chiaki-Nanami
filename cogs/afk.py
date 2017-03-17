import discord

from collections import defaultdict, deque
from datetime import datetime
from discord.ext import commands

from .utils import checks, errors
from .utils.compat import user_color
from .utils.converter import duration
from .utils.database import Database
from .utils.misc import duration_units

_afk_default = { 'limit': 5, 'max_timeout': 5 * 60}

class AFK:
    def __init__(self, bot):
        self.bot = bot
        self.afk_db = Database("afk.json")
        self.user_message_queue = defaultdict(deque)

    async def _afk_embed(self, member, msg):
        avatar = member.avatar_url_as(format=None)
        colour = await user_color(member)
        title = f"{member.display_name} is AFK"
        desc = f"{member} is AFK"
        return (discord.Embed(title=title, description=desc, colour=colour)
               .set_thumbnail(url=avatar)
               .add_field(name="Message", value=msg)
               .set_footer(text=f"ID: {member.id}")
               )

    def _is_timed_out(self, server, author):
        settings, message_queue = self.afk_db[server], self.user_message_queue[author]
        print(settings)
        if len(message_queue) <= settings['limit']:
            return False
        return (message_queue.popleft() - datetime.now()).total_seconds() >= settings['max_timeout']

    def _remove_afk(self, author):
        old_message = self.afk_db['messages'].pop(str(author.id), None)
        self.user_message_queue[author].clear()
        return old_message is not None

    @commands.command()
    async def afk(self, ctx, *, message: str=None):
        """Sets your AFK message"""
        server = ctx.guild
        member = ctx.author
        if message is None:
            msg = "You are no longer AFK" if self._remove_afk(member) else "You need a message... I think."
            await ctx.send(msg)
        else:
            self.afk_db['messages'][str(member.id)] = message
            await ctx.send("You are AFK")

    @commands.group()
    @checks.is_admin()
    async def afkset(self, ctx):
        pass

    @afkset.command(name='limit')
    async def set_limit(self, ctx, limit: int):
        """Sets your number of messages required for an AFK user to be out of AFK."""
        if limit <= 0:
            raise errors.InvalidUserArgument("limit is too low, the mininum limit is 1, I think.")
        self.afk_db[ctx.guild]['limit'] = limit
        await ctx.send(f"Okay. Users now have **{limit}** before being kicked out of AFK, probably.")

    @afkset.command(name='timeout')
    async def set_timeout(self, ctx, time: duration):
        """Sets the maximum amount of time between the user's first message and the last."""
        settings = self.afk_db[ctx.guild]
        settings['max_timeout'] = time
        await ctx.send(f"Okay. If a user posts {settings['limit']} messages within {duration_units(time)} "
                        "they will be kicked out of AFK, I think.")

    async def check_user_message(self, message):
        author, server = message.author, message.guild
        if author.id == self.bot.user.id:
            return

        author_id = str(author.id)
        if author_id not in self.afk_db['messages']:
            return

        self.user_message_queue[author].append(message.created_at)
        if self._is_timed_out(server, author):
            self._remove_afk(author)
            await message.channel.send(f"{author.mention}, you are no longer AFK as you have messaged "
                                       f"{settings['limit']} times in less than {duration_units(settings['max_timeout'])}.")

    async def check_user_mention(self, message):
        if message.author.id == self.bot.user.id:
            return

        for user in message.mentions:
            user_afk_message = self.afk_db['messages'].get(str(user.id))
            if user_afk_message is None:
                continue
            afk_message = f"{user.mention} is AFK, proabably.\nI think this is their message:"
            afk_embed = await self._afk_embed(user, user_afk_message)
            await message.channel.send(afk_message, embed=afk_embed)

    async def on_message(self, message):
        self.afk_db.setdefault(message.guild, _afk_default.copy())
        await self.check_user_message(message)
        await self.check_user_mention(message)

def setup(bot):
    bot.add_cog(AFK(bot))
