import asyncio
import discord
from discord.ext import commands
import re

def parse_int(s):
    try:
        return int(s)
    except ValueError:
        return None

DURATION_MULTIPLIERS = {
    's': 1,            'sec': 1,
    'm': 60,           'min': 60, 
    'h': 60 * 60,      'hr': 60 * 60,
    'd': 60 * 60 * 24, 'day': 60 * 60 * 24,
}

def _parse_duration(duration):
    _, num, unit, *rest = re.split(r"(\d+)", duration)
    return time * DURATION_MULTIPLIERS.get(unit, 1)

class Moderator:
    def __init__(self, bot):
        self.bot = bot

    async def _set_perms_for_mute(self, member, allowsm, denysm):
        allow, deny = message.channel.overwrites_for(member)
        allow.send_messages = allowsm
        deny.send_messages = denysm
        await self.bot.edit_channel_permissions(
            message.channel,
            member,
            allow=allow,
            deny=deny
            )
        
    @commands.command(pass_context=True)
    async def clear(self, ctx, *rest):
        number = min(parse_int(rest[0]), 1000)
        msg = ctx.message
        #Is it a number?
        if number < 1 or number is None:
            #Maybe it's a user?
            if not msg.mentions:
                return
            user = msg.mentions[0]
            if not user:
                return
            del_msg = await self.bot.purge_from(
                msg.channel,
                check=lambda m: m.author.id == user.id or m == message
                )
        else:
            del_msg = await self.bot.purge_from(msg.channel, limit=number+1)
        message_number = len(del_msg) - 1
        confirm_message = await self.bot.send_message(
            msg.channel,   
            "`Deleted {} message{}!`".format(
                message_number,
                "s"*(message_number != 1)
            )
        )
        await asyncio.sleep(1.5)
        await self.bot.delete_message(confirm_message)

    @commands.command(pass_context=True)
    async def mute(self, ctx, user : discord.Member, duration : str, *reason : str):
        """Mutes a user for a given duration and reason

        Usage: mute @komaeda 666s Stop talking about hope please"""
        if not ctx.message.mentions:
            return
        member = ctx.message.mentions[0]
        self._set_perms_for_mute(member, False, True)
        await self.bot.send_message(
            message.channel,
            "{} has now been muted for {}, Reason: {}".format(user.mention,
                                                              duration,
                                                              ' '.join(reason))
            )
        await asyncio.sleep(_parse_duration(duration))
        await self._unmute(user)
        
    @commands.command(pass_context=True)
    async def unmute(self, ctx, user : discord.Member):
        if not ctx.message.mentions:
            return
        member = ctx.message.mentions[0]

        self._unmute(member)
        await self.bot.send_message(
            message.channel,
            "{} can speak again, probably".format(user.mention)
            )

    async def _unmute(self, member):
        await self._set_perms_for_mute(member, False, True)

def setup(bot):
    bot.add_cog(Moderator(bot))
