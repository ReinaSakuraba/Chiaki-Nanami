import asyncio
import copy
import discord
import enum
import os
import re

from .utils import checks
from .utils.database import Database
from .utils.errors import InvalidUserArgument
from .utils.aitertools import aiterable
from .utils.misc import duration_units, nice_time, parse_int, try_async_call, usage

from collections import Counter, defaultdict, namedtuple
from discord.ext import commands
from datetime import datetime
from functools import wraps

DURATION_MULTIPLIERS = {
    's': 1,                  'sec': 1,
    'm': 60,                 'min': 60,
    'h': 60 * 60,            'hr': 60 * 60,
    'd': 60 * 60 * 24,       'day': 60 * 60 * 24,
    'w': 60 * 60 * 24 * 7,   'wk': 60 * 60 * 24 * 7,
    'y': 60 * 60 * 24 * 365, 'yr': 60 * 60 * 24 * 365,
}

def pairwise(iterable):
    it = iter(iterable)
    return zip(*[it, it])

def _parse_time(string, unit='m'):
    duration = parse_int(string)
    if duration is None:
        return 0
    return duration * DURATION_MULTIPLIERS.get(unit, 60)

def _full_time(strings):
    durations = re.split(r"(\d+[\.]?\d*)", strings)[1:]
    return sum(_parse_time(d, u) for d, u in pairwise(durations))

class ModAction(enum.Enum):
    warn = ("was warned :warning:", 0xFF8000, True)
    warn_excess = ("was muted because they were warned too much", 0xFF8000, True)
    mute = ("was muted :no_mouth:", 0x000000, True)
    unmute = ("was unmuted :speaking_head:", 0x000000, True)
    kick = ("was kicked :boot:", 0xFF0000, False)
    temp_ban = ("was temporarily banned :hammer_pick:", 0xCC0000, True)
    ban = ("was banned :hammer:", 0xAA1111, False)
    unban = ("was unbanned :slight_smile:", 0x33FF00, False)

    def __init__(self, msg, colour, include_duration):
        self.msg = msg
        self.colour = colour
        self.include_duration = include_duration

DEFAULT_REASON = "No reason..."

def _case_embed(num, action, target, msg, reason):
    actioner = msg.author
    title = f"Case/Action Log/Something #{num}"
    footer = f"Command executed in #{msg.channel}"
    description = f"{target.mention} {action.msg}"
    avatar_url = target.avatar_url or target.default_avatar_url

    return (discord.Embed(title=title, description=description, color=action.colour, timestamp=msg.timestamp)
           .set_thumbnail(url=avatar_url)
           .add_field(name="Moderator", value=actioner.mention)
           .add_field(name="Reason", value=reason, inline=False)
           .set_footer(text=footer))

# Ignore this random classes
class SlowmodeUpdater:
    __slots__ = ('seconds', 'users_last_message')
    def __init__(self):
        self.seconds = 0
        self.users_last_message = {}

    def reset(self):
        self.seconds = 0
        self.users_last_message.clear()

_user_requires_quotes_due_to_reason = """

Because of the reason parameter, if you don't want to mention the user
you must put the user in quotes if you're gonna put a reason.
"""
def requires_quotes_for_user(func):
    func.__doc__ += _user_requires_quotes_due_to_reason
    return func

def mod_file(filename):
    return os.path.join('mod', filename)

_server_warn_default = {"warn_limit": 2, "users_warns": Counter()}

