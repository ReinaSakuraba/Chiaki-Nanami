import contextlib
import discord
import functools
import itertools

from collections import namedtuple
from datetime import datetime
from discord.ext import commands

from .utils.compat import async_cache
from .utils.database import Database
from .utils.formats import pluralize
from .utils.misc import duration_units, emoji_url, ordinal
from .utils.timer import Scheduler, TimerEntry


ModAction = namedtuple('ModAction', 'repr emoji colour')
_mod_actions = {
    'warn'    : ModAction('warned', '\N{WARNING SIGN}', 0xFFAA00),
    'mute'    : ModAction('muted', '\N{ZIPPER-MOUTH FACE}', 0),
    'kick'    : ModAction('kicked', '\N{WOMANS BOOTS}', 0xFF0000),
    'softban' : ModAction('soft banned', '\N{BIOHAZARD SIGN}', 0xF08000),
    'tempban' : ModAction('temporarily banned', '\N{ALARM CLOCK}', 0xA00000),
    'ban'     : ModAction('banned', '\N{HAMMER}', 0x800000),
    'unban'   : ModAction('unbanned', '\N{HAMMER}', 0x00FF00),
    'massban' : ModAction('massbanned', '\N{NO ENTRY}', 1)    
}
# punishments that have a duration argument
PUNISHMENTS_WITH_DURATION = ['tempban', 'mute']


def _is_mod_action(ctx):
    return ctx.command.qualified_name in _mod_actions

@async_cache(maxsize=512)
async def _get_message(channel, message_id):
    o = discord.Object(id=message_id + 1)
    # don't wanna use get_message due to poor rate limit (1/1s) vs (50/1s)
    msg = await channel.history(limit=1, before=o).next()

    if msg.id != message_id:
        return None

    return msg

_case_config_default = {
    'log': False,
}

