import asyncio
import contextlib
import discord
import functools
import glob
import operator
import os
import random
import string

from collections import namedtuple
from discord.ext import commands

from .manager import SessionManager

from ..utils import errors
from ..utils.misc import base_filename

_template = '''
  011111
  0    2
  0    3      Guessed : {guesses}
  0   546     Average : {avg}%
  0    4
  0   7 8
 _0_
|   |______
|          |
|__________|
'''

_symbols = string.octdigits + '8'
_blanks = dict.fromkeys(map(ord, _symbols), ' ')

hangman_drawings = []
for fake, real in zip(_symbols, '|_|o|/\\/\\'):
    hangman_drawings.append(_template.translate(_blanks))
    _template = _template.replace(fake, real)
hangman_drawings.append(_template)
del _template

GameResult = namedtuple('GameResult', 'success message')
GameResult.__bool__ = operator.attrgetter('success')


# TODO: embed-fuck this
class HangmanSession:
    def __init__(self, ctx, word):
        self.ctx = ctx
        self.word = word
        self._lowered_word = self.word.lower()
        self.blanks = ['_' if letter in string.ascii_letters else letter
                       for letter in word]
        self.guesses = []
        self.fails = 0
        self.cooldowns = {}
        self.force_closed = False
        self._finished = asyncio.Event()
        self._runner = None

    def _verify_guess(self, guess):
        lowered = guess.lower()
        if lowered in self.guesses:
            return GameResult(success=None, message=f"{guess} was already guessed!")

        if len(lowered) != 1:      # full word
            if lowered == self._lowered_word:
                return GameResult(success=True, message=f"You guessed it!")
            return GameResult(success=False, message=f"That is not the word :(")

        if lowered in self._lowered_word    :
            return GameResult(success=True, message=f"That is in the word :D")
        return GameResult(success=False, message=f"That is not in the word :(")

    def _check_message(self, message):
        if message.channel != self.ctx.channel:
            return False

        # check for cooldown
        last_time = self.cooldowns.get(message.author)
        if last_time is not None:
            if (message.created_at - last_time).total_seconds() < 1:
                print('no')
                return False

        content = message.content
        return len(content) == 1 or content.startswith('*')

    async def __run(self):
        message = await self.ctx.send(self.format_message('Hangman game started!'))

        while True:
            guess = await self.ctx.bot.wait_for('message', check=self._check_message)
            self.cooldowns[guess.author] = guess.created_at
            content = guess.content
            content = content[len(content) > 1:]

            ok, result = self._verify_guess(content)
            if ok:
                self.blanks[:] = (c if c.lower() in content else v for c, v in zip(self.word, self.blanks))
            else:
                self.fails += ok is not None
            self.guesses.append(content.lower())
            await message.edit(content=f'{guess.author.mention}, {self.format_message(result)}')
            if self.is_completed() or self.is_dead():
                break

        self._finished.set()

    async def run(self):
        self._runner = self.ctx.bot.loop.create_task(self.__run())
        await self._finished.wait()

        message = f'The answer was {self.word}'
        return GameResult(success=not self.is_dead(), message=message)

    async def stop(self, force=False):
        self.force_closed = True
        self._runner.cancel()
        self._finished.set()

    def format_message(self, message):
        return f'{message}\n{self.game_screen()}'

    def game_screen(self):
        formats = {
            'guesses': ', '.join(self.guesses),
            'avg': self.average() * 100
        }

        screen = hangman_drawings[self.fails].format(**formats)
        return f'```\n{screen}\n{" ".join(self.blanks)}```'

    def average(self):
        return 1 - (self.fails / len(self.guesses)) if self.fails else 1

    def is_completed(self):
        return '_' not in self.blanks

    def is_dead(self):
        return self.fails >= len(hangman_drawings)

def _load_hangman(filename):
    with open(filename) as f:
        return [line.strip() for line in f]


class Hangman:
    """So you don't have to hang people in real life."""
    FILE_PATH = os.path.join('.', 'data', 'games', 'hangman')

    def __init__(self, bot):
        self.bot = bot
        self.manager = SessionManager()
        self.bot.loop.create_task(self._load_categories())

    def __unload(self):
        self.manager.cancel_all(loop=self.bot.loop)

    async def _load_categories(self):
        load_async = functools.partial(self.bot.loop.run_in_executor, None, _load_hangman)
        files = glob.glob(f'{self.FILE_PATH}/*.txt')
        load_tasks = (load_async(name) for name in files)
        file_names = (base_filename(name) for name in files)

        self.default_categories = dict(zip(file_names, await asyncio.gather(*load_tasks)))
        print('everything is ok now')

    async def _get_category(self, ctx, category):
        lowered = category.lower()
        with contextlib.suppress(KeyError):
            return self.default_categories[lowered]

        custom_category = self.custom_categories[ctx.guild].get(lowered)
        if custom_category is None:
            raise commands.BadArgument(f"Category {category} doesn't exist... :(")

    @staticmethod
    def _get_random_word(words):
        if all(len(word) < 4 for word in words):
            raise errors.InvalidUserArgument("Category doesn't have enough words with at least 4 letters")

        return random.choice(words)

    @commands.group(invoke_without_command=True)
    async def hangman(self, ctx, category):
        """It's hangman..."""
        if self.manager.session_exists(ctx.channel):
             return await ctx.send("A hangman game is already running in this channel...")
        
        words = await self._get_category(ctx, category)
        word = self._get_random_word(words)
        with self.manager.temp_session(ctx.channel, HangmanSession(ctx, word)) as inst:
            success, message = await inst.run()
            if inst.force_closed:
                return

            game_over_message = 'You did it!' if success else 'Noooo you lost :('
            await ctx.send(f'{game_over_message} {message}') 

    @hangman.command(name='stop')
    async def hangman_stop(self, ctx):
        instance = self.manager.get_session(ctx.channel)
        if instance is None:
            return await ctx.send('There is no hangman running right now...')

        await instance.stop()
        await ctx.send('Hangman stopped.')

def setup(bot):
    bot.add_cog(Hangman(bot))
