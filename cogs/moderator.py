import asyncio
import discord
import re

from .utils import checks
from .utils.database import Database
from .utils.aitertools import AIterable

from collections import Counter, defaultdict
from discord.ext import commands
from datetime import datetime, date

def _pairwise(it):
    iterit = iter(it)
    return zip(iterit, iterit)

def _nwise(it, n=2):
    iterit = iter(it)
    return zip(*([iterit] * n))

def parse_int(s):
    try:
        return int(s)
    except ValueError:
        return None


DURATION_MULTIPLIERS = {
    's': 1,                  'sec': 1,
    'm': 60,                 'min': 60,
    'h': 60 * 60,            'hr': 60 * 60,
    'd': 60 * 60 * 24,       'day': 60 * 60 * 24,
    'w': 60 * 60 * 24 * 7,   'wk': 60 * 60 * 24 * 7,
    'y': 60 * 60 * 24 * 365, 'yr': 60 * 60 * 24 * 365,
}

def _parse_duration(duration, unit):
    duration = parse_int(duration)
    print(unit)
    if duration is None:
        return 0
    return duration * DURATION_MULTIPLIERS.get(unit, 60)

def _full_duration(durations):
    durations = re.split(r"(\d+[\.]?\d*)", durations)[1:]
    print(durations, list(_pairwise(durations)))
    return sum(_parse_duration(d, u) for d, u in _pairwise(durations))

def _full_succinct_duration(secs):
	m, s = divmod(secs, 60)
	h, m = divmod(m, 60)
	d, h = divmod(h, 24)
	w, d = divmod(d, 7)
	unit_list = [(w, 'weeks'), (d, 'days'), (h, 'hours'), (m, 'mins'), (s, 'seconds')]
	return ', '.join(f"{n} {u}" for n, u in unit_list if n)

def _case_embed(num, action, target, actioner, reason,
                color: discord.Colour, time=None):
    if time is None:
        time = datetime.now()
    title = f"Case/Action Log/Something #{num}"
    description = "{} {}".format(target.mention, action)
    avatar_url = target.avatar_url or target.default_avatar_url
    embed = discord.Embed(title=title, description=description,
                          color=color, timestamp=time)
    embed.set_thumbnail(url=avatar_url)
    embed.add_field(name="Moderator", value=actioner.mention)
    embed.add_field(name="Reason", value=reason, inline=False)
    return embed

# Ignore this random classes
class SlowmodeUpdater:
    __slots__ = ('seconds', 'users_last_message')
    def __init__(self):
        self.seconds = 0
        self.users_last_message = {}

    def reset(self):
        self.seconds = 0
        self.users_last_message.clear()

class ServerWarn:
    __slots__ = ('warn_limit', 'users_last_message')
    def __init__(self):
        self.warn_limit = 2
        self.users_warns = Counter()


