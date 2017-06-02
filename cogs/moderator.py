import asyncio
import contextlib
import discord
import functools
import json
import os

from collections import defaultdict, deque, namedtuple
from datetime import datetime
from discord.ext import commands
from operator import itemgetter

from .utils import checks, errors
from .utils.context_managers import redirect_exception  
from .utils.converter import duration, in_, union
from .utils.database import Database
from .utils.json_serializers import (
    DatetimeEncoder, DequeEncoder, decode_datetime, decode_deque, union_decoder
    )
from .utils.misc import duration_units, emoji_url, ordinal

_default_warn_config = {
    'timeout': 60 * 15,
    'punishments': {
        '2': {
            'punish': 'mute',
            'duration': 60 * 10,
        }
    },
    'members': {},
}

ModAction = namedtuple('ModAction', 'repr emoji colour')
mod_action_types = {
    'warn'         : ModAction('warned', '\N{WARNING SIGN}', 0xFFAA00),
    'mute'         : ModAction('muted', '\N{ZIPPER-MOUTH FACE}', 0),
    'kick'         : ModAction('kicked', '\N{WOMANS BOOTS}', 0xFF0000),
    'softban'      : ModAction('soft banned', '\N{BIOHAZARD SIGN}', 0xF08000),
    'tempban'      : ModAction('temporarily banned', '\N{ALARM CLOCK}', 0xA00000),
    'ban'          : ModAction('banned', '\N{HAMMER}', 0x800000),
    'unban'        : ModAction('unbanned', '\N{HAMMER}', 0x00FF00),
    'special_role' : ModAction('unbanned', '\N{HAMMER}', 0x00FF00),
}
_restricted_warn_punishments = {'softban', 'unban', 'warn'}

ModCase = namedtuple('ModCase', 'type mod user reason')
WarnEntry = namedtuple('WarnEntry', 'time reason')

def _mod_file(filename): return os.path.join('mod', filename)
_member_key = '({0.guild.id}, {0.id})'.format


class WarnEncoder(DequeEncoder, DatetimeEncoder):
    pass

warn_hook = union_decoder(decode_deque, decode_datetime)

def _rreplace(s, old, new, count=1 ):
    li = s.rsplit(old, count)  
    return new.join(li)

