import asyncio
import collections
import discord
import random
import time

from discord.ext import commands

from .utils.cd import cd
from .utils.misc import str_join

# Yes I know this is a copy of https://github.com/Rapptz/discord.py/blob/master/examples/playlist.py
# But hey, no point reinventing the wheel

if not discord.opus.is_loaded():
    # the 'opus' library here is opus.dll on windows
    # or libopus.so on linux in the current directory
    # you should replace this with the location the
    # opus library is located in and with the proper filename.
    # note that on windows this DLL is automatically provided for you
    discord.opus.load_opus('opus')

def _time(self):
    return time.time() - self._start

discord.voice_client.StreamPlayer.time = property(_time)

class ShuffableQueue(asyncio.Queue):
    # Probably not safe
    def __delitem__(self, idx):
        del self._queue[idx]
        
    def __getitem__(self, idx):
        return self._queue[idx]

    def __setitem__(self, idx, val):
        self._queue[idx] = val
    
    def __iter__(self):
        return iter(self._queue)

    def clear(self):
        self._queue.clear()
    
    def shuffle(self):
        queue = list(self._queue)
        random.shuffle(queue)
        self._queue = collections.deque(queue)
        
class VoiceEntry:
    def __init__(self, message, player):
        self.requester = message.author
        self.channel = message.channel
        self.player = player

    def __str__(self):
        fmt = '**{0.title}** uploaded by {0.uploader} and requested by {1.display_name}'
        duration = self.player.duration
        if duration:
            fmt = fmt + ' [length: {0[0]}m {0[1]}s]'.format(divmod(duration, 60))
        return fmt.format(self.player, self.requester)

    @property
    def required_skip_votes(self):
        return len(self.channel.voice_members)

class VoiceState:
    def __init__(self, bot):
        self.current = None
        self.voice = None
        self.bot = bot
        self.play_next_song = asyncio.Event()
        self.songs = ShuffableQueue()
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
            return
        self.skip_votes.clear()
        if self.is_playing():
            self.player.stop()
        
    def shuffle(self):
        self.songs.shuffle()

    def clear(self):
        self.songs.clear()

    def toggle_next(self):
        self.bot.loop.call_soon_threadsafe(self.play_next_song.set)

    async def audio_player_task(self):
        while True:
            self.play_next_song.clear()
            if self.current is not None:
                await self.bot.send_message(self.current.channel, 'Finished playing ' + str(self.current))
            self.current = await self.songs.get()
            await self.bot.send_message(self.current.channel, 'Now playing ' + str(self.current))
            self.current.player.start()
            await self.play_next_song.wait()
            
    @property
    def player(self):
        return self.current.player