MOD_FOLDER = "mod/"
class Moderator:
    """Moderator-related commands

    Most of these require the Moderator role (defined by =>addmodrole) or the right permissions
    """
    def __init__(self, bot):
        self.bot = bot
        self.muted_roles_db = Database.from_json(MOD_FOLDER + "mutedroles.json")
        self.muted_users_db = Database.from_json(MOD_FOLDER + "mutedusers.json",
                                                 default_factory=dict)
        self.cases_db = Database.from_json(MOD_FOLDER + "case-action.json",
                                           default_factory=dict)
        self.slowmodes = defaultdict(SlowmodeUpdater)
        self.slowonlys = defaultdict(dict)
        server_warn_default = lambda: {"warn_limit": 2, "users_warns" : Counter()}
        self.warns_db = Database.from_json(MOD_FOLDER + "warns.json",
                                           default_factory=server_warn_default)
        self.bot.loop.create_task(self.update_muted_users())

    async def _create_muted_role(self, server):
        overwrite = discord.PermissionOverwrite(send_messages=False,
                                                manage_messages=False)
        role = await self.bot.create_role(server=server,
                                          name='Chiaki-Muted',
                                          color=discord.Colour(0xFF0000))
        for channel in server.channels:
            await self.bot.edit_channel_permissions(channel, role, overwrite)
        return role

    async def _get_muted_role(self, server):
        try:
            role_id = self.muted_roles_db[server]
        except KeyError:
            print("creating new role")
            role = await self._create_muted_role(server)
            self.muted_roles_db[server] = role.id
            return role
        else:
            role = discord.utils.get(server.roles, id=role_id)
            return role or self._get_muted_role(server)

    async def _make_case(self, action, msg, target, reason, color, **kwargs):
        server_cases = self.cases_db[msg.server]
        if not server_cases:
            print("no server_cases")
            return
        case_channel = self.bot.get_channel(server_cases.get("channel"))
        if case_channel is None:
            print("no case_channel")
            return
        case_embed = _case_embed(server_cases["case_num"],
                                 action, target, msg.author,
                                 reason, color
                                 )
        if kwargs.get('mod'):
            (case_embed.set_field_at(1, name="Duration", value=kwargs.get("duration"))
                       .add_field(name="Reason", value=reason, inline=False))
        server_cases["case_num"] += 1
        await self.bot.send_message(case_channel, embed=case_embed)


    async def _mute(self, member):
        muted_role = await self._get_muted_role(member.server)
        await self.bot.add_roles(member, muted_role)

    async def _unmute(self, member):
        muted_role = await self._get_muted_role(member.server)
        await self.bot.remove_roles(member, muted_role)
        try:
            self.muted_users_db[member.server].pop(member.id)
        except KeyError:
            pass
        #await self._set_perms_for_mute(member, False, True)

    async def update_muted_users(self):
        await self.bot.wait_until_ready()
        time = datetime.strptime
        while not self.bot.is_closed:
            for server_id, muted_members in list(self.muted_users_db.items()):
                server = self.bot.get_server(server_id)

                for member_id, status in list(muted_members.items()):
                    now = datetime.now()
                    last_time = time(status["time"], "%Y-%m-%d %H:%M:%S.%f")

                    # yay for hax
                    if (now - last_time).total_seconds() >= status["duration"]:
                        member = server.get_member(member_id)
                        await self._unmute(member)

            # Must end the blocking or else the program will hang
            await asyncio.sleep(0)

    # TODO
    @commands.command(pass_context=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def slowmode(self, ctx, secs: int=10):
        """Puts the channel in slowmode"""
        channel = ctx.message.channel
        self.slowmodes[channel].seconds = secs
        fmt = ("{.mention} is now in slow mode, probably."
               " You must wait {} seconds before you can send another message")
        await self.bot.say(fmt.format(channel, secs))

    @commands.command(pass_context=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def slowonly(self, ctx, user: discord.Member, secs: int):
        """Puts a user in a certain channel in slowmode"""
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
        try:
            self.slowonlys[channel].pop(user)
        except KeyError:
            await self.bot.say(f"{user} was never in slowmode, I think")
        else:
            await self.bot.say(f"{user} is no longer in slow mode, I think. :sweat_smile:")

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

    #TODO: Make separate commands from number vs member
    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def clear(self, ctx, *, rest: str):
        msg = ctx.message
        number = parse_int(rest)
        #Is it a number?
        if number is None:
            #Maybe it's a user?
            try:
                user = commands.UserConverter(ctx, rest).convert()
            except commands.BadArgument:
                return
            deleted = await self._clear(msg.channel, check=lambda m: m.author.id == user.id)
        else:
            if number < 1:
                await self.bot.say("How can I delete {number} messages...?")
                return
            deleted = await self._clear(msg.channel, limit=min(number, 1000) + 1)
        deleted_count = len(deleted) - 1
        is_plural = 's'*(deleted_count != 1)
        await self.bot.say(
            f"Deleted {deleted_count} message{is_plural} successfully!",
            delete_after=1.5
        )

    async def clear_num(self, ctx, num):
        pass

    # Because of the reason parameter
    # If you don't want to mention the member
    # You must put quotes around the member name if there are spaces
    # eg mute "makoto naegi#0001" Too Hopeful
    # This also applies to kick, ban, and unmute

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions()
    async def warn(self, ctx, member: discord.Member, *, reason: str="None"):
        server = ctx.message.server
        author = ctx.message.author
        server_warns = self.warns_db[server]

        await self.bot.say(("Hey, {0}, {1} has warned you for: {2}. Please stop."
                           ).format(member.mention, author.mention, reason))
        await self.bot.send_message(member, f"{author} from {server} has warned you for {reason}.")

        server_warns["users_warns"][member.id] += 1
        if server_warns["users_warns"][member.id] >= server_warns["warn_limit"]:
            await ctx.invoke(self.mute, member, "30", reason=reason)
            case_str = "was muted automatically because they were warned too much"
        else:
            case_str = "was warned"
        await self._make_case(case_str, ctx.message, member, reason, 0xFF8000)


    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_roles=True)
    async def mute(self, ctx, member : discord.Member, durations : str, *, reason : str="None"):
        """Mutes a user for a given duration and reason

        Because of the reason parameter, if you don't want to mention the user
        you must put the user in quotes if you're gonna put a reason
        Usage: mute @komaeda 5h666s Stop talking about hope please"""
        message = ctx.message
        server = message.server

        print(durations)
        await self._mute(member)
        server_mutes = self.muted_users_db[server]
        duration = _full_duration(durations)
        data = {
            "time": str(datetime.now()),
            "duration": duration,
            "reason": reason,
            }

        server_mutes[member.id] = data
        full_succinct_duration = _full_succinct_duration(duration)
        await self.bot.send_message(
            message.channel,
            ("{} has now been muted by {} "
             "for {}. Reason: {}").format(member.mention,
                                          message.author.mention,
                                          full_succinct_duration, reason)
            )
        await self._make_case("was muted :no_mouth:", message, member, 
                             reason, 0, mod=True, duration=full_succinct_duration)
        #self._set_perms_for_mute(member, False, True)

    async def on_member_join(self, member):
        # Prevent mute evasion by leaving the server and coming back
        server = member.server
        if member.id in self.muted_users_db[server]:
            await self._mute(member)

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_roles=True)
    async def unmute(self, ctx, member : discord.Member, *, reason : str="None"):
        """Unmutes a user

        Because of the reason parameter, if you don't want to mention the user
        you must put the user in quotes if you're gonna put a reason
        """

        await self._unmute(member)
        await self.bot.send_message(
            ctx.message.channel,
            "{} can speak again, probably".format(member.mention)
            )

    # Most of the time mention is used...
    # Which is why using solely the name won't work here
    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str="idk no one put a reason"):
        """Kicks a user (obviously)

        Because of the reason parameter, if you don't want to mention the user
        you must put the user in quotes if you're gonna put a reason
        e.g. kick "Junko Enoshima#6666" Too much despair
        """
        try:
            await self.bot.kick(member)
        except discord.Forbidden:
            await self.bot.say("I don't have the permission to kick members, I think.")
        except discord.HTTPException:
            await self.bot.say("Kicking failed. I don't know what happened.")
        else:
            await self.bot.say("Done, please don't make me do that again.")
            await self._make_case("was kicked :boot:", ctx.message,
                                  member, reason, 0xFF0000)

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(kick_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str):
        """Bans a user (obviously)

        Because of the reason parameter, if you don't want to mention the user
        you must put the user in quotes if you're gonna put a reason
        e.g. ban "Junko Enoshima#6666" Too much despair
        """
        try:
            await self.bot.ban(member)
        except discord.Forbidden:
            await self.bot.say("I don't have the permission to ban members, I think.")
        except discord.HTTPException:
            await self.bot.say("Banning failed. I don't know what happened.")
        else:
            await self.bot.say("Done, please don't make me do that again.")
            await self._make_case("was banned :hammer:", ctx.message,
                                  member, reason, 0xAA1111)

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(kick_members=True)
    async def unban(self, ctx, member: discord.Member, *, reason: str):
        """Unbans a user (obviously)

        Because of the reason parameter, if you don't want to mention the user
        you must put the user in quotes if you're gonna put a reason
        e.g. ban "Junko Enoshima#6666" Too much despair
        """
        try:
            await self.bot.unban(ctx.message.server, member)
        except discord.Forbidden:
            await self.bot.say("I don't have the permission to unban members, I think.")
        except discord.HTTPException:
            await self.bot.say("Unbanning failed. I don't know what happened.")
        else:
            await self.bot.say(f"Done. What did {member.mention} do to get banned in the first place?")
            await self._make_case("was unbanned :slight_smile:", ctx.message,
                                  member, reason, 0xAA1111)

    @commands.group(pass_context=True, no_pm=True)
    @checks.admin_or_permissions()
    async def caseset(self, ctx):
        pass

    @caseset.command(pass_context=True, no_pm=True)
    @checks.admin_or_permissions()
    async def log(self, ctx, *, channel: discord.Channel=None):
        if channel is None:
            channel = ctx.message.channel
        server_cases = self.cases_db[ctx.message.server]
        server_cases["channel"] = channel.id
        if "case_num" not in server_cases:
            server_cases["case_num"] = 1
        await self.bot.say(f"Cases will now be made on channel {channel.mention}")

    @caseset.command(pass_context=True, no_pm=True)
    @checks.admin_or_permissions()
    async def reset(self, ctx):
        server_cases = self.cases_db[ctx.message.server]
        server_cases["case_num"] = 1
        await self.bot.say(f"Cases has been reset back to 1")

    async def on_message(self, message):
        await self.update_slowmode(message)
        await self.update_slowonly(message)


def setup(bot):
    bot.add_cog(Moderator(bot))
