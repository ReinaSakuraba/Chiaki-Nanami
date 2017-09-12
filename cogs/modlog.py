import asyncio
import asyncqlio
import collections
import discord
import enum
import json

from datetime import datetime
from discord.ext import commands
from operator import attrgetter

from .utils import cache, dbtypes
from .utils.misc import emoji_url
from .utils.time import duration_units


class ModLogError(Exception):
    pass


_Table = asyncqlio.table_base()


class Case(_Table, table_name='modlog'):
    id = asyncqlio.Column(dbtypes.AutoIncrementInteger, primary_key=True)
    channel_id = asyncqlio.Column(asyncqlio.BigInt, index=True)
    message_id = asyncqlio.Column(asyncqlio.BigInt, index=True)

    guild_id = asyncqlio.Column(asyncqlio.BigInt, index=True)
    action = asyncqlio.Column(asyncqlio.String(16))
    mod_id = asyncqlio.Column(asyncqlio.BigInt)
    reason = asyncqlio.Column(asyncqlio.String(1024))
    created_at = asyncqlio.Column(asyncqlio.Timestamp)

    # Can either be the duration, in the case of a mute or tempban,
    # or the role, in the case of a special role.
    extra = asyncqlio.Column(asyncqlio.Text, default='{}')


class CaseTarget(_Table, table_name='modlog_targets'):
    id = asyncqlio.Column(dbtypes.AutoIncrementInteger, primary_key=True)
    entry_id = asyncqlio.Column(dbtypes.AutoIncrementInteger)
    user_id = asyncqlio.Column(asyncqlio.BigInt)


ModAction = collections.namedtuple('ModAction', 'repr emoji colour')


_mod_actions = {
    'warn'    : ModAction('warned', '\N{WARNING SIGN}', 0xFFAA00),
    'mute'    : ModAction('muted', '\N{SPEAKER WITH CANCELLATION STROKE}', 0),
    'kick'    : ModAction('kicked', '\N{WOMANS BOOTS}', 0xFF0000),
    'softban' : ModAction('soft banned', '\N{BIOHAZARD SIGN}', 0xF08000),
    'tempban' : ModAction('temporarily banned', '\N{ALARM CLOCK}', 0xA00000),
    'ban'     : ModAction('banned', '\N{HAMMER}', 0x800000),
    'unban'   : ModAction('unbanned', '\N{DOVE OF PEACE}', 0x00FF00),
    'hackban' : ModAction('prematurely banned', '\N{NO ENTRY}', 1),
    'massban' : ModAction('massbanned', '\N{NO ENTRY}', 1),
}

for k, v in list(_mod_actions.items()):
    _mod_actions[f'auto-{k}'] = v._replace(repr=f'auto-{v.repr}')

MASSBAN_THUMBNAIL = emoji_url('\N{NO ENTRY}')


ActionFlag = enum.IntFlag('ActionFlag', list(_mod_actions))
_default_flags = (2 ** len(_mod_actions) - 1) & ~ActionFlag.hackban


class ModLogConfig(_Table, table_name='case_config'):
    guild_id = asyncqlio.Column(asyncqlio.BigInt, primary_key=True)
    channel_id = asyncqlio.Column(asyncqlio.BigInt)
    enabled = asyncqlio.Column(asyncqlio.Boolean, default=True)
    log_auto = asyncqlio.Column(asyncqlio.SmallInt, default=True)
    events = asyncqlio.Column(asyncqlio.Integer, default=_default_flags)


def _is_mod_action(ctx):
    return ctx.command.qualified_name in _mod_actions


@cache.cache(maxsize=512)
async def _get_message(channel, message_id):
    o = discord.Object(id=message_id + 1)
    # don't wanna use get_message due to poor rate limit (1/1s) vs (50/1s)
    msg = await channel.history(limit=1, before=o).next()

    if msg.id != message_id:
        return None

    return msg