class Cases:
    def __init__(self, bot):
        self.bot = bot
        # I'm storing the cases and the the configs separately
        # This lightens the cognitive overhead, as merging the actual cases
        # and their configs in one file would give me nothing but headaches
        self.case_config = Database('cases/configs.json', default_factory=_case_config_default.copy)
        # A case has six entries
        # type     = The action that was done
        # user     = The ID of the user who did the action
        # targets  = A list of all the IDs of the users who were affected by the action
        # duration = The length the target was affected for, used for mute and tempban
        # auto     = Whether or not the target was auto-punished by warn.
        # reason   = The reason the action was done.
        #
        # server is not needed, it's stored in the key.
        # Also there are message_id and channel_id that store the messages
        self.cases = Database('cases/cases.json', default_factory=list)

        # Somewhat hacky way to prevent doubling up the logs if a user uses the bot to ban.
        self._cache = set()
        self._remove_scheduler = Scheduler(bot, 'mod_cache_remove')

    async def send_case(self, action, server, user, *targets, reason, duration=None, auto=False):
        config = self.case_config[server]
        if not config['log']:
            return

        channel = self.bot.get_channel(config.get('channel_id'))
        if channel is None:
            return

        cases = self.cases[server]
        embed = self.make_embed(len(cases) + 1, action, server, user,
                               *targets, reason=reason, duration=duration,
                               auto=auto)

        msg = await channel.send(embed=embed)

        case = {
            'message_id': msg.id,
            'channel_id': channel.id,
            'type': action,
            'user': user.id,
            'targets': [t.id for t in targets],
            'duration': duration,
            'auto': auto,
            'reason': reason,
        }
        cases.append(case)

    def make_embed(self, num, action, server, user, *targets, reason, duration=None, auto=False):
        mod_action = _mod_actions[action]
        avatar_url = targets[0].avatar_url if len(targets) == 1 else None
        bot_avatar = self.bot.user.avatar_url

        duration_string = f' for {duration_units(duration)}' if duration is not None else ''
        action_field = f'{"Auto-" * auto}{mod_action.repr.title()}{duration_string} by {user}'
        reason = reason or 'No reason. Please enter one.'

        embed = (discord.Embed(color=mod_action.colour, timestamp=datetime.utcnow())
                .set_author(name=f"Case #{num}", icon_url=emoji_url(mod_action.emoji))
                .add_field(name=f'User{"s" * (len(targets) != 1)}', value=','.join(map(str, targets)))
                .add_field(name="Action", value=action_field, inline=False)
                .add_field(name="Reason", value=reason, inline=False)
                .set_footer(text=f'ID: {user.id}', icon_url=bot_avatar)
                )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)
        return embed

    def get_warn_number(self, member):
        mod = self.bot.get_cog('Moderator')
        assert mod is not None, "Mod Cog not loaded but a warn case was logged."

        log = mod.warn_log['s{0.guild.id};m{0.id}'.format(member)]
        return len(log)

    async def notify_user(self, action, server, user, *targets, reason, duration=None, auto=False):
        if action == 'massban':
            return

        mod_action = _mod_actions[action]

        action_applied = f'You were {mod_action.repr}'
        # Will probably refactor this later.
        embed = (discord.Embed(colour=mod_action.colour, timestamp=datetime.utcnow())
                .add_field(name='In', value=str(server), inline=False)
                .add_field(name='By', value=str(user), inline=False)
                .add_field(name='Reason', value=reason, inline=False)
                )
        set_author = functools.partial(embed.set_author, icon_url=emoji_url(mod_action.emoji))

        for target in targets:
            if duration:
                applied = f'{action_applied} for {duration_units(duration)}'
            elif action == 'warn':
                applied = f'{action_applied} for the {ordinal(self.get_warn_number(target))} time'

            set_author(name=f'{applied}!')
            with contextlib.suppress(discord.HTTPException):
                await target.send(embed=embed)
                print('ok', target)
        print('success!')

    async def embed_from_index(self, server, idx):
        entry = self.cases[server][idx]
        user = self.bot.get_user(entry['user'])
        # The user wasn't found, so we'll have to just grab the embed that 
        # was previously sent before
        if user is None:
            channel = self.bot.get_channel(entry['channel_id'])
            message = await _get_message(channel, entry['message_id'])
            return message.embeds[0]


        return self.make_embed(idx + 1, entry['type'], server, user,
                               *map(self.bot.get_user, entry['targets']),
                               reason=entry['reason'],
                               duration=entry.get('duration', None),
                               auto=entry.get('auto', False)
                               )


    @commands.group(invoke_without_command=True)
    async def case(self, ctx, num: int = -1):
        """Shows a particular case entry. Defaults to the most recent one"""
        cases = self.cases[ctx.guild]
        if num < 0:
            num += len(cases)

        entry_embed = await self.embed_from_index(ctx.guild, num)
        message = f'{ctx.author.mention}, Case #{num + 1} from {entry_embed.timestamp}'
        await ctx.send(message, embed=entry_embed)

    @case.command(name='set')
    @commands.has_permissions(manage_guild=True)
    async def case_set(self, ctx, do_cases: bool):
        """Sets whether or not cases should be logged.

        Keep in mind that if this is disabled, any new cases won't be logged
        until it's re-enabled. When it's re-enabled, the number will start off from
        before it was disabled.
        """
        self.case_config[ctx.guild]['log'] = do_cases
        message = ("ZzzZzZzz... ok then...",
                   "Alright, let's get started on logging this moderation actions!"
                   )[do_cases]

        await ctx.send(message)

    @case.command(name='channel')
    @commands.has_permissions(manage_guild=True)
    async def case_channel(self, ctx, channel: discord.TextChannel = None):
        """Sets the channel to log cases. 

        If given no arguments, it shows the current channel that is being used.
        """
        config = self.case_config[ctx.guild]
        if channel is None:
            log_channel = self.bot.get_channel(config.get('channel_id'))
            message = ("Umm... I don't have a channel, please set one with "
                       f"`{ctx.prefix}{ctx.command.full_parent_name} {ctx.invoked_with} my_channel`"
                      if channel is None else f"I'll do my reports in {log_channel.mention}")
            await ctx.send(message)
        else:
            config['channel_id'] = channel.id
            await ctx.send(f'Ok, {channel.mention} it is then!')

    @case.command(name='reset', aliases=['clear'])
    @commands.has_permissions(manage_guild=True)
    async def case_reset(self, ctx):
        """Resets the case-logger.

        This clears all the entries, so use this with caution.
        """
        cases = self.cases[ctx.guild]
        if not cases:
            return await ctx.send("I haven't even reported anything yet!")
        cases.clear()
        await ctx.send("Ok, let's have a fresh start now!")

    @commands.command()
    async def reason(self, ctx, index: int, *, reason):
        """Sets the reason for a given case entry. 

        You can only edit a case that's yours.
        """

        entry = self.cases[ctx.guild][index]
        user = ['user']
        if entry['user'] != ctx.author.id:
            return await ctx.send('This case is not yours...')

        channel = self.bot.get_channel(entry['channel_id'])
        if channel is None:
            return await ctx.send("The channel this case was in longer exists.")

        message = await _get_message(channel, entry['message_id'])
        if message is None:
            return await ctx.send("The message was deleted (for some reason). I can't edit it.")

        assert message.author.id == self.bot.user.id

        embed = message.embeds[0].set_field_at(-1, name="Reason", value=reason, inline=False)
        if user is None:
            entry['user'] = ctx.author.id
            action_field = embed.fields[1]
            new_action = _rreplace(action_field.value, 'None', str(ctx.author), 1)
            embed.set_field_at(1, name=action_field.name, value=new_action, inline=False)

        await message.edit(embed=embed)
        entry['reason'] = reason
        await ctx.send(f"Successfully changed case #{index}'s reason to {reason}!")

    @case.error
    @reason.error
    async def case_error(self, ctx, error):
        if isinstance(error.__cause__, IndexError):
            await ctx.send(f'Case #{ctx.args[2]} does not point to a case in this server...')

    async def on_command(self, ctx):
        # We only want to put the result on the cache iff the command succeeded parsing
        # It's ok if the command fails, we'll just handle it in on_command_error
        if not _is_mod_action(ctx):
            return

        targets = (m for m in ctx.args if isinstance(m, discord.Member))
        for member in targets:
            args = ctx.command.qualified_name, ctx.guild.id, member.id
            self._cache.add(args)
            entry = TimerEntry(datetime.utcnow().timestamp() + 5, args)
            self._remove_scheduler.add_entry(entry)

    async def on_command_completion(self, ctx):
        if not _is_mod_action(ctx):
            return
        action = ctx.command.qualified_name

        targets = [m for m in ctx.args if isinstance(m, discord.Member)]
        
        duration = ctx.args[3] if action in PUNISHMENTS_WITH_DURATION else None
        reason = ctx.kwargs['reason'] if action != 'massban' else ctx.args[2]
        auto_punished = getattr(ctx, 'auto_punished', False)

        await self.send_case(action, ctx.guild, ctx.author, *targets, 
                             reason=reason, duration=duration, auto=auto_punished)
        await self.notify_user(action, ctx.guild, ctx.author, *targets,
                               reason=reason, duration=duration, auto=auto_punished)


    async def _poll_audit_log(self, guild, user, *, action):
        if (action, guild.id, user.id) in self._cache:
            # Assume it was invoked by a command (only commands will put this in the cache).
            return

        # poll the audit log for some nice shit
        # XXX: This doesn't catch softbans.
        audit_action = getattr(discord.AuditLogAction, action)
        entry = await guild.audit_logs(action=audit_action, limit=1).get(target=user)
        await self.send_case(action, guild, entry.user, entry.target, reason=entry.reason)

    async def _poll_ban(self, guild, user, *, action):
        if ('softban', guild.id, user.id) in self._cache:
            return
        await self._poll_audit_log(guild, user, action=action)

    async def on_member_ban(self, guild, user):
        await self._poll_ban(guild, user, action='ban')

    async def on_member_unban(self, guild, user):
        await self._poll_ban(guild, user, action='unban')

    async def on_member_remove(self, member):
        await self._poll_audit_log(member.guild, member, action='kick')

    async def on_mod_cache_remove(self, entry):
        self._cache.discard(entry.args)


def setup(bot):
    bot.add_cog(Cases(bot))