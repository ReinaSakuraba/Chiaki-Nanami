import asyncio
import contextlib
import discord
import enum
import functools
import itertools
import os
import random
import re
import time

from collections import defaultdict
from discord.ext import commands
from functools import lru_cache, wraps

from .utils import checks
from .utils.compat import url_color
from .utils.errors import ResultsNotFound
from .utils.misc import str_join, duration_units, usage

# Can't use a with statement here...
_temporary_env = dict(os.environ)
os.environ["PATH"] += os.pathsep + r"dependencies\ffmpeg\bin"

# Yes I know this is a copy of https://github.com/Rapptz/discord.py/blob/master/examples/playlist.py
# But hey, no point reinventing the wheel

if not discord.opus.is_loaded():
    # the 'opus' library here is opus.dll on windows
    # or libopus.so on linux in the current directory
    # you should replace this with the location the
    # opus library is located in and with the proper filename.
    # note that on windows this DLL is automatically provided for you
    discord.opus.load_opus('opus')

discord.voice_client.StreamPlayer.time = property(lambda self: time.time() - self._start)

def requires_user_in_voice_channel(func):
    @wraps(func)
    async def wrapper(self, ctx, *args, **kwargs):
        if ctx.message.author.voice_channel is None:
            return await self.bot.reply('You are not in a voice channel.')
        return await func(self, ctx, *args, **kwargs)
    return wrapper

class AcceptableURL(enum.Enum):
    YOUTUBE = re.compile(r'^(https?\:\/\/)?(www\.|m\.)?(youtube\.com|youtu\.?be)\/.+$')
    SOUNDCLOUD = re.compile(r'^(https?\:\/\/)?(www\.)?(soundcloud\.com\/)')

    @classmethod
    def sanitize(cls, url):
        for link_pattern in cls:
            if link_pattern.value.match(url):
                break
        else:
            raise commands.BadArgument("The given url is not acceptable for playing music")

class IterableQueue(asyncio.Queue):
    # Probably not thread-safe
    __len__ = asyncio.Queue.qsize

    def __delitem__(self, idx):
        del self._queue[idx]

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            start, stop, step = idx.start, idx.stop, idx.step
            if start and start < 0: idx.start += len(self._queue)
            if stop and stop < 0:  idx.stop += len(self._queue)
            return type(self._queue)(itertools.islice(self._queue, start, stop, step))
        return self._queue[idx]

    def __setitem__(self, idx, val):
        self._queue[idx] = val

    def clear(self):
        self._queue.clear()

    def shuffle(self):
        random.shuffle(self._queue)

    def reverse(self):
        self._queue.reverse()

async def _get_info(player, loop):
    ytdl = player.yt
    func = functools.partial(ytdl.extract_info, player.url, download=False)
    info = await loop.run_in_executor(None, func)
    if "entries" in info:
        info = info['entries'][0]
    return info

class VoiceEntry:
    def __init__(self, message, player):
        self.requester = message.author
        self.channel = message.channel
        self.player = player

    def __str__(self):
        fmt = '**{0.title}** uploaded by {0.uploader} and requested by {1.display_name}'
        duration = self.player.duration
        if duration:
            fmt += f' [length: {duration_units(duration)}]'
        return fmt.format(self.player, self.requester)

    async def colour_embed(self):
        embed = self.embed
        embed.colour = await url_color(self.info['thumbnail'])
        return embed

    @discord.utils.cached_property
    def embed(self):
        requester, player, info = self.requester, self.player, self.info
        avatar = requester.avatar_url or requester.default_avatar_url

        return (discord.Embed(title=player.title, description=f"Uploaded by {player.uploader}", url=info['webpage_url'])
               .set_author(name=f"Requested by {requester.display_name}", icon_url=avatar)
               .set_thumbnail(url=info.get('thumbnail'))
               .set_footer(text=f'Duration: {duration_units(player.duration)}')
               )

    @property
    def required_skip_votes(self):
        return len(self.channel.voice_members)

WAIT_FOR_SONG_TIME = 60
SHOW_CURRENT_SONG_AS_EMBED = False # disabled due to blocking