class ModLog:
    def __init__(self, bot):
        self.bot = bot
        self._md = bot.db.bind_tables(_Table)
        self._cache_cleaner = asyncio.ensure_future(self._clean_cache())

    def __unload(self):
        self._cache_cleaner.cancel()

    async def _clean_cache(self):
        # Used to clear the message cache every now and then
        while True:
            await asyncio.sleep(60 * 20)
            _get_message.cache.clear()

    async def _get_case_config(self, session, guild_id):
        query = (session.select.from_(ModLogConfig)
                        .where(ModLogConfig.guild_id == guild_id)
                 )
        return await query.first()

    async def _send_case(self, session, action, server, mod, targets, reason, extra=None, auto=False):
        config = await self._get_case_config(session, server.id)
        if not (config and config.enabled):
            return None

        if not config.events & ActionFlag[action]:
            return None

        if auto and not config.log_auto:
            return None

        channel = server.get_channel(config.channel_id)
        if not channel:
            raise ModLogError(f"The channel ID you specified ({config.channel_id}) doesn't exist.")

        if auto:
            action = f'auto-{action}'

        # Get the case number, this is why the guild_id is indexed.
        query = "SELECT COUNT(*) FROM modlog WHERE guild_id={guild_id};"
        params = {'guild_id': server.id}
        result = await session.cursor(query, params)
        row = await result.fetch_row()

        # Send the case like normal
        embed = self._create_embed(row['count'] + 1, action, mod, targets, reason, extra)

        try:
            message = await channel.send(embed=embed)
        except discord.Forbidden:
            raise ModLogError(f"I can't send messages to {channel.mention}. Check my privileges pls...")

        # Add the case to the DB, because mod-logging was successful!
        row = await session.add(Case(
            guild_id=server.id,
            channel_id=channel.id,
            message_id=message.id,

            action=action,
            mod_id=mod.id,
            reason=reason,

            created_at=message.created_at,
            extra=json.dumps({'args': [extra]})

        ))

        return row.id

    def _create_embed(self, number, action, mod, targets, reason, extra):
        action = _mod_actions[action]

        avatar_url = targets[0].avatar_url if len(targets) == 1 else MASSBAN_THUMBNAIL
        bot_avatar = self.bot.user.avatar_url

        duration_string = f' for {duration_units(extra)}' if extra is not None else ''
        action_field = f'{action.repr.title()}{duration_string} by {mod}'
        reason = reason or 'No reason. Please enter one.'

        return (discord.Embed(color=action.colour, timestamp=datetime.utcnow())
                .set_author(name=f"Case #{number}", icon_url=emoji_url(action.emoji))
                .set_thumbnail(url=avatar_url)
                .add_field(name=f'User{"s" * (len(targets) != 1)}', value=', '.join(map(str, targets)))
                .add_field(name="Action", value=action_field, inline=False)
                .add_field(name="Reason", value=reason, inline=False)
                .set_footer(text=f'ID: {mod.id}', icon_url=bot_avatar)
                )

    async def _insert_case(self, session, action, server, mod, targets, reason, extra, entry_id):
        if len(targets) == 1:
            await session.add(CaseTarget(entry_id=entry_id, user_id=targets[0].id))
        else:
            columns = ('entry_id', 'user_id')
            to_insert = [(entry_id, t.id) for t in targets]
            conn = session.transaction.acquired_connection
            await conn.copy_records_to_table('modlog_targets', columns=columns, records=to_insert)

    async def on_command_completion(self, ctx):
        name = ctx.command.qualified_name
        if name not in _mod_actions:
            return

        targets = [m for m in ctx.args if isinstance(m, discord.Member)]
        # Will be set by warn in the event of auto-punishment
        auto = getattr(ctx, 'auto_punished', False)
        # For mutes and tempbans.
        extra = ctx.args[3] if 'duration' in ctx.command.params else None
        # In the event of a massban, the reason is a required positional argument
        # rather than a keyword-only consume rest one.
        reason = ctx.kwargs.get('reason') or ctx.args[2]

        try:
            # Connection will be closed by the time this event is called,
            # so we can't use ctx.session.
            async with ctx.db.get_session() as session:
                args = (session, name, ctx.guild, ctx.author, targets, reason, extra)
                entry_id = await self._send_case(*args, auto=auto)
                if entry_id:
                    await self._insert_case(*args, entry_id)

        except ModLogError as e:
            await ctx.send(f'{ctx.author.mention}, {e}')

    async def _get_case(self, session, guild_id, num):
        query = (session.select.from_(Case)
                        .where(Case.guild_id == guild_id)
                        .order_by(Case.id)
                        .offset(num - 1)
                        .limit(1)
                 )
        return await query.first()

    # Now for the commands.
    @commands.group(invoke_without_command=True)
    async def case(self, ctx, num: int):
        """Retrives the case with the given number."""
        # I'll find some way to do handle negative number later...
        result = await self._get_case(ctx.session, ctx.guild.id, num)
        if result is None:
            return await ctx.send(f'Case #{num} is not a valid case.')

        t_query = ctx.session.select.from_(CaseTarget).where(CaseTarget.entry_id == result.id)
        targets = [ctx.bot.get_user(row.user_id) or f'<Unknown: {row.user_id}>'
                   async for row in await t_query.all()]

        extra = json.loads(result.extra)
        extra = extra['args'][0] if extra else None

        # Parse the cases accordingly
        embed = self._create_embed(
            num,
            result.action,
            ctx.bot.get_user(result.mod_id),
            targets,
            result.reason,
            extra,
        )

        await ctx.send(embed=embed)

    @commands.group()
    @commands.has_permissions(manage_guild=True)
    async def modlog(self, ctx):
        pass

    @modlog.command(name='channel')
    @commands.has_permissions(manage_guild=True)
    async def modlog_channel(self, ctx, channel: discord.TextChannel):
        """Sets the channel that will be used for logging moderation actions"""
        permissions = ctx.me.permissions_in(channel)
        if not permissions.read_messages:
            return await ctx.send(f'I need to be able to read messages in {channel.mention} you baka!')

        if not permissions.send_messages:
            return await ctx.send(f'I need to be able to send messages in {channel.mention}. '
                                  'How else will I be able to log?!')

        if not permissions.embed_links:
            return await ctx.send('I need the Embed Links permissions in order to make '
                                  f'{channel.mention} the mod-log channel...')

        config = await self._get_case_config(ctx.session, ctx.guild.id)
        config = config or ModLogConfig(guild_id=ctx.guild.id)
        config.channel_id = channel.id

        await ctx.session.add(config)
        await ctx.send('ok')

    @commands.command()
    @commands.has_permissions(manage_guild=True)
    async def reason(self, ctx, num: int, *, reason):
        case = await self._get_case(ctx.session, ctx.guild.id, num)
        if case is None:
            return await ctx.send(f"Case #{num} doesn't exist.")

        if case.mod_id != ctx.author.id:
            return await ctx.send("This case is not yours.")

        channel = ctx.guild.get_channel(case.channel_id)
        if not channel:
            return await ctx.send('This channel no longer exists... :frowning:')

        message = await _get_message(channel, case.message_id)
        if not message:
            return await ctx.send('Somehow this message was deleted...')

        embed = message.embeds[0]
        reason_field = embed.fields[-1]
        embed.set_field_at(-1, name=reason_field.name, value=reason, inline=False)

        try:
            await message.edit(embed=embed)
        except discord.NotFound:
            # In case the message was cached, and the message was deleted
            # While it was still in the cache.
            return await ctx.send('Somehow this message was deleted...')

        case.reason = reason
        await ctx.session.add(case)
        await ctx.send('\N{OK HAND SIGN}')


def setup(bot):
    bot.add_cog(ModLog(bot))