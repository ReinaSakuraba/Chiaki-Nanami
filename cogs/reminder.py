import asyncio
import contextlib
import discord
import itertools
import parsedatetime

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from discord.ext import commands

from .utils.context_managers import redirect_exception
from .utils.converter import duration
from .utils.database import Database
from .utils.misc import duration_units, emoji_url, truncate
from .utils.timer import Scheduler, TimerEntry


MAX_REMINDERS = 10
ALARM_CLOCK_URL = emoji_url('\N{ALARM CLOCK}')

_calendar = parsedatetime.Calendar()
def parse_time(time_string):
    return _calendar.parseDT(time_string)[0]


# sorry not sorry danny
class Reminder:
    def __init__(self, bot):
        self.bot = bot
        self.reminder_data = Database('reminders.json', default_factory=list)
        self.scheduler = Scheduler(bot, 'reminder_complete')

        self.reminder_data.update((m_id, list(map(TimerEntry._make, v)))
                                  for m_id, v in self.reminder_data.items())
        for entry in itertools.chain.from_iterable(self.reminder_data.values()):
            self.scheduler.add_entry(entry)

    def __unload(self):
        with contextlib.suppress(BaseException):
            self.manager.close()

    def add_reminder(self, member, when, duration, channel_id, message):
        entry = TimerEntry(when, (duration, channel_id, member.id, message))
        self.reminder_data[member].append(entry)
        self.scheduler.add_entry(entry)

    def remove_reminder(self, entry):
        with contextlib.suppress(ValueError):
            self.reminder_data[entry.args[2]].remove(entry)
        with contextlib.suppress(ValueError):
            self.scheduler.remove_entry(entry)

    @commands.group(invoke_without_command=True)
    async def remind(self, ctx, duration: duration, *, message: commands.clean_content='nothing'):
        """Adds a reminder that will go off after a certain amount of time."""
        when = ctx.message.created_at + timedelta(seconds=duration)
        self.add_reminder(ctx.author, when.timestamp(), duration, ctx.channel.id, message)
        await ctx.send('ok')

    @remind.command(name='at')
    async def remind_at(self, ctx, when: parse_time, *, message: commands.clean_content='nothing'):
        """Adds a reminder that will go off at a certain time.

        Times are based off UTC.
        """
        delta = when - ctx.message.created_at
        seconds = delta.total_seconds()

        if seconds < 0:
            return await ctx.send("I can't go back in time for you. Sorry.")

        self.add_reminder(ctx.author, when.timestamp(), seconds, ctx.channel.id, message)
        await ctx.send('ok')

    @remind.command(name='cancel', aliases=['del'])
    async def cancel_reminder(self, ctx, index: int):
        """Cancels a pending reminder with a given index."""
        with redirect_exception((IndexError, f'{index} is either not valid, or out of range... I think.')):
            entry = self.reminder_data[ctx.author][index - (index > 0)]

        self.remove_reminder(entry)
        await ctx.send(f'#{index} canceled. Here was the original message, I think: {entry.args[-1]}.')

    @commands.command()
    async def reminders(self, ctx):
        """Lists all the pending reminders that you currently have."""
        reminders = self.reminder_data.get(ctx.author)
        if not reminders:
            return await ctx.send('You have no pending reminders...')

        embed = (discord.Embed(colour=self.bot.colour)
                .set_author(name='Reminders for {ctx.author}')
                )

        for i, entry in enumerate(self.reminder_data[ctx.author][:], start=1):
            _, channel_id, _, message = entry.args
            channel = self.bot.get_channel(channel_id)
            name = f'{i}. For {channel} from {channel.guild}'
            value = f'Finishes in {entry.dt :%c}\n"{truncate(message, 20, "...")}"'
            embed.add_field(name=name, value=value, inline=False)

        await ctx.send(embed=embed)

    async def on_reminder_complete(self, timer):
        duration, channel_id, user_id, message = timer.args
        human_delta = duration_units(duration)
        channel = self.bot.get_channel(channel_id)
        user = self.bot.get_user(user_id)

        is_private = isinstance(channel, discord.abc.PrivateChannel)
        destination_format = ('Direct Message' if is_private else f'#{channel} in {channel.guild}!')
        embed = (discord.Embed(description=message, colour=0x00ff00, timestamp=timer.dt)
                .set_author(name=f'Reminder for {destination_format}', icon_url=ALARM_CLOCK_URL)
                .set_footer(text=f'From {human_delta} ago. ')
                )

        try:
            await channel.send(f'<@{user_id}> {human_delta} ago you wanted to be reminded of {message}')
            await user.send(embed=embed)
        finally:
            self.remove_reminder(timer)


def setup(bot):
    bot.add_cog(Reminder(bot))