class VoiceState:
    def __init__(self, bot):
        self.current = None
        self.voice = None
        self.bot = bot
        self.play_next_song = asyncio.Event()
        self.got_next_song = asyncio.Event()
        self.songs = IterableQueue()
        self.skip_votes = set() # a set of user_ids that voted
        self.audio_player = self.bot.loop.create_task(self.audio_player_task())

    def is_playing(self):
        if self.voice is None or self.current is None:
            return False

        player = self.current.player
        return not player.is_done()

    def skip(self, idx=None):
        if idx is not None:
            del self.songs[idx]
        else:
            self.skip_votes.clear()
            if self.is_playing():
                self.current.player.stop()

    def shuffle(self):
        random.shuffle(self.songs)

    def clear(self):
        self.songs.clear()

    def toggle_next(self):
        self.bot.loop.call_soon_threadsafe(self.play_next_song.set)

    def user_request_count(self, user):
        return len([entry for entry in self.songs if entry.requester == user])

    async def get_next_song(self):
        try:
            self.current = await asyncio.wait_for(self.songs.get(), WAIT_FOR_SONG_TIME)
        except asyncio.TimeoutError:
            await self.stop()
        else:
            self.bot.loop.call_soon_threadsafe(self.got_next_song.set)

    async def stop(self):
        await self.bot.send_message(self.current.channel, "Disconnecting because no one requested a song :(")
        await self.voice.disconnect()
        self.voice = self.current = None

    async def wait_until_next_song(self):
        await self.get_next_song()
        await self.got_next_song.wait()
        if self.current is None:
            await self.get_next_song()

    async def announce_next_song(self):
        if SHOW_CURRENT_SONG_AS_EMBED:
            message = await self.bot.send_message(self.current.channel, "Playing song...", embed=self.current.embed)
        else:
            message = await self.bot.send_message(self.current.channel, f"Playing song...\n{self.current}")
        #for emoji in ['\u23F8', '\u23F9', '\u23E9', ]:
        #    await self.bot.add_reaction(message, emoji)
        self.current_message = message

    async def audio_player_task(self):
        while True:
            self.got_next_song.clear()
            self.play_next_song.clear()
            if self.current is not None:
                await self.bot.send_message(self.current.channel, f'Finished playing {self.current}')
            await self.wait_until_next_song()
            await self.announce_next_song()
            self.current.player.start()
            await self.play_next_song.wait()

    @property
    def player(self):
        return self.current.player

# TODO: make this constant server-specific
MAX_SONG_REQUESTS = 10

