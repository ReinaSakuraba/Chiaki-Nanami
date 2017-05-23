import asyncio
import discord
import random
import time

from collections import OrderedDict
from discord.ext import commands

from .manager import SessionManager
from ..utils.misc import str_join

class RacingSession:
    TRACK_LENGTH = 20
    DEFAULT_TRACK = '|' + '-' * TRACK_LENGTH + '|'
    MINIMUM_REQUIRED_MEMBERS = 2
    # fields can only go up to 25
    MAXIMUM_REQUIRED_MEMBERS = 25

    def __init__(self, ctx):
        self.ctx = ctx
        self.positions = OrderedDict()
        self.running = False
        self.current_embed = (discord.Embed(colour=self.ctx.bot.colour)
                             .set_author(name='Race has started!')
                             )
        self.start = time.perf_counter()

    def add_member(self, m):
        self.positions[m] = 1

    def already_joined(self, m):
        return m in self.positions

    def has_enough_members(self):
        return len(self.positions) >= self.MINIMUM_REQUIRED_MEMBERS

    def update_game(self):
        for member in self.positions:
            self.positions[member] = self.positions[member] + random.uniform(0, 3)

    def _member_fields(self):
        for member, position in self.positions.items():
            buffer = self.DEFAULT_TRACK
            position = round(position)
            progression = buffer[:position] + '\N{TURTLE}' + buffer[position:]
            yield {'name': str(member), 'value': progression}

    def update_current_embed(self):
        for i, kwargs in enumerate(self._member_fields()):
            self.current_embed.set_field_at(i, **kwargs, inline=False)

    def winners(self):
        return [member for member, position in self.positions.items()
                if round(position) >= self.TRACK_LENGTH + 1]

    async def run(self):
        for kwargs in self._member_fields():
            self.current_embed.add_field(**kwargs, inline=False)
        message = await self.ctx.send(embed=self.current_embed)
        self.running = True

        while True:
            await asyncio.sleep(random.uniform(1, 3))
            self.update_game()
            self.update_current_embed()
            await message.edit(embed=self.current_embed)
            winners = self.winners()
            if winners:
                break

        seconds = time.perf_counter() - self.start
        names = [str(m) for m in winners]
        if len(names) > 1:
            winners_fmt = ', '.join(names[:-1]) + ', and ' + names[-1]
            extra_winner_text = 'are the winners!'
        else:
            winners_fmt = names[0]
            extra_winner_text = 'is the winner!'

        await self.ctx.send(f'{winners_fmt} {extra_winner_text}')

    async def stop(self, force=True):
        pass


class Racing:
    def __init__(self, bot):
        self.bot = bot
        self.manager = SessionManager()

    @commands.command()
    async def race(self, ctx, bet=0):
        session = self.manager.get_session(ctx.channel)
        if session is not None:
            if session.running:
                return await ctx.send('You were a little late to the party!')
            if session.already_joined(ctx.author):
                return await ctx.send("You're already in the race!")

            session.add_member(ctx.author)
            return await ctx.send('ok')

        with self.manager.temp_session(ctx.channel, RacingSession(ctx)) as inst:
            inst.add_member(ctx.author)
            await ctx.send(f'Race has started! Type {ctx.prefix}{ctx.invoked_with} to join!')
            await asyncio.sleep(15)
            if not inst.has_enough_members():
                return await ctx.send("Can't start race. Not enough people :(")
            await inst.run()

def setup(bot):
    bot.add_cog(Racing(bot))