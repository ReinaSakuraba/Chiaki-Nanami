import asyncqlio
import discord
import itertools
import math
import psutil

from discord.ext import commands
from more_itertools import ilen, partition

from .utils import dbtypes
from .utils.formats import pluralize
from .utils.paginator import ListPaginator, EmbedFieldPages
from .utils.time import human_timedelta

_Table = asyncqlio.table_base()


class Command(_Table, table_name='commands'):
    id = asyncqlio.Column(dbtypes.AutoIncrementInteger, primary_key=True)
    guild_id = asyncqlio.Column(asyncqlio.BigInt, index=True)
    channel_id = asyncqlio.Column(asyncqlio.BigInt)
    author_id = asyncqlio.Column(asyncqlio.BigInt, index=True)
    used = asyncqlio.Column(asyncqlio.Timestamp)
    prefix = asyncqlio.Column(asyncqlio.String)
    command = asyncqlio.Column(asyncqlio.String, index=True)


class Stats:
    def __init__(self, bot):
        self.bot = bot
        self._md = self.bot.db.bind_tables(_Table)
        self.process = psutil.Process()

    async def on_command(self, ctx):
        command = ctx.command.qualified_name
        self.bot.command_leaderboard[command] += 1
        row = Command(
            guild_id=ctx.guild.id,
            channel_id=ctx.channel.id,
            author_id=ctx.author.id,
            used=ctx.message.created_at,
            prefix=ctx.prefix,
            command=command,
        )

        async with ctx.db.get_session() as s:
            await s.add(row)

    async def _show_top_commands(self, ctx, n, entries):
        padding = int(math.log10(n)) + 1
        lines = (f'`\u200b{i:>{padding}}.`  {c} ({pluralize(use=u)})'
                 for i, (c, u) in enumerate(entries, 1))

        title = pluralize(command=n)
        await ListPaginator(ctx, lines, title=f'Top {title}').interact()

    @commands.group(name='topcommands', aliases=['topcmds'], invoke_without_command=True)
    async def top_commands(self, ctx, n=10):
        """Shows the n most used commands since I've woken up."""
        entries = self.bot.command_leaderboard.most_common(n)
        await self._show_top_commands(ctx, n, entries)

    @top_commands.group(name='alltime', aliases=['all'])
    async def top_commands_alltime(self, ctx, n=10):
        """Shows the top n commands of all time, globally."""
        query = """SELECT command,
                          COUNT(*) as "uses"
                   FROM commands
                   GROUP BY command
                   ORDER BY "uses" DESC
                   LIMIT {n};
                """
        results = await (await ctx.session.cursor(query, {'n': n})).flatten()
        await self._show_top_commands(ctx, n, (r.values() for r in results))    

    @top_commands.group(name='alltimeserver', aliases=['allserver'])
    async def top_commands_alltimeserver(self, ctx, n=10):
        """Shows the top n commands of all time, in the server."""
        query = """SELECT command,
                          COUNT(*) as "uses"
                   FROM commands
                   WHERE guild_id = {guild_id}
                   GROUP BY command
                   ORDER BY "uses" DESC
                   LIMIT {n};
                """
        params = {'n': n, 'guild_id': ctx.guild.id}
        results = await (await ctx.session.cursor(query, params)).flatten()
        print(results)
        await self._show_top_commands(ctx, n, (tuple(r.values()) for r in results))

    @commands.command(name='stats')
    async def stats(self, ctx):
        """Shows some general statistics about the bot.

        Do not confuse this with `{prefix}about` which is just the
        general info. This is just numbers.
        """

        bot = self.bot
        command_map = itertools.starmap('{1} {0}'.format, bot.command_counter.most_common())
        command_stats = '\n'.join(command_map) or 'No stats yet.'
        extension_stats = '\n'.join(f'{len(set(getattr(bot, attr).values()))} {attr}'
                                    for attr in ('cogs', 'extensions'))

        with self.process.oneshot():
            memory_usage_in_mb = self.process.memory_full_info().uss / 1024**2
            cpu_usage = self.process.cpu_percent() / psutil.cpu_count()

        uptime_seconds = bot.uptime.total_seconds()
        average_messages = bot.message_counter / uptime_seconds
        message_field = f'{bot.message_counter} messages\n({average_messages :.2f} messages/sec)'

        text, voice = partition(lambda c: isinstance(c, discord.TextChannel), bot.get_all_channels())
        presence = (f"{len(bot.guilds)} Servers\n{ilen(text)} Text Channels\n"
                    f"{ilen(voice)} Voice Channels\n{len(bot.users)} Users")

        chiaki_embed = (discord.Embed(description=bot.appinfo.description, colour=self.bot.colour)
                        .set_author(name=str(ctx.bot.user), icon_url=bot.user.avatar_url)
                        .add_field(name='Modules', value=extension_stats)
                        .add_field(name='CPU Usage', value=f'{cpu_usage}%\n{memory_usage_in_mb :.2f}MB')
                        .add_field(name='Messages', value=message_field)
                        .add_field(name='Presence', value=presence)
                        .add_field(name='Commands', value=command_stats)
                        .add_field(name='Uptime', value=self.bot.str_uptime.replace(', ', '\n'))
                        )
        await ctx.send(embed=chiaki_embed)

    @commands.command(name='commandhistory', aliases=['cmdhistory'])
    async def command_history(self, ctx, n=5):
        """Shows the last n commands you've used."""
        n = min(n, 50)

        query = (ctx.session.select.from_(Command)
                            .where(Command.author_id == ctx.author.id)
                            .order_by(Command.used, sort_order='desc')
                            .offset(1)  # Skip this command.
                            .limit(n)
                 )

        rows = [(row.command, row.used) async for row in await query.all()]
        lines = [(f'`{row.prefix}{row.command}`', f'Executed {human_timedelta(row.used)}')
                 async for row in await query.all()]
        title = pluralize(command=n)
        pages = EmbedFieldPages(ctx, lines, title=f"{ctx.author}'s last {title}", 
                                inline=False, lines_per_page=5)
        await pages.interact()


    async def command_stats(self):
        pass

    async def shard_stats(self, ctx):
        """Shows the status for each of my shards, assuming I support sharding."""
        if not hasattr(ctx.bot, 'shards'):
            return await ctx.send("I don't support shards... yet.")
        # TODO


def setup(bot):
    bot.add_cog(Stats(bot))
