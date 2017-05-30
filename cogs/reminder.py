import asyncio
import contextlib
import discord

from collections import defaultdict
from datetime import datetime, timedelta
from discord.ext import commands

from .utils.compat import iter_except
from .utils.converter import duration
from .utils.database import Database
from .utils.json_serializers import DatetimeEncoder, decode_datetime
from .utils.misc import duration_units, emoji_url, truncate


MAX_REMINDERS = 10
ALARM_CLOCK_URL = emoji_url('\N{ALARM CLOCK}')


class Reminder:
    def __init__(self, bot):
        self.bot = bot
        self.reminder_data = Database('reminders.json', default_factory=list,
                                      encoder=DatetimeEncoder, object_hook=decode_datetime)
        self.reminder_tasks = defaultdict(dict)
        self.bot.loop.create_task(self._parse_reminders())

    def __unload(self):
        for _, reminders in iter_except(self.reminder_tasks.popitem, KeyError):
            for task in reminders.values():
                with contextlib.suppress(BaseException):
                    task.cancel()

    async def _parse_reminders(self):
        await self.bot.wait_until_ready()
        for member_id, reminders in list(self.reminder_data.items()):
            member_id = int(member_id)
            user = self.bot.get_user(member_id)
            # create a shallow copy of the list to avoid a RuntimeError
            # as the reminder data might be removed during iteration
            for reminder in reminders[:]:
                parsed = self._parse_reminder_data(reminder)
                self.reminder_tasks[member_id][parsed['when']] = self._make_task(reminder, user, **parsed)

    def _make_task(self, data, user, when, duration, destination, message):
        async def task():
            # We can use the time here for two reasons:
            # 1. It's impossible for two times to be the same
            # 2. The payload will have a time, that can be used as an 
            #    ID to identify the task
            try:
                await self._remind_task(user, when, duration, destination, message)
            finally:
                with contextlib.suppress(ValueError):
                    self.reminder_data[user].remove(data)
                with contextlib.suppress(KeyError):
                    del self.reminder_tasks[user.id][when]
        return asyncio.ensure_future(task())

    @staticmethod
    async def _remind_task(user, when, duration, destination, message):
        delta = datetime.utcnow() - when
        await asyncio.sleep(duration - delta.total_seconds())

        is_private = isinstance(destination, discord.abc.PrivateChannel)
        destination_format = ('Direct Message' if is_private else f'#{destination} in {destination.guild}!')
        reminder_embed = (discord.Embed(description=message, colour=0x00ff00, timestamp=when)
                         .set_author(name=f'Reminder for {destination_format}', icon_url=ALARM_CLOCK_URL)
                         .set_footer(text=f'From {duration_units(duration)} ago. ')
                         )
        await destination.send(f'{user.mention}, {message}')
        await user.send(embed=reminder_embed)

    def _parse_reminder_data(self, data):
        return {
            **data,
            'destination': self.bot.get_channel(data['destination'])
        }

    def add_reminder(self, ctx, duration, message):
        when = datetime.utcnow()
        user = ctx.author
        data = {
            'duration': duration,
            'when': when,
            'destination': ctx.channel.id,
            'message': message
        }
        self.reminder_data[user].append(data)
        self.reminder_tasks[user.id][when] = self._make_task(data, user, when, duration, ctx.channel, message)

    @commands.group(invoke_without_command=True)
    async def remind(self, ctx, duration: duration, *, message):
        if len(self.reminder_tasks.get(ctx.author, {})) > MAX_REMINDERS:
            return await ctx.send('You have too many pending reminders right now.')

        self.add_reminder(ctx, duration, message)
        future = datetime.utcnow() + timedelta(seconds=duration)
        await ctx.send(f'{ctx.author.mention} Okay, on {future :%c} I will '
                       f'remind you about {message}')

    async def remind_at(self, ctx, when, *, message):
        pass

    @commands.command()
    async def reminders(self, ctx):
        reminders = self.reminder_data.get(ctx.author, [])
        if not reminders:
            return await ctx.send('You have no pending reminders...')

        embed = (discord.Embed(colour=self.bot.colour)
                .set_author(name='Reminders for {ctx.author}')
                )

        for i, reminder in enumerate(self.reminder_data[ctx.author][:], start=1):
            channel = self.bot.get_channel(reminder['destination'])
            time = reminder['when'] + timedelta(seconds=reminder['duration'])
            name = f'{i}. For {channel} from {channel.guild}'
            value = f'Finishes in {time :%c}\n"{truncate(reminder["message"], 20, "...")}"'
            embed.add_field(name=name, value=value, inline=False)

        await ctx.send(embed=embed)

    @remind.command(name='cancel')
    async def cancel_reminder(self, ctx, index: int):
        """Cancels a pending a reminder."""
        index -= index > 0      # allow for nice negative indexing
        try:
            data = self.reminder_data[ctx.author][index]
        except IndexError:
            return await ctx.send(f"Task #{index} doesn't exist...")

        when = data['when']
        task = self.reminder_tasks[ctx.author.id][when]
        task.cancel()
        await ctx.send('ok byebye')

def setup(bot):
    bot.add_cog(Reminder(bot))
