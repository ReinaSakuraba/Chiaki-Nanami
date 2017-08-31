import contextlib
import discord
import itertools
import json
import parsedatetime

from discord.ext import commands
from datetime import timedelta

from .utils.context_managers import redirect_exception
from .utils.misc import emoji_url, truncate
from .utils.time import duration, human_timedelta


MAX_REMINDERS = 10
ALARM_CLOCK_URL = emoji_url('\N{ALARM CLOCK}')
CLOCK_URL = emoji_url('\N{MANTELPIECE CLOCK}')
CANCELED_URL = emoji_url('\N{BELL WITH CANCELLATION STROKE}')


_calendar = parsedatetime.Calendar()
def parse_time(time_string):
    return _calendar.parseDT(time_string)[0]


# sorry not sorry danny
class Reminder:
    def __init__(self, bot):
        self.bot = bot

    def __unload(self):
        with contextlib.suppress(BaseException):
            self.manager.close()

    @staticmethod
    def _create_reminder_embed(ctx, when, message):
        # Discord attempts to be smart with breaking up long lines. If a line
        # is extremely long, it will attempt to insert a line break before the
        # next word. This is good in some uses. However, lines that are just one
        # really long word won't be broken up into lines. This leads to the
        # embed being stretched all the way to the right.
        #
        # To avoid giving myself too much of a headache, I've decided to not
        # attempt to break up the lines myself.

        return (discord.Embed(colour=0x00FF00, description=message, timestamp=when)
               .set_author(name='Reminder set!', icon_url=CLOCK_URL)
               .set_thumbnail(url=ctx.author.avatar_url)
               .add_field(name='For', value=f'#{ctx.channel} in {ctx.guild}', inline=False)
               .set_footer(text='Set to go off at')
               )

    async def _add_reminder(self, ctx, when, message):
        args = (ctx.author.id, ctx.channel.id, message)
        await ctx.bot.db_scheduler.add_abs(when, 'reminder_complete', args)
        await ctx.send(embed=self._create_reminder_embed(ctx, when, message))

    @commands.group(invoke_without_command=True)
    async def remind(self, ctx, duration: duration, *, message: commands.clean_content='nothing'):
        """Adds a reminder that will go off after a certain amount of time."""

        when = ctx.message.created_at + timedelta(seconds=duration)
        await self._add_reminder(ctx, when, message)

    @remind.command(name='at')
    async def remind_at(self, ctx, when: parse_time, *, message: commands.clean_content='nothing'):
        """Adds a reminder that will go off at a certain time.

        Times are based off UTC.
        """
        if when < ctx.message.created_at:
            return await ctx.send("I can't go back in time for you. Sorry.")
        await self._add_reminder(ctx, when, message)

    @remind.command(name='cancel', aliases=['del'])
    async def cancel_reminder(self, ctx, index: int=1):
        """Cancels a running reminder with a given index. Reminders start at 1.

        If no args are given, it defaults to the earliest one.
        """
        query = """SELECT *
                   FROM schedule
                   WHERE event = 'reminder_complete'
                   AND args_kwargs #>> '{args,0}' = $1
                   ORDER BY created
                   OFFSET $2
                   LIMIT 1;
                """

        # We have to go to the lowest level possible, because simply using
        # ctx.session.cursor WILL NOT work, as it uses str.format to format
        # the parameters, which will throw a KeyError due to the {} in the
        # JSON operators.
        async with ctx.db.connector.pool.acquire() as session:
            entry = await session.fetchrow(query, str(ctx.author.id), index - 1)
        if entry is None:
            return await ctx.send(f'Reminder #{index} does not exist... baka...')

        await ctx.bot.db_scheduler.remove(discord.Object(id=entry['id']))

        _, channel_id, message = json.loads(entry['args_kwargs'])['args']
        channel = self.bot.get_channel(channel_id) or 'deleted-channel'
        # In case the channel doesn't exist anymore
        server = getattr(channel, 'guild', None)

        embed = (discord.Embed(colour=0xFF0000, description=message, timestamp=entry['expires'])
                .set_author(name=f'Reminder #{index} cancelled!', icon_url=CANCELED_URL)
                .add_field(name='Was for', value=f'{channel} in {server}')
                .set_footer(text='Was set to go off at')
                )

        await ctx.send(embed=embed)

    @commands.command()
    async def reminders(self, ctx):
        """Lists all the pending reminders that you currently have."""     
        query = """SELECT expires, args_kwargs #>> '{args,1}', args_kwargs #>> '{args,2}'
                   FROM schedule
                   WHERE event = 'reminder_complete'
                   AND args_kwargs #>> '{args,0}' = $1
                   ORDER BY expires;
                """
        # We have to go to the lowest level possible, because simply using
        # ctx.session.cursor WILL NOT work, as it uses str.format to format
        # the parameters, which will throw a KeyError due to the {} in the
        # JSON operators.
        async with ctx.db.connector.pool.acquire() as session:
            reminders = await session.fetch(query, str(ctx.author.id))

        if not reminders:
            return await ctx.send("You have no reminders at the moment.")

        em = (discord.Embed(colour=self.bot.colour)
             .set_author(name=f'Reminders for {ctx.author}')
             )

        for expires, channel_id, message in reminders:
            em.add_field(name=f'In {human_timedelta(expires)} from now.', 
                         value=truncate(f'<#{channel_id}>: {message}', 1024, '...'), inline=False)

        await ctx.send(embed=em)

    async def on_reminder_complete(self, timer):
        user_id, channel_id, message = timer.args
        human_delta = human_timedelta(timer.created)
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            # rip
            return

        user = self.bot.get_user(user_id)

        is_private = isinstance(channel, discord.abc.PrivateChannel)
        destination_format = ('Direct Message' if is_private else f'#{channel} in {channel.guild}!')
        embed = (discord.Embed(description=message, colour=0x00ff00, timestamp=timer.utc)
                .set_author(name=f'Reminder for {destination_format}', icon_url=ALARM_CLOCK_URL)
                .set_footer(text=f'From {human_delta}.')
                )

        with contextlib.suppress(discord.HTTPException):
            await user.send(embed=embed)
        try:
            await channel.send(f"<@{user_id}>", embed=embed)
        except discord.HTTPException:  # can't embed
            await channel.send(f'<@{user_id}> {human_delta} ago you wanted to be reminded of {message}')


def setup(bot):
    bot.add_cog(Reminder(bot))