class Moderator:
    """Moderator-related commands

    Most of these require the Moderator role (defined by 'addmodrole')
    or the right permissions.
    """
    def __init__(self, bot):
        self.bot = bot
        self.muted_roles_db = Database.from_json(mod_file("mutedroles.json"))
        self.muted_users_db = Database.from_json(mod_file("mutedusers.json"), default_factory=dict)
        self.temp_bans_db = Database.from_json(mod_file("tempbans.json"), default_factory=dict)
        self.cases_db = Database.from_json(mod_file("case-action.json"), default_factory=dict)
        self.slowmodes = defaultdict(SlowmodeUpdater)
        self.slowonlys = defaultdict(dict)
        self.warns_db = Database.from_json(mod_file("warns.json"), default_factory=_server_warn_default.copy)
        self.bot.loop.create_task(self.update())

    async def _try_action(self, func, on_success=None, on_forbidden=None, on_http_exc=None):
        alts = [
            (discord.Forbidden, on_forbidden),
            (discord.HTTPException, on_http_exc),
            ]
        result = await try_async_call(func, on_success=on_success, exception_alts=alts)
        await self.bot.say(result.message)

    async def _regen_muted_permissions(self, role):
        overwrite = discord.PermissionOverwrite(send_messages=False,
                                                add_reactions=False,
                                                manage_messages=False)
        for channel in role.server.channels:
            await self.bot.edit_channel_permissions(channel, role, overwrite)

    async def _create_muted_role(self, server):
        role = await self.bot.create_role(server=server, name='Chiaki-Muted',
                                          color=discord.Colour(0xFF0000))
        await self._regen_muted_permissions(role)
        return role

    async def _get_muted_role(self, server):
        async def default_muted(server):
            role = await self._create_muted_role(server)
            self.muted_roles_db[server] = role.id
            # Explicit dump to make sure the roles get updated
            await self.muted_roles_db.dump()
            return role
        try:
            role_id = self.muted_roles_db[server]
        except KeyError:
            return await default_muted(server)
        else:
            role = discord.utils.get(server.roles, id=role_id)
            # Role could've been deleted, so we have to account for that.
            return role or await default_muted(server)

    async def _make_case(self, action, msg, target, reason, duration=None):
        server_cases = self.cases_db[msg.server]
        if not server_cases:
            print("no server_cases")
            return
        case_channel = self.bot.get_channel(server_cases.get("channel"))
        if case_channel is None:
            print("no case_channel")
            return

        case_embed = _case_embed(server_cases["case_num"], action, target, msg, reason)
        if action.include_duration:
            case_embed.set_field_at(1, name="Duration", value=duration)
            case_embed.add_field(name="Reason", value=reason, inline=False)
        server_cases["case_num"] += 1
        await self.bot.send_message(case_channel, embed=case_embed)

    async def _clear(self, channel, *, limit=100, check=None):
        try:
            deleted = await self.bot.purge_from(channel, limit=limit, check=check)
        except discord.Forbidden:
            await self.bot.say("I don't have the right perms to clear messages.")
            return None
        except discord.HTTPException:
            await self.bot.say("Deleting the messages failed, somehow.")
            return None
        else:
            return deleted

    async def _mute(self, member):
        muted_role = await self._get_muted_role(member.server)
        await self.bot.add_roles(member, muted_role)

    async def _unmute(self, member):
        muted_role = await self._get_muted_role(member.server)
        await self.bot.remove_roles(member, muted_role)
        self.muted_users_db[member.server].pop(member.id, None)

    async def _update_db(self, db, action):
        async for server_id, affected_members in aiterable(list(db.items())):
            server = self.bot.get_server(server_id)

            async for member_id, status in aiterable(list(affected_members.items())):
                now = datetime.now()
                last_time = datetime.strptime(status["time"], "%Y-%m-%d %H:%M:%S.%f")

                # yay for hax
                if (now - last_time).total_seconds() >= status["duration"]:
                    member = server.get_member(member_id)
                    await action(member, status)

    async def update(self):
        await self.bot.wait_until_ready()
        update_db = self._update_db
        # let's hope async lambdas become a thing
        async def unmute(member, status):
            await self._unmute(member)
        async def unban(member, status):
            server = self.bot.get_server(status["server"])
            member = await self.bot.get_user_info(status["user"])
            await self.bot.unban(server, member)
            invite = await self.bot.create_invite(server)
            msg = f"You have been unbanned from {server}, please be on your best behaviour from now on..."
            await self.bot.send_message(member, f"{msg}\n{invite}")

        while not self.bot.is_closed:
            await update_db(self.muted_users_db, unmute)
            await update_db(self.temp_bans_db, unban)
            await asyncio.sleep(0)

    @commands.command(pass_context=True)
    @checks.mod_or_permissions(manage_messages=True)
    @usage('slowmode 100')
    async def slowmode(self, ctx, secs: int=10):
        """Puts the channel in slowmode"""
        if secs <= 0:
            raise InvalidUserArgument("Seconds must be positive, unless you want me to back in time...")

        channel = ctx.message.channel
        self.slowmodes[channel].seconds = secs
        fmt = (f"{channel.mention} is now in slow mode, probably."
               f" You must wait {secs} seconds before you can send another message")
        await self.bot.say(fmt)

    @commands.command(pass_context=True)
    @checks.mod_or_permissions(manage_messages=True)
    @usage('slowonly Salt')
    async def slowonly(self, ctx, user: discord.Member, secs: int):
        """Puts a user in a certain channel in slowmode"""
        if secs <= 0:
            raise errors.InvalidUserArgument(f"How can I put someone in slowmode for {secs} seconds...?")

        channel = ctx.message.channel
        slowonly_channel = self.slowonlys[channel]

        user_dict = {
            "duration": secs,
            "last_time": datetime.now()
            }
        slowonly_channel[user] = user_dict

        fmt = (f"{channel.mention} is now in slow mode for {user.mention}, probably."
               f"They must wait {secs} seconds before they can send another message")
        await self.bot.say(fmt)

    @commands.command(pass_context=True, aliases=['slowoff'])
    @checks.mod_or_permissions(manage_messages=True)
    async def slowmodeoff(self, ctx):
        """Puts the channel out of slowmode"""
        channel = ctx.message.channel
        self.slowmodes[channel].reset()
        fmt = "{.mention} is no longer in slow mode, I think. :sweat_smile:"
        await self.bot.say(fmt.format(channel))

    @commands.command(pass_context=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def slowonlyoff(self, ctx, user: discord.Member):
        """Puts a user in a certain channel out of slowmode"""
        channel = ctx.message.channel
        result = try_call(lambda: self.slowonlys[channel].pop(user),
                          on_success=f"{user} is no longer in slow mode, I think. :sweat_smile:",
                          exception_alts={KeyError: f"{user} was never in slowmode, I think"})

    async def update_slowmode(self, message):
        author = message.author
        channel = message.channel
        slowmode = self.slowmodes[channel]
        message_time = message.timestamp
        last_time = slowmode.users_last_message.get(author, None)
        if last_time is None or (message_time - last_time).total_seconds() >= slowmode.seconds:
            slowmode.users_last_message[author] = message_time
            await asyncio.sleep(0)
        else:
            await self.bot.delete_message(message)

    async def update_slowonly(self, message):
        author = message.author
        channel = message.channel
        slowonly_user = self.slowonlys[channel].get(author)
        if slowonly_user is None:
            return

        message_time = message.timestamp
        last_time = slowonly_user["last_time"]
        if (message_time - last_time).total_seconds() >= slowonly_user["duration"]:
            slowonly_user["last_time"] = message_time
            await asyncio.sleep(0)
        else:
            await self.bot.delete_message(message)

    @commands.command(pass_context=True, no_pm=True, aliases=['clr'])
    @checks.mod_or_permissions(manage_messages=True)
    @usage('clear 50', 'clear Nadeko')
    async def clear(self, ctx, *, arg: str):
        """Mass-deletes some messages

        If the argument specified is a number, it deletes that many messages.
        If the argument specified is a user, it deletes any messages from that user in the last 100 messages.
        """
        msg = ctx.message
        number = parse_int(arg)
        #Is it a number?
        if number is None:
            #Maybe it's a user?
            user = commands.UserConverter(ctx, arg).convert()
            deleted = await self._clear(msg.channel, check=lambda m: m.author.id == user.id)
        else:
            if number < 1:
                raise InvalidUserArgument("How can I delete {number} messages...?")
            deleted = await self._clear(msg.channel, limit=min(number, 1000) + 1)
        if deleted is None:
            return
        deleted_count = len(deleted) - 1
        is_plural = 's'*(deleted_count != 1)
        await self.bot.say(
            f"Deleted {deleted_count} message{is_plural} successfully!",
            delete_after=1.5
        )

    # Because of the reason parameter
    # If you don't want to mention the member
    # You must put quotes around the member name if there are spaces
    # eg mute "makoto naegi#0001" Too Hopeful
    # This also applies to kick, ban, and unmute

    @commands.command(pass_context=True, no_pm=True)
    @checks.is_mod()
    @requires_quotes_for_user
    @usage('warn "Chiaki Nanami" Sleeping too much.')
    async def warn(self, ctx, member: discord.Member, *, reason):
        """Warns a user.

        If a user was warned already, then it mutes the user for 30 mins.
        """
        server = ctx.message.server
        author = ctx.message.author
        server_warns = self.warns_db[server]

        await self.bot.say(("Hey, {0}, {1} has warned you for: \"{2}\". Please stop."
                           ).format(member.mention, author.mention, reason))
        await self.bot.send_message(member, f"{author} from {server} has warned you for {reason}.")

        server_warns["users_warns"][member.id] += 1
        if server_warns["users_warns"][member.id] >= server_warns["warn_limit"]:
            await ctx.invoke(self.mute, member, "30", reason=reason)
            action = ModAction.warn_excess
        else:
            action = ModAction.warn
        await self._make_case(action, ctx.message, member, reason)


    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_roles=True)
    @requires_quotes_for_user
    @usage('mute @komaeda 5h666s Stop talking about hope please')
    async def mute(self, ctx, member: discord.Member, duration: _full_time, *, reason: str=DEFAULT_REASON):
        """Mutes a user for a given duration and reason"""
        message = ctx.message
        server = message.server

        await self._mute(member)
        server_mutes = self.muted_users_db[server]
        data = {
            "time": str(datetime.now()),
            "duration": duration,
            "reason": reason,
            }

        server_mutes[member.id] = data
        units = duration_units(duration)
        await self.bot.send_message(message.channel,
            f"{member.mention} has now been muted by {message.author.mention} "
            f"for {units}. Reason: {reason}")
        await self._make_case(ModAction.mute, message, member, reason, duration=units)
        #self._set_perms_for_mute(member, False, True)

    async def on_member_join(self, member):
        # Prevent mute evasion by leaving the server and coming back
        server = member.server
        if member.id in self.muted_users_db[server]:
            await self._mute(member)

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_roles=True)
    @requires_quotes_for_user
    @usage('unmute "Makoto Naegi" We need more hope.')
    async def unmute(self, ctx, member: discord.Member, *, reason="None"):
        """Unmutes a user"""
        await self._unmute(member)
        await self.bot.say(f"{member.mention} can speak again, probably.")
        await self._make_case(ModAction.unmute, ctx.message, member, reason)

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(kick_members=True)
    @requires_quotes_for_user
    @usage('kick "Junko Enoshima#6666" Too much despair')
    async def kick(self, ctx, member: discord.Member, *, reason: str="idk no one put a reason"):
        """Kicks a user (obviously)"""
        if member == ctx.message.author:
            raise InvalidUserArgument("You can't kick yourself, I think.")
        try:
            await self.bot.kick(member)
        except discord.Forbidden:
            await self.bot.say("I don't have the permission to kick members, I think.")
        except discord.HTTPException:
            await self.bot.say("Kicking failed. I don't know what happened.")
        else:
            await self.bot.say("Done, please don't make me do that again.")
            await self._make_case(ModAction.kick, ctx.message, member, reason)

    @commands.command(pass_context=True, no_pm=True, disabled=True)
    @checks.mod_or_permissions(ban_members=True)
    @requires_quotes_for_user
    @usage('tempban "Junko Enoshima#6666" Too much despair')
    async def tempban(self, ctx, member: discord.Member, durations: _full_time, *, reason: str):
        """Temporarily bans a user (obviously)"""
        server_temp_bans = self.temp_bans_db[member.server]
        data = {
            "server": member.server.id,
            "user": member.id,
            "time": str(datetime.now()),
            "duration": duration,
            "reason": reason,
            }

        server_temp_bans[member.id] = data
        duration_units = duration_units(duration)
        try:
            await self.bot.ban(member)
        except discord.Forbidden:
            await self.bot.say("I don't have the permission to ban members, I think.")
        except discord.HTTPException:
            await self.bot.say("Banning failed. I don't know what happened.")
        else:
            await self.bot.say("Done, please don't make me do that again.")
            await self._make_case(ModAction.temp_ban, ctx.message, member, reason, duration_units)

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(ban_members=True)
    @usage('ban "Junko Enoshima#6666" Too much despair')
    @requires_quotes_for_user
    async def ban(self, ctx, member: discord.Member, *, reason: str):
        """Bans a user (obviously)"""
        if member == ctx.message.author:
            raise InvalidUserArgument("You can't ban yourself, I think.")
        try:
            await self.bot.ban(member)
        except discord.Forbidden:
            await self.bot.say("I don't have the permission to ban members, I think.")
        except discord.HTTPException:
            await self.bot.say("Banning failed. I don't know what happened.")
        else:
            await self.bot.say("Done, please don't make me do that again.")
            await self._make_case(ModAction.ban, ctx.message, member, reason)

    @commands.command(pass_context=True, no_pm=True, disabled=True)
    @checks.is_owner()
    async def unban(self, ctx, member: discord.User, *, reason: str):
        """Unbans a user (obviously)

        As of right now, this command doesn't work, as the user is effectively removed from the server upon banning.
        """
        try:
            await self.bot.unban(ctx.message.server, member)
        except discord.Forbidden:
            await self.bot.say("I don't have the permission to unban members, I think.")
        except discord.HTTPException:
            await self.bot.say("Unbanning failed. I don't know what happened.")
        else:
            await self.bot.say(f"Done. What did {member.mention} do to get banned in the first place?")
            await self._make_case(ModAction.unban, ctx.message, member, reason)

    @commands.group(pass_context=True, no_pm=True)
    @checks.is_admin()
    async def caseset(self, ctx):
        pass

    @caseset.command(pass_context=True, no_pm=True)
    @checks.is_admin()
    async def log(self, ctx, *, channel: discord.Channel=None):
        if channel is None:
            channel = ctx.message.channel
        server_cases = self.cases_db[ctx.message.server]
        server_cases["channel"] = channel.id
        server_cases.setdefault("case_num", 1)
        await self.bot.say(f"Cases will now be made on channel {channel.mention}")

    @caseset.command(pass_context=True, no_pm=True)
    @checks.is_admin()
    async def reset(self, ctx):
        server_cases = self.cases_db[ctx.message.server]
        server_cases["case_num"] = 1
        await self.bot.say(f"Cases has been reset back to 1")

    async def on_message(self, message):
        await self.update_slowmode(message)
        await self.update_slowonly(message)

def setup(bot):
    bot.add_cog(Moderator(bot), "Mod")