class Music:
    """Voice related commands.

    Works in multiple servers at once.
    """
    __prefix__ = '&'
    def __init__(self, bot):
        self.bot = bot
        self.voice_states = defaultdict(lambda: VoiceState(self.bot))

    def get_voice_state(self, server):
        return self.voice_states[server]

    async def create_voice_client(self, channel):
        voice = await self.bot.join_voice_channel(channel)
        state = self.get_voice_state(channel.server)
        state.voice = voice

    # *Wishes __unload could be a coroutine...*
    def __unload(self):
        print("Music unloading")
        for state in self.voice_states.values():
            with contextlib.suppress(BaseException):
                state.audio_player.cancel()
                if state.voice:
                    self.bot.loop.create_task(state.voice.disconnect())

    async def _create_song(self, ctx, song, state):
        opts = {
            'default_search': 'auto',
            'quiet': True,
        }
        try:
            player = await state.voice.create_ytdl_player(song, ytdl_options=opts, after=state.toggle_next)
        except Exception as e:
            fmt = f'An error occurred while processing this request: ```py\n{type(e).__name__}: {e}\n```'
            await self.bot.send_message(ctx.message.channel, fmt)
            raise e
        else:
            player.volume = 0.6
            entry = VoiceEntry(ctx.message, player)
            entry.info = await _get_info(player, state.voice.loop)
            AcceptableURL.sanitize(entry.info['webpage_url'])
            await state.songs.put(entry)
            state.got_next_song.set()
            return entry

    def _get_state_song(self, state, idx):
        try:
            return state.current if idx is None else state.songs[idx]
        except IndexError:
            raise ResultsNotFound(f"Song #{idx} doesn't exist")

    @commands.command(pass_context=True, no_pm=True)
    async def join(self, ctx, *, channel : discord.Channel):
        """Joins a voice channel."""
        try:
            await self.create_voice_client(channel)
        except discord.ClientException:
            await self.bot.say('Already in a voice channel...')
        except discord.InvalidArgument:
            await self.bot.say('This is not a voice channel...')
        else:
            await self.bot.say(f'Ready to play audio in **{channel}**!')

    @commands.command(pass_context=True, no_pm=True)
    @requires_user_in_voice_channel
    async def summon(self, ctx):
        """Summons the bot to join your voice channel."""
        summoned_channel = ctx.message.author.voice_channel

        state = self.get_voice_state(ctx.message.server)
        # The module could've unloaded while the bot was in the voice channel.
        # Meaning that the module doesn't recognize that the bot is in a voice channel
        if state.voice is None:
            state.voice = (self.bot.voice_client_in(ctx.message.server)
                           or await self.bot.join_voice_channel(summoned_channel))
        else:
            await state.voice.move_to(summoned_channel)

    @commands.command(pass_context=True, no_pm=True)
    @requires_user_in_voice_channel
    async def play(self, ctx, *, song : str):
        """Plays a song.

        If there is a song currently in the queue, then it is
        queued until the next song is done playing.

        This command automatically searches as well from YouTube.
        The list of supported sites can be found here:
        https://rg3.github.io/youtube-dl/supportedsites.html
        """

        state = self.get_voice_state(ctx.message.server)

        if state.voice is None:
            await ctx.invoke(self.summon)

        if state.user_request_count(ctx.message.author) > MAX_SONG_REQUESTS:
            return await self.bot.reply("You have already requested too many songs on this channel. "
                                       f"The maximum number of songs you can request is {MAX_SONG_REQUESTS}.")
            

        entry = await self._create_song(ctx, song, state)
        await self.bot.say(f'Enqueued {entry}')

    @commands.command(pass_context=True, no_pm=True)
    @commands.cooldown(rate=1, per=90, type=commands.BucketType.server)
    @requires_user_in_voice_channel
    async def repeat(self, ctx, times: int, idx: int=None):
        """Repeats a song a given amount of times

        If idx is not specified, it defaults to the current song.
        To prevent abuse, this command can only be called every 90 seconds.
        """
        if times > 5:
            raise commands.BadArgument("You cannot repeat a song more than 5 times!")
        if times <= 0:
            raise commands.BadArgument(f"How am I supposed to repeat a song {times} times?")

        state = self.get_voice_state(ctx.message.server)
        current = self._get_state_song(state, idx)

        for _ in range(times):
            self.bot.loop.create_task(self._create_song(ctx, current.player.url, state))

        state.got_next_song.set()
        await self.bot.say(f"Successfully repeated {current} {times} times!")

    @commands.command(pass_context=True, no_pm=True)
    async def volume(self, ctx, value: int):
        """Sets the volume of the currently playing song."""

        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.volume = value / 100
            await self.bot.say(f'Set the volume to **{player.volume:.0%}**')

    @commands.command(pass_context=True, no_pm=True)
    @requires_user_in_voice_channel
    async def pause(self, ctx):
        """Pauses the currently played song."""
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            state.player.pause()
        await self.bot.say("Currently paused.")

    @commands.command(pass_context=True, no_pm=True)
    @requires_user_in_voice_channel
    async def resume(self, ctx):
        """Resumes the currently played song."""
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            state.player.resume()
        await self.bot.say("Resumed.")

    @commands.command(pass_context=True, no_pm=True)
    
    @requires_user_in_voice_channel
    async def stop(self, ctx):
        """Stops playing audio and leaves the voice channel.

        This also clears the queue.
        """
        server = ctx.message.server
        state = self.voice_states.pop(server, None)

        if state.is_playing():
            state.player.stop()

        with contextlib.suppress(BaseException):
            state.audio_player.cancel()
            await state.voice.disconnect()

    @commands.command(pass_context=True, no_pm=True)
    @requires_user_in_voice_channel
    @usage('skip', 'skip -f', 'skip 69 -f')
    async def skip(self, ctx, num=None, force_skip=''):
        """Vote to skip a song. The song requester can automatically skip.

        1/3 of the number of members in the current voice channel is the number
        of skip votes needed for the song to be skipped.

        Alternatively you can specify an -f flag to force skip a song.
        This can only be used by moderators.

        Negative indices are allowed. They just start from the end of the queue rather than the beginning.
        """

        if num == '-f':
            num = None
            force_skip = True
        else:
            if num is not None:
                num = int(num)
                num -= num > 0
            force_skip = force_skip == '-f'

        state = self.get_voice_state(ctx.message.server)
        if not state.is_playing():
            return await self.bot.say('Not playing any music right now...')

        current = self._get_state_song(state, num)

        async def inner_skip(msg):
            await self.bot.say(msg)
            state.skip(num)
            await self.bot.say(f"Removing {current}")

        if force_skip and checks.role_predicate(ctx, checks.ChiakiRole.mod):
           return await inner_skip('Force skip...')

        voter = ctx.message.author
        if voter == current.requester:
            await inner_skip('Requester requested skipping song...')
        elif voter.id not in state.skip_votes:
            state.skip_votes.add(voter.id)
            total_votes = len(state.skip_votes)
            required_skip_votes = current.required_skip_votes
            if total_votes >= required_skip_votes:
                await inner_skip('Skip vote passed, skipping song...')
            else:
                await self.bot.say(f'Skip vote added, currently at [**{total_votes}**/{required_skip_votes}]')
        else:
            await self.bot.say('You have already voted to skip this song.')

    @commands.command(pass_context=True, no_pm=True, aliases=['np'])
    async def nowplaying(self, ctx):
        """Shows info about the currently played song."""

        state = self.get_voice_state(ctx.message.server)
        current = state.current
        if current is None:
            await self.bot.say('Not playing anything.')
            return
        skip_count = len(state.skip_votes)
        fmt = 'Now {2} into playing {0} [skips: {1}/{0.required_skip_votes}]'
        await self.bot.say(fmt.format(current, skip_count, duration_units(current.player.time)))

    @commands.group(pass_context=True, no_pm=True)
    async def queue(self, ctx):
        """Super command for operating on queues"""
        pass

    @queue.command(name="clear", pass_context=True, no_pm=True)
    
    async def clear(self, ctx):
        """Clears the queue

        This doesn't stop the current song or disconnect me from the voice channel
        Use 'stop' for that
        """
        state = self.get_voice_state(ctx.message.server)
        state.clear()
        await self.bot.reply("Successfully cleared the queue!")

    @queue.command(name="shuffle", pass_context=True, no_pm=True)
    async def queue_shuffle(self, ctx):
        """Shuffle the queue"""

        state = self.get_voice_state(ctx.message.server)
        state.shuffle()
        await self.bot.say(":ok_hand:")
        await self.bot.reply("Successfully shuffled the queue!")

    @queue.command(name="list", pass_context=True, no_pm=True)
    async def queue_list(self, ctx, limit=10):
        """Shows the next [limit] songs that are about be played. Defaults to the next 10 songs.

        This does not include the current song
        (use nowplaying to find that out)
        """

        state = self.get_voice_state(ctx.message.server)
        await self.bot.say(str_join('\n', state.songs[:limit]))

    @queue.command(name="nextsong", pass_context=True, no_pm=True, aliases=['next'])
    async def queue_next_song(self, ctx):
        """Shows the next song that will be played"""

        state = self.get_voice_state(ctx.message.server)
        try:
            msg = str(state.songs[0])
        except IndexError:
            msg = "There is no song pending... I think."
        await self.bot.say(msg)

    # TODO: Use reactions to control the music playing
    async def on_reaction_add(self, reaction, user):
        pass

    async def on_reaction_remove(self, reaction, user):
        pass

def setup(bot):
    bot.add_cog(Music(bot))

def teardown(bot):
    os.environ.clear()
    os.environ.update(_temporary_env)