# TODO:
# - implement anti-raid protocol
# - implement antispam
# - implement mention-spam
class Moderator:
    def __init__(self, bot):
        self.bot = bot

        # Current statuses
        self.current_slowmodes = defaultdict(dict)
        self.current_slowonlys = {}

        # Databases / Configs
        self.guild_warn_config = Database(_mod_file('warns.json'), default_factory=_default_warn_config.copy,
            encoder=WarnEncoder, object_hook=warn_hook)
        self.raids = Database(_mod_file('raids.json'))
        self.cases = Database(_mod_file('cases.json'), default_factory=dict)
        self.mutes = Database(_mod_file('mutes.json'), default_factory=dict)
        self.tempbans = Database(_mod_file('tempbans.json'), default_factory=dict)

        self.slowmodes = Database(_mod_file('slowmode.json'))
        self.slowmode_limits = self.slowmodes.setdefault('general', {})
        self.slowonly_limits = self.slowmodes.setdefault('members', {})
        self.slowmodes = {}
        self.slowonlys = {}

        self.muted_roles = Database(_mod_file('muted_roles.json'), default_factory=None)

        self.bot.loop.create_task(self._resume_mutes_and_tempbans())

    @staticmethod
    async def _default_temp_task(member, data, action):
        timedelta = datetime.utcnow() - datetime.strptime(data['time'], "%Y-%m-%d %H:%M:%S.%f")
        await asyncio.sleep(data['duration'] - timedelta.total_seconds())
        await action(member)

    async def _resume_mutes_and_tempbans(self):
        await self.bot.wait_until_ready()

        def server_pair_helper(db):
            for server, member_status in list(db.items()):
                for member_id, status in list(member_status.items()):
                    yield self.bot.get_guild(int(server)), int(member_id), status

        for server, member_id, status in server_pair_helper(self.mutes):
            member = server.get_member(member_id)
            self.bot.loop.create_task(self._default_temp_task(member, status, self._do_unmute))

        # We have to repeat the loop for each database 
        # due to how each mod tool and user_getter is used
        for server, user_id, status in server_pair_helper(self.tempbans):
            unban = functools.partial(self._attempt_unban, server)
            self.bot.loop.create_task(self._default_temp_task(user_id, status, unban))

    @staticmethod
    def _case_embed(num, ctx, case, duration=None):
        type_, mod, user, reason = case
        case_type = mod_action_types[type_]
        avatar_url = user.avatar_url_as(format=None)
        bot_avatar = ctx.bot.user.avatar_url_as(format=None)

        auto_punished = getattr(ctx, 'auto_punished', False)
        if auto_punished:
            mod = ctx.bot.user

        duration_string = f' for {duration_units(duration)}' if duration is not None else ''
        action_field = f'{"Auto-" * auto_punished}{case_type.repr.title()}{duration_string} by {mod}'
        reason = reason or 'No reason. Please enter one.'

        return (discord.Embed(color=case_type.colour, timestamp=ctx.message.created_at)
               .set_author(name=f"Case #{num}", icon_url=emoji_url(case_type.emoji))
               .set_thumbnail(url=avatar_url)
               .add_field(name="User", value=str(user))
               .add_field(name="Action", value=action_field, inline=False)
               .add_field(name="Reason", value=reason, inline=False)
               .set_footer(text=f'ID: {user.id}', icon_url=bot_avatar)
               )

    async def _send_case(self, ctx, case, duration=None):
        server_cases = self.cases[ctx.guild]
        case_channel = self.bot.get_channel(server_cases.get('case_channel'))
        if case_channel is None:
            return

        cases = server_cases.setdefault('cases', [])
        case_embed = self._case_embed(len(cases) + 1, ctx, case, duration)

        msg = await case_channel.send(embed=case_embed)

        case = {
            'message_id': msg.id,
            'channel_id': case_channel.id,
            'type': case.type,
            'mod': case.mod.id,
            'user': case.user.id,
            'reason': case.reason,
        }
        cases.append(case)

    async def update_slowmode(self, message):
        if not isinstance(message.channel, discord.abc.GuildChannel):
            # slowmode is pointless is DMs
            return

        for mode, limit_key, key in [('slowmode', str(message.channel.id), message.channel ),
                                     ('slowonly', _member_key(message.author), message.guild)]:
            # order is important here
            # the slowmode limits are persistent, but the current slowmodes are not
            limit = getattr(self, f'{mode}_limits').get(limit_key)
            if limit is None:
                continue

            current = getattr(self, f'{mode}s').setdefault(key, {})
            last_time = current.get(message.author)
            if last_time is None or (message.created_at - last_time).total_seconds() >= limit:
                current[message.author] = message.created_at
            else:
                await message.delete()
                break

    @commands.command()
    @checks.mod_or_permissions(manage_messages=True)
    async def slowmode(self, ctx, duration: duration, member: discord.Member=None):
        """Puts a channel in slowmode

        An optional member argument can be provided. If it is provided,
        the user is put in slowmode for the entire server.
        """
        async def adder(db, limit_key, key, pronoun, actual_key=None):
            if actual_key is None:
                actual_key = key

            limits = getattr(self, f'{db}_limits')
            if limit_key in limits:
                return await ctx.send(f"{key.mention} is already in slowmode!") 
            limits[limit_key] = duration

            getattr(self, f'{db}s').setdefault(actual_key, {})
            await ctx.send(f"{key.mention} is now on slowmode! {pronoun} must wait {duration} "
                            "seconds before they can post another message.")

        if member is not None:
            await adder('slowonly', _member_key(member), member, 'They', actual_key=member.server)
        else:
            await adder('slowmode', str(ctx.channel.id), ctx.channel, 'Everyone')

    @commands.command(aliases=['slowoff'])
    @checks.mod_or_permissions(manage_messages=True)
    async def slowmodeoff(self, ctx, member: discord.Member=None):
        async def popper(currents, limits, limit_key, key):
            with redirect_exception((KeyError, f"{key.mention} was never in slowmode...")):
                del currents[key]
                del limits[limit_key]
            await ctx.send(f"{key.mention} is no longer in slowmode!")

        if member is not None:
            await popper(self.slowonlys.get(message.guild, {}), self.slowonly_limits,
                         _member_key(member), member)
        else:
            await popper(self.slowmodes, self.slowmode_limits, 
                         str(ctx.channel.id), ctx.channel)

    @commands.command(aliases=['clr'])
    @checks.mod_or_permissions(manage_messages=True)
    async def clear(self, ctx, num_or_user: union(int, discord.Member)=None):
        """Clears some messages in a channels

        The argument can either be a user or a number.
        If it's a number it deletes *up to* that many messages.
        If it's a user, it deletes any message by that user up to the last 100 messages.
        If no argument was specified, it deletes my messages.
        """
        async def attempt_clear(*, limit=100, check=None):
            with redirect_exception((discord.Forbidden, "I need the Manage Messages perm to clear messages."),
                                    (discord.HTTPException, "Deleting the messages failed, somehow.")):
                return await ctx.channel.purge(limit=limit, check=check)

        if isinstance(num_or_user, int):
            if num_or_user < 1:
                raise errors.InvalidUserArgument(f"How can I delete {number} messages...?")
            deleted = await attempt_clear(limit=min(num_or_user, 1000) + 1)
        elif isinstance(num_or_user, discord.Member):
            deleted = await attempt_clear(check=lambda m: m.author.id == user.id)
        else:
            deleted = await attempt_clear(check=lambda m: m.author.id == bot.user.id)

        deleted_count = len(deleted) - 1
        is_plural = 's'*(deleted_count != 1)
        await ctx.send(f"Deleted {deleted_count} message{is_plural} successfully!", delete_after=1.5)

    @commands.command()
    @checks.is_mod()
    async def warn(self, ctx, member: discord.Member, *, reason: str):
        """Warns a user (obviously)"""
        author, current_time = ctx.author, ctx.message.created_at
        warn_config = self.guild_warn_config[ctx.guild]
        warn_queue = warn_config['members'].setdefault(str(member.id), deque())
        warn_queue.append((current_time, author.id, reason))
        current_warn_num = len(warn_queue)

        def check_warn_num():
            if current_warn_num >= max(map(int, punishments)):
                warn_queue.popleft()

        async def default_warn():
            warn_embed = (discord.Embed(colour=0xffaa00, description=reason)
                         .set_author(name=str(author), icon_url=author.avatar_url_as(format=None))
                         )
            await member.send(f"You have been warned by {author} for the followng reason:", embed=warn_embed)
            await member.send(f"This is your {ordinal(current_warn_num)} warning.")
            await ctx.send(f"\N{WARNING SIGN} Warned {member.mention} successfully!")
            await self._send_case(ctx, ModCase(type='warn', mod=ctx.author, user=member, reason=reason))
            check_warn_num()

        punishments = warn_config['punishments']
        punishment = punishments.get(str(current_warn_num))
        if punishment is None:
            return await default_warn()

        # warn is too old, ignore it.
        if (current_time - warn_queue[0][0]).total_seconds() > warn_config['warn_timeout']:
            return await default_warn()

        # Auto-punish the user
        args = member,
        if punishment['duration'] is not None:
            args += punishment['duration'],
        ctx.auto_punished = True

        punish = punishment['punish']
        await ctx.invoke(getattr(self, punish), *args, reason=reason + f'\n({ordinal(current_warn_num)} warning)')
        check_warn_num()

    @commands.command(name='clearwarns')
    @checks.is_mod()
    async def clear_warns(self, ctx, member: discord.Member):
        self.guild_warn_config[ctx.guild]['members'][str(member.id)].clear()
        await ctx.send(f"{member}'s warns have been reset!")

    @staticmethod
    def _check_user(ctx, member):
        if ctx.author.id == member.id:
            raise errors.InvalidUserArgument("Please don't hurt yourself. :(")
        if member.id == ctx.bot.user.id:
            raise errors.InvalidUserArgument("Hey, what did I do??")

    async def _create_muted_role(self, server):
        role = await server.create_role(name='Chiaki-Muted', colour=discord.Colour.red())
        await self._regen_muted_role_perms(role, *server.channels)

        self.muted_roles[str(server.id)] = role.id
        # Explicit dump to make sure the roles get updated
        await self.mutes.dump()
        return role

    async def _get_muted_role(self, server):
        if server is None:
            return None

        try:
            role_id = self.muted_roles[str(server.id)]
        except KeyError:
            return await self._create_muted_role(server)
        else:
            role = discord.utils.get(server.roles, id=role_id)
            # Role could've been deleted, which means it will be None. 
            # So we have to account for that.
            return role or await self._create_muted_role(server)

    @staticmethod
    async def _regen_muted_role_perms(role, *channels):
        muted_permissions = dict.fromkeys(['send_messages', 'manage_messages', 'add_reactions',
                                           'speak', 'connect', 'use_voice_activation'], False)
        for channel in channels:
            await channel.set_permissions(role, **muted_permissions)

    @staticmethod
    def put_payload(db, member, duration):
        payload = {
            'time': str(datetime.utcnow()),
            'duration': duration,
        }

        db[member.guild][str(member.id)] = payload

    async def _do_mute(self, member, duration):
        mute_role = await self._get_muted_role(member.guild)

        # with redirect_exception((discord.Forbidden, "I either need the Manage Roles permission, or {member} is too high."),
        #                         (discord.HTTPException, "I can't mute {member} for some reason...")):
        await member.add_roles(mute_role)
        self.put_payload(self.mutes, member, duration)

    async def _do_unmute(self, member):
        mute_role = await self._get_muted_role(member.guild)
        await member.remove_roles(mute_role)
        self.mutes[member.guild].pop(str(member.id))

    @commands.command()
    @checks.mod_or_permissions(manage_roles=True)
    async def mute(self, ctx, member: discord.Member, duration: duration, *, reason: str=None):
        """Mutes a user (obviously)"""
        await self._do_mute(member, duration)
        await ctx.send(f"Done. {member.mention} will now be muted for {duration_units(duration)}... \N{ZIPPER-MOUTH FACE}")
        await self._send_case(ctx, ModCase(type='mute', mod=ctx.author, user=member, reason=reason), duration)
        await asyncio.sleep(duration)
        await self._do_unmute(member)

    @commands.command()
    @checks.mod_or_permissions(manage_roles=True)
    async def unmute(self, ctx, member: discord.Member, *, reason: str=None):
        """Unmutes a user (obviously)"""
        await self._do_unmute(member)
        await ctx.send(f'{member.mention} can now speak again... \N{SMILING FACE WITH OPEN MOUTH AND COLD SWEAT}')
        await self._send_case(ctx, ModCase(type='unmute', mod=ctx.author, user=member, reason=reason), duration)

    @commands.command(name='regenmutedperms', aliases=['rmp'])
    @checks.is_owner()
    @commands.guild_only()
    async def regen_muted_perms(self, ctx):
        mute_role = await self._get_muted_role(ctx.guild)
        await self._regen_muted_role_perms(mute_role, *ctx.guild.channels)
        await ctx.send('\N{THUMBS UP SIGN}')
        
    @commands.command(name='setmuterole', aliases=['smur'])
    @checks.admin_or_permissions(manage_roles=True, manage_server=True)
    async def set_muted_role(self, ctx, *, role: discord.Role):
        """Sets the muted role for the server.
        
        Ideally you shouldn't have to do this, as I already create a muted role.
        This is just in case you already have a muted role and would like to use that one.
        """
        await self._regen_muted_role_perms(role, *ctx.guild.channels)
        self.muted_roles[str(ctx.guild.id)] = role.id
        await ctx.send(f'Set the muted role to **{role}**!')
        
    @commands.command(name='muterole', aliases=['mur'])
    async def muted_role(self, ctx):
        """Gets the current muted role."""
        role_id = self.muted_roles.get(str(ctx.guild.id), None)
        role = discord.utils.get(ctx.guild.roles, id=role_id)
        msg = ("There is no muted role, either set one now or let me create one for you."
               if role is None else f"The current muted role is **{role}**")
        await ctx.send(msg)

    @commands.command()
    @checks.mod_or_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str=None):
        """Kick a user (obviously)"""
        self._check_user(ctx, member)

        with redirect_exception((discord.Forbidden, 'I need the "Kick Members" permission, I think.'),
                                (discord.HTTPException, f'Kicking {member} failed, for some reason.')):
            await member.kick(reason=reason)
        await ctx.send(f"Done. Please don't make me do that again...")
        await self._send_case(ctx, ModCase(type='kick', mod=ctx.author, user=member, reason=reason))

    @staticmethod
    async def _attempt_ban(member, *, days=1, reason=None):
        with redirect_exception((Forbidden, 'I need the "Ban Members" permission, I think.'),
                                (HTTPException, f'Banning {member} failed, for some reason.')):
            await member.ban(delete_message_days=days, reason=reason)

    async def _attempt_unban(self, server, user, reason):
        await server.unban(user, reason)
        self.tempbans[server].pop(str(member.id), None)

    @commands.command(aliases=['sb'])
    @checks.mod_or_permissions(ban_members=True)
    async def softban(self, ctx, member: discord.Member, days: int=1, *, reason: str=None):
        """Softbans a user (obviously)"""
        self._check_user(ctx, member)
        await self._attempt_ban(member, days=days, reason=reason)
        await ctx.send("Done. Please don't make me do it again...")
        await self._send_case(ctx, ModCase(type='softban', mod=ctx.author, user=member, reason=reason))

        await asyncio.sleep(10)
        await member.unban(reason='unban after a softban')
        invite = await ctx.guild.create_invite(max_uses=1, reason=f'created to unban {member}')
        # XXX: This will not work if the user doesn't have any mutual servers 
        #      with the bot at this point. Is that ok?
        await member.send(f"You have been soft-banned by {ctx.author} "
                          f"for the following reason:\n{reason}\n"
                           "Here's the invite link back to the server. "
                          f"I hope you've learned your lesson...\n{invite}")

    @commands.command(aliases=['tb'])
    @checks.mod_or_permissions(ban_members=True)
    async def tempban(self, ctx, member: discord.Member, duration: duration, *, reason: str=None):
        """Temporarily bans a user (obviously)"""
        self._check_user(ctx, member)
        await self._attempt_ban(member, reason=reason)
        await ctx.send(f"Done. Please don't make me do that again...")

        self.put_payload(self.tempbans, member, duration)
        await self._send_case(ctx, ModCase(type='tempban', mod=ctx.author, user=member, reason=reason), duration)
        await asyncio.sleep(duration)
        await self._attempt_unban(ctx.guild, member, reason)

    @commands.command()
    @checks.mod_or_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str=None):
        """Bans a user (obviously)"""
        self._check_user(ctx, member)

        await self._attempt_ban(member, reason=reason)
        await ctx.send(f"Done. Please don't make me do that again...")
        await self._send_case(ctx, ModCase(type='ban', mod=ctx.author, user=member, reason=reason))

    @commands.command()
    @checks.mod_or_permissions(ban_members=True)
    async def unban(self, ctx, user: discord.User, *, reason: str=None):
        """Unbans a user (obviously)"""
        with redirect_exception((discord.Forbidden, 'I need the "Ban Members" permission, I think.'),
                                (discord.HTTPException, f'Unbanning {user} failed, for some reason.')):
            await ctx.guild.unban(user)
        await ctx.send("Done. What did they do to get banned in the first place...?")
        await self._send_case(ctx, ModCase(type='unban', mod=ctx.author, user=user, reason=reason))

    @commands.command()
    @checks.mod_or_permissions(ban_members=True)
    async def hackban(self, ctx, user_id):
        """Bans a user (obviously)
        
        Unlike {prefix}ban, this can only take the ID of a user.
        This makes it possible to ban a user who's not even in the server.
        (Not so obviously)
        """
        with redirect_exception((discord.Forbidden, 'I need the "Ban Members" permission, I think.'),
                                (discord.HTTPException, f'Unbanning user {user_id} failed, for some reason.')):
            await self._state.http.ban(user_id, ctx.guild.id)
        await ctx.send("\N{OK HAND SIGN}")

    # TODO: implement these stuffs
    async def antispam(self, limit, effect):
        pass

    @commands.command(name='warnpunish')
    async def warn_punish(self, ctx, num: int, punishment, duration: duration=None):
        """Sets the punishment a user receives upon exceeding a given warn limit"""
        punish_lower = punishment.lower()
        if punish_lower in _restricted_warn_punishments:
            raise errors.InvalidUserArgument("{punish_lower} is not a valid punishment")

        if punish_lower in {'tempban', 'mute'} and duration is None:
            raise errors.InvalidUserArgument(f'A duration is required for {punish_lower}')

        payload = {
            'punish': punish_lower,
            'duration': duration,
        }
        self.guild_warn_config[ctx.guild]['punishments'][str(num)] = payload
        await ctx.send(f'\N{OK HAND SIGN} if a user has been warned {num} times, I will **{punish_lower}** them.')

    async def warn_timeout(self, ctx, duration: duration):
        """Sets the maximum time between the oldest warn and the most recent warn.
        If a user hits a warn limit within this timeframe, they will be punished.
        """
        self.guild_warn_config[ctx.guild]['timeout'] = duration
        await ctx.send(f'Alright, if a user was warned within {duration_units(duration)} '
                        'after their oldest warn, bad things will happen.')


    # ------------- Case Related Commands ------------------

    def _get_case(self, server, num=None):
        cases = self.cases[server].setdefault('cases', [])
        with redirect_exception((IndexError, f"Couldn't find case {num}."),
                                cls=errors.ResultsNotFound):
            # support negative indexing
            if num is None:
                return cases
            num -= num > 0
            return cases[num]

    @commands.group()
    @checks.admin_or_permissions(manage_server=True)
    async def caseset(self, ctx):
        """Super-command for all mod case-related commands

        Only cases where the bot was used will be logged.
        """
        # TODO: Make like Pollr and log *everything*
        pass

    @caseset.command(name='logchannel', aliases=['channel'])
    async def log_channel(self, ctx, channel: discord.TextChannel):
        """Sets the channel for logging mod cases"""
        if not channel.permissions_for(ctx.me).send_messages:
            raise errors.InvalidUserArgument(f"I can't speak in {channel.mention}. Please give me the Send Messages perm there.\n")

        self.cases[ctx.guild]['case_channel'] = channel.id
        await ctx.send(f"Cases will now be put on {channel.mention}")

    @caseset.command(name='stop')
    async def case_stop(self, ctx):
        """Stops logging the mod-cases."""
        with redirect_exception((KeyError, "There was never a place to log any cases...")):
            self.cases[ctx.guild].pop('case_channel')
        await ctx.send(f"Cases will now be put on {channel.mention}")

    @caseset.command(name='reason')
    async def case_reason(self, ctx, num: int, *, reason):
        """Sets the reason for a given mod case"""
        case = self._get_case(ctx.guild, num)
        mod = case['mod']
        if case['type'] == 'WARN':
            return await ctx.send("Cannot edit a warn case (it doesn't make sense anyway...)")

        if mod not in (None, ctx.author.id):    
            return await ctx.send("That case is not yours...")

        channel = self.bot.get_channel(case['channel_id'])
        if channel is None:
            return await ctx.send("This channel no longer exists")

        message = await channel.get_message(case['message_id'])
        assert message.author.id == self.bot.user.id

        embed = message.embeds[0].set_field_at(-1, name="Reason", value=reason, inline=False)
        if mod is None:
            case['mod'] = ctx.author.id
            action_field = embed.fields[1]
            new_action = _rreplace(action_field.value, 'None', str(ctx.author), 1)
            embed.set_field_at(1, name=action_field.name, value=new_action, inline=False)

        await message.edit(embed=embed)
        case['reason'] = reason
        await ctx.send(f"Successfully changed case #{num}'s reason to {reason}!")

    @caseset.command(name='reset', aliases=['clear'])
    async def case_reset(self, ctx):
        """Resets all the mod cases. However, this doesn't clear the existing case messages."""
        cases = self._get_case(ctx.guild)
        if not cases:
            raise errors.ResultsNotFound("There are no cases in this server!")

        cases.clear()
        await ctx.send("Successfully cleared the cases for this server!")

    # Will probably be redone later but I don't like the implementation at the moment.
    # def _get_special_roles(self, server):
    #     return self.cases[server].setdefault('special_roles', [])

    # @caseset.command(name='addspecialrole', aliases=['asr'])
    # async def case_add_special_role(self, ctx, *, role: discord.Role):
    #     """Adds a special role to be logged."""
    #     muted_role = await self._get_muted_role(ctx.guild)
    #     if role == muted_role:
    #         return await ctx.send("That role is the muted role. It's already special.")

    #     special_roles = self._get_special_roles(ctx.guild)
    #     if role.id in special_roles:
    #         return await ctx.send("You have already made this role special.")

    #     special_roles.append(role.id)
    #     await ctx.send(f'{role} is now a special role! If a user is given this role, it will be logged.')

    # @caseset.command(name='removespecialrole', aliases=['rsr'])
    # async def case_remove_special_role(self, ctx, *, role: discord.Role):
    #     """Removes a special role from being logged."""

    #     special_roles = self._get_special_roles(ctx.guild)
    #     if role.id not in special_roles:
    #         return await ctx.send("This role isn't special.")

    #     special_roles.remove(role.id)
    #     await ctx.send(f'{role} is no longer a special role! I will not keep track of it anymore.')


    # --------- Events ---------

    async def on_message(self, message):
        await self.update_slowmode(message)

    async def on_guild_channel_create(self, channel):
        server = channel.guild
        role = await self._get_muted_role(server)
        if role is None:
            return
        await self._regen_muted_role_perms(role, channel)

    async def on_member_join(self, member):
        # Prevent mute-evasion
        mute_data = self.mutes[member.guild].get(str(member.id))
        if mute_data:
            await self._do_mute(member, mute_data['duration'])

    # async def on_member_update(self, before, after):
    #     new_roles = set(after.roles).symmetric_difference(before.roles)
    #     special_roles = self._get_special_roles(before.guild)

    #     for new_role in new_roles:
    #         if new_role.id in special_roles:
    #             await self._send_case(ctx, ModCase(type='special_role', mod=None, user=before, reason=None))

def setup(bot):
    bot.add_cog(Moderator(bot))
