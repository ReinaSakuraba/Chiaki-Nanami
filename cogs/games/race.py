import asyncio
import contextlib
import discord
import heapq
import operator
import random
import time

from collections import OrderedDict
from discord.ext import commands

from .manager import SessionManager
from ..utils.misc import str_join


TRACK_LENGTH = 40
DEFAULT_TRACK = '|' + '-' * TRACK_LENGTH + '|'
ANIMALS = [
    '\N{TURTLE}',
    '\N{SNAIL}',
    '\N{ELEPHANT}',
    '\N{RABBIT}',
    '\N{PIG}'
]


class Racer:
    def __init__(self):
        self.animal = random.choice(ANIMALS)
        self.distance = 0

    def update(self):
        self.distance += random.triangular(0, 10, 3)

    def is_finished(self):
        return self.distance >= TRACK_LENGTH + 1

    @property
    def progress(self):
        buffer = DEFAULT_TRACK
        position = round(self.distance)
        return buffer[:position] + self.animal + buffer[position:]

    @property
    def position(self):
        return self.distance / TRACK_LENGTH * 100


class RacingSession:
    MINIMUM_REQUIRED_MEMBERS = 2
    # fields can only go up to 25
    MAXIMUM_REQUIRED_MEMBERS = 25

    def __init__(self, ctx):
        self.ctx = ctx
        self.players = OrderedDict()
        self.running = False
        self._track = (discord.Embed(colour=self.ctx.bot.colour)
                      .set_author(name='Race has started!')
                      .set_footer(text='Current Leader: None')
                      )
        self._is_full = asyncio.Event()

    def add_member(self, m):
        self.players[m] = Racer()
        if len(self.players) >= self.MAXIMUM_REQUIRED_MEMBERS:
            self._is_full.set()

    def already_joined(self, m):
        return m in self.players

    def has_enough_members(self):
        return len(self.players) >= self.MINIMUM_REQUIRED_MEMBERS

    def update_game(self):
        for player in self.players.values():
            player.update()

    def _member_fields(self):
        return ((str(member), racer.progress) for member, racer in self.players.items())

    def update_current_embed(self):
        for i, (name, value) in enumerate(self._member_fields()):
            self._track.set_field_at(i, name=name, value=value, inline=False)

        leader = self.leader
        position = min(self.players[leader].position, 100)
        self._track.set_footer(text=f'Current Leader: {leader} ({position: .2f}m)')

    def winners(self):
        return [m for m, r in self.players.items() if r.is_finished()]

    async def wait_until_full(self):
        await self._is_full.wait()

    async def _loop(self):
        for name, value in self._member_fields():
            self._track.add_field(name=name, value=value, inline=False)
        message = await self.ctx.send(embed=self._track)
        self.running = True

        while True:
            await asyncio.sleep(random.uniform(1, 3))
            self.update_game()
            self.update_current_embed()
            await message.edit(embed=self._track)
            if self.is_completed():
                break

    async def _display_winners(self):
        names = ['Winner', 'Runner Up', 'Third Runner']
        embed = discord.Embed(title='Results', colour=0x00FF00)
        # Cannot use '\N' because the medal characters don't have a name
        # I can only refer to them by their code points.
        for title, (char, (member, racer)) in zip(names, enumerate(self.top_racers(), start=0x1f947)):
            use_flag = "\N{CHEQUERED FLAG}" * racer.is_finished()
            # We have to bold just the username in the event of a win.
            # So we can't just f'{member}' here.
            name = f'{title} {use_flag}'
            value = f'{chr(char)} {racer.animal} {member}'
            embed.add_field(name=name, value=value, inline=False)

        await self.ctx.send(embed=embed)

    async def run(self):
        start = time.perf_counter()
        await self._loop()
        seconds = time.perf_counter() - start
        await self._display_winners()

    def top_racers(self, n=3):
        return heapq.nlargest(n, self.players.items(), key=lambda i: i[1].distance)

    def is_completed(self):
        return any(r.is_finished() for r in self.players.values())

    @property
    def leader(self):
        return max(self.players, key=lambda m: self.players[m].distance)

    async def stop(self, force=True):
        pass


class Racing:
    def __init__(self, bot):
        self.bot = bot
        self.manager = SessionManager()

    @commands.command()
    async def race(self, ctx, bet: int=0):
        session = self.manager.get_session(ctx.channel)
        if session is not None:
            if session.running:
                return await ctx.send('You were a little late to the party!')
            if session.already_joined(ctx.author):
                return await ctx.send("You're already in the race!")

            session.add_member(ctx.author)
            return await ctx.send(f"Okay, {ctx.author.mention}. Good luck!")

        with self.manager.temp_session(ctx.channel, RacingSession(ctx)) as inst:
            inst.add_member(ctx.author)
            await ctx.send(f'Race has started! Type {ctx.prefix}{ctx.invoked_with} to join!')

            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(inst.wait_until_full(), timeout=30)

            if not inst.has_enough_members():
                return await ctx.send("Can't start race. Not enough people :(")
            await asyncio.sleep(random.uniform(0.25, 0.75))
            await inst.run()

    async def race_close(self):
        """Stops registration of a race early."""
        pass

def setup(bot):
    bot.add_cog(Racing(bot))