class Music:
    """Voice related commands.

    Works in multiple servers at once.
    """
    __prefix__ = '&'
    def __init__(self, bot):
        self.bot = bot
        self.voice_states = collections.defaultdict(lambda: VoiceState(self.bot))

    def get_voice_state(self, server):
        return self.voice_states[server]

    async def create_voice_client(self, channel):
        voice = await self.bot.join_voice_channel(channel)
        state = self.get_voice_state(channel.server)
        state.voice = voice

    def __unload(self):
        for state in self.voice_states.values():
            try:
                state.audio_player.cancel()
                if state.voice:
                    self.bot.loop.create_task(state.voice.disconnect())
            except:
                pass

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
            await self.bot.say('Ready to play audio in ' + channel.name)

    @commands.command(pass_context=True, no_pm=True)
    async def summon(self, ctx):
        """Summons the bot to join your voice channel."""
        summoned_channel = ctx.message.author.voice_channel
        if summoned_channel is None:
            await self.bot.say('You are not in a voice channel.')
            return False

        state = self.get_voice_state(ctx.message.server)
        if state.voice is None:
            state.voice = await self.bot.join_voice_channel(summoned_channel)
        else:
            await state.voice.move_to(summoned_channel)

        return True

    @commands.command(pass_context=True, no_pm=True)
    async def play(self, ctx, *, song : str):
        """Plays a song.

        If there is a song currently in the queue, then it is
        queued until the next song is done playing.

        This command automatically searches as well from YouTube.
        The list of supported sites can be found here:
        https://rg3.github.io/youtube-dl/supportedsites.html
        """
        state = self.get_voice_state(ctx.message.server)
        opts = {
            'default_search': 'auto',
            'quiet': True,
        }

        if state.voice is None:
            success = await ctx.invoke(self.summon)
            if not success:
                return

        try:
            with cd(r"dependencies\ffmpeg\bin"):
                player = await state.voice.create_ytdl_player(song, ytdl_options=opts, after=state.toggle_next)
        except Exception as e:
            fmt = 'An error occurred while processing this request: ```py\n{}: {}\n```'
            await self.bot.send_message(ctx.message.channel, fmt.format(type(e).__name__, e))
        else:
            player.volume = 0.6
            entry = VoiceEntry(ctx.message, player)
            await self.bot.say('Enqueued ' + str(entry))
            await state.songs.put(entry)

    @commands.command(pass_context=True, no_pm=True)
    async def volume(self, ctx, value : int):
        """Sets the volume of the currently playing song."""

        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.volume = value / 100
            await self.bot.say('Set the volume to {:.0%}'.format(player.volume))

    @commands.command(pass_context=True, no_pm=True)
    async def pause(self, ctx):
        """Pauses the currently played song."""
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.pause()

    @commands.command(pass_context=True, no_pm=True)
    async def resume(self, ctx):
        """Resumes the currently played song."""
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.resume()

    @commands.command(pass_context=True, no_pm=True)
    async def stop(self, ctx):
        """Stops playing audio and leaves the voice channel.

        This also clears the queue.
        """
        server = ctx.message.server
        state = self.get_voice_state(server)

        if state.is_playing():
            player = state.player
            player.stop()

        try:
            state.audio_player.cancel()
            del self.voice_states[server]
            await state.voice.disconnect()
        except:
            pass

    @commands.command(pass_context=True, no_pm=True)
    async def skip(self, ctx, num: int=None, force_skip=False):
        """Vote to skip a song. The song requester can automatically skip.

        3 skip votes are needed for the song to be skipped.
        """

        if num == '-f':
            num = None
            force_skip = True
        else:
            force_skip = force_skip == '-f'

        state = self.get_voice_state(ctx.message.server)
        if not state.is_playing():
            await self.bot.say('Not playing any music right now...')
            return

        try:
            current = state.current if num is None else state.songs[num]
        except IndexError:
            await self.bot.say("Song {} doesn't exist".format(num))
            return
        
        voter = ctx.message.author
        if voter == current.requester:
            await self.bot.say('Requester requested skipping song...')
            state.skip(num)
            await self.bot.say("Removing " + str(current))
        elif voter.id not in state.skip_votes:
            state.skip_votes.add(voter.id)
            total_votes = len(state.skip_votes)
            required_skip_votes = current.required_skip_votes
            if total_votes >= required_skip_votes:
                await self.bot.say('Skip vote passed, skipping song...')
                state.skip(num)
                await self.bot.say("Removing " + str(current))
            else:
                await self.bot.say('Skip vote added, currently at [{}/{}]'.format(total_votes, required_skip_votes))
        else:
            await self.bot.say('You have already voted to skip this song.')

    @commands.command(pass_context=True, no_pm=True, aliases=['np'])
    async def nowplaying(self, ctx):
        """Shows info about the currently played song."""

        state = self.get_voice_state(ctx.message.server)
        if state.current is None:
            await self.bot.say('Not playing anything.')
        else:
            skip_count = len(state.skip_votes)
            fmt = 'Now {0.player.time}s into playing {0} [skips: {1}/{0.required_skip_votes}]'
            await self.bot.say(fmt.format(state.current, skip_count))

    @commands.group(pass_context=True, no_pm=True)
    async def queue(self, ctx):
        """Super command for operating on queues"""
        pass

    @queue.command(pass_context=True, no_pm=True)
    async def clear(self, ctx):
        """Clears the queue

        This doesn't stop the current song or disconnect me from the voice channel
        Use 'stop' for that
        """
        state = self.get_voice_state(ctx.message.server)
        state.clear()
    
    @queue.command(pass_context=True, no_pm=True)
    async def shuffle(self, ctx):
        """Shuffle the queue"""

        state = self.get_voice_state(ctx.message.server)
        state.shuffle()

    @queue.command(pass_context=True, name="list", no_pm=True)
    async def list_(self, ctx, limit=10):
        """Shows the first [limit] songs that are gonna be played

        This does not include the current song
        (use nowplaying to find that out)
        """

        state = self.get_voice_state(ctx.message.server)
        await self.bot.say(str_join('\n', state.songs))

def setup(bot):
    bot.add_cog(Music(bot))
