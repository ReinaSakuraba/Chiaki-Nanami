import asyncio
import discord
import re

from .utils import checks
from .utils.database import Database
from .utils.aitertools import AIterable

from collections import defaultdict
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
    's': 1,                'sec': 1,
    'm': 60,               'min': 60, 
    'h': 60 * 60,          'hr': 60 * 60,
    'd': 60 * 60 * 24,     'day': 60 * 60 * 24,
    'w': 60 * 60 * 24 * 7, 'wk': 60 * 60 * 24 * 7,
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

def _case_embed(cases, action, target, actioner, reason, 
                color: discord.Colour, time=None):
    number = len(cases) + 1
    if time is None:
        time = datetime.now()
    title = "Case/Action Log/Something #{}".format(number)
    description = "{} {}".format(target.mention, action)
    avatar_url = target.avatar_url or target.default_avatar_url
    embed = discord.Embed(title=title, description=description,
                          color=color, timestamp=time)
    embed.set_thumbnail(url=avatar_url)
    embed.add_field(name="Moderator", value=actioner.mention)
    embed.add_field(name="Reason", value=reason) 
    return embed

class SlowmodeUpdater:
    __slots__ = ('seconds', 'users_last_message')
    def __init__(self):
        self.seconds = 0
        self.users_last_message = {}
        
MOD_FOLDER = "mod/"
class Moderator:
    def __init__(self, bot):
        self.bot = bot
        self.muted_roles_db = Database.from_json(MOD_FOLDER + "mutedroles.json")
        self.muted_users_db = Database.from_json(MOD_FOLDER + "mutedusers.json",
                                                 factory_not_top_tier=dict)
        self.cases_db = Database.from_json(MOD_FOLDER + "case-action.json",
                                           factory_not_top_tier=dict)
        self.slowmodes = defaultdict(SlowmodeUpdater)
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

    async def _make_case(self, action, msg, target, reason, color):
        server_cases = self.cases_db[msg.server]
        if not server_cases:
            print("no server_cases")
            return
        case_channel = self.bot.get_channel(server_cases.get("channel"))
        if case_channel is None:
            print("no case_channel")
            return
        case_embed = _case_embed(server_cases["cases"],
                                 action, target, msg.author,
                                 reason, color
                                 )
        server_cases["cases"].append(case_embed.to_dict())
        await self.bot.send_message(msg.channel, embed=case_embed)
        

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
                    if (now - last_time).seconds >= status["duration"]:
                        member = server.get_member(member_id)
                        await self._unmute(member)
                        
            # Must end the blocking or else the program will hang      
            await asyncio.sleep(0)
         
    # TODO   
    @commands.command(pass_context=True)
    @checks.admin_or_permissions(manage_messages=True)
    async def slowmode(self, ctx, secs: int=10):
        """Puts the channel in slowmode"""
        channel = ctx.message.channel
        self.slowmodes[channel].seconds = secs
        fmt = ("{.mention} is now in slow mode, probably."
               " You must wait {} seconds before you can send another message")
        await self.bot.say(fmt.format(channel, secs))
        
    @commands.command(pass_context=True, aliases=['slowoff'])
    @checks.admin_or_permissions(manage_messages=True)
    async def slowmodeoff(self, ctx):
        """Puts the channel in slowmode"""
        channel = ctx.message.channel
        self.slowmodes[channel].seconds = 0
        fmt = "{.mention} is no longer in slow mode, I think. :sweat_smile:"
        await self.bot.say(fmt.format(channel))
    
    async def update_slowmode(self, message):
        author = message.author
        channel = message.channel
        slowmode = self.slowmodes[channel]
        message_time = message.timestamp
        last_time = slowmode.users_last_message.get(author)
        if last_time is None or (message_time - last_time).seconds >= slowmode.seconds:
            slowmode.users_last_message[author] = message_time
            await asyncio.sleep(0)
        else:
            await self.bot.delete_message(message)
        
                    
    #TODO: Make separate commands from number vs member
    @commands.command(pass_context=True, no_pm=True)
    @checks.admin_or_permissions(manage_messages=True)
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
                check=lambda m: m.author.id == user.id
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

    # Because of the reason parameter
    # If you don't want to mention the member
    # You must put quotes around the member name if there are spaces
    # eg mute "makoto naegi#0001" Too Hopeful
    # This also applies to kick, ban, and unmute
    @commands.command(pass_context=True, no_pm=True)
    @checks.admin_or_permissions(manage_roles=True)
    async def mute(self, ctx, member : discord.Member, durations : str, *, reason : str="None"):
        """Mutes a user for a given duration and reason

        Because of the reason parameter, if you don't want to mention the user 
        you must put the user in quotes if you're gonna put a reason
        Usage: mute @komaeda 5h666s Stop talking about hope please"""
        message = ctx.message
        server = message.server
        
        print(durations)
##        if not message.mentions:
##            return
##        member = message.mentions[0]
        await self._mute(member)
        server_mutes = self.muted_users_db[server]
        duration = _full_duration(durations)
        data = {
            "time": str(datetime.now()),
            "duration": duration,
            "reason": reason,
            }
        
        server_mutes[member.id] = data
        
        await self.bot.send_message(
            message.channel,
            ("{} has now been muted by {} "
             "for {} seconds, Reason: {}").format(member.mention,
                                                  message.author.mention,
                                                  duration, reason)
            )
        await self._make_case("was muted", message, member, reason, 0)
        #self._set_perms_for_mute(member, False, True)

    async def on_member_join(self, member):
        # Prevent mute evasion by leaving the server and coming back
        server = member.server
        if member.id in self.muted_users_db[server]:
            await self._mute(member)
        
    @commands.command(pass_context=True, no_pm=True)
    @checks.admin_or_permissions(manage_roles=True)
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
    @checks.admin_or_permissions(kick_members=True)
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
    @checks.admin_or_permissions(kick_members=True)
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

    @commands.group(pass_context=True, no_pm=True)
    @checks.admin_or_permissions()
    async def caseset(self, ctx):
        pass

    @caseset.command(pass_context=True, no_pm=True)
    @checks.admin_or_permissions()
    async def log(self, ctx):
        server_cases = self.cases_db[ctx.message.server]
        server_cases["channel"] = ctx.message.channel.id
        server_cases["cases"] = []
        await self.bot.say("Cases will now be made on this channel")
        
    async def on_message(self, message):
        await self.update_slowmode(message)
    

def setup(bot):
    bot.add_cog(Moderator(bot))
