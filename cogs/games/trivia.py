import asyncio
import collections
import contextlib
import discord
import glob
import itertools
import os
import random

from discord.ext import commands
from fuzzywuzzy import process

from .manager import SessionManager
from ..utils.misc import base_filename, emoji_url, load_async
from ..utils.paginator import EmbedFieldPages


Question = collections.namedtuple('Question', 'question answers')


QUESTION_GAME_TIMEOUT = 60
class TriviaSession:
    def __init__(self, ctx, category):
        self.ctx = ctx
        self.category = category
        self.finished = asyncio.Event()
        self._answered = asyncio.Event()
        self.scoreboard = collections.Counter()
        self._runner = self._time_out_checker = None

    def _check_answer(self, m):
        if m.channel != self.ctx.channel:
            return False
        # Prevent other bots from accidentally answering the question
        # This issue has happened numberous times with other bots.
        if m.author.bot:
            return False
        self._answered.set()
        _, ratio = process.extractOne(m.content, self.question.answers)
        return ratio >= 85

    def _question_embed(self, n):
        leader = self.leader
        leader_text = f'{leader[0]} with {leader[1]} points' if leader else None
        description = self.category.get('description', discord.Embed.Empty)
        return (discord.Embed(description=description, colour=random.randint(0, 0xFFFFFF))
               .set_author(name=self.category.get('title', 'Trivia'))
               .add_field(name=f'Question #{n}', value=self.question.question)
               .set_footer(text=f'Current leader: {leader_text}')
               )

    def _answer_embed(self, answerer, action):
        description = f'The answer was **{self.question.answers[0]}**.'
        return (discord.Embed(colour=0x00FF00, description=description)
               .set_author(name=f'{answerer} {action}!')
               .set_thumbnail(url=answerer.avatar_url)
               .set_footer(text=f'{answerer} now has {self.scoreboard[answerer]} points.')
               )

    @staticmethod
    def _timeout_embed(answer):
        return (discord.Embed(description=f'The answer was **{answer}**', colour=0xFF0000)
               .set_author(name='Times up!', icon_url=emoji_url('\N{ALARM CLOCK}'))
               .set_footer(text='No one got any points :(')
               )

    async def _loop(self):
        for q in itertools.count(1):
            self.question = self.next_question()
            await self.ctx.send(embed=self._question_embed(q))
            try:
                msg = await self.ctx.bot.wait_for('message', timeout=20, check=self._check_answer)
            except asyncio.TimeoutError:
                await self.ctx.send(embed=self._timeout_embed(self.question.answers[0]))
            else:
                self.scoreboard[msg.author] += 1
                if self.scoreboard[msg.author] >= 10:
                    await self.ctx.send(embed=self._answer_embed(msg.author, 'wins the game'))
                    return msg.author
                await self.ctx.send(embed=self._answer_embed(msg.author, 'got it'))
            finally:
                await asyncio.sleep(random.uniform(1.5, 3))

    async def _check_time_out(self):
        while True:
            await asyncio.wait_for(self._answered.wait(), QUESTION_GAME_TIMEOUT)
            self._answered.clear()

    async def run(self):
        self._runner = asyncio.ensure_future(self._loop())
        done, pending = await asyncio.wait([self._runner, self._check_time_out()],
                                           return_when=asyncio.FIRST_COMPLETED)
        try:
            return await done.pop()
        finally:
            # When TimeoutError is raised in the second coro, it doesn't stop the
            # asyncio.wait due to the return_when kwarg.
            self._runner.cancel()
            # Also for some reason the timeout check task doesn't get cancelled.
            pending.pop().cancel()

    def stop(self, force=False):
        self._runner.cancel()

    def next_question(self):
        return Question(**random.choice(self.category['questions']))

    @property
    def leader(self):
        leaderboard = self.leaderboard
        return leaderboard[0] if leaderboard else None

    @property
    def leaderboard(self):
        return self.scoreboard.most_common()


class Trivia:
    """It's trivia and stuff"""
    FILE_PATH = os.path.join('.', 'data', 'games', 'trivia')

    def __init__(self, bot):
        self.bot = bot
        self.manager = SessionManager()
        self.custom_categories = collections.defaultdict(dict)
        self.default_categories = {}
        self.bot.loop.create_task(self._load_categories())

    # def __unload(self):
        # stop running any currently running trivia games
        # self.manager.cancel_all(loop=self.bot.loop)

    def all_categories(self, guild):
        # This will be ChainMapped with custom categories
        return self.default_categories

    async def _load_categories(self):
        files = glob.glob(f'{self.FILE_PATH}/*.json')
        load_tasks = (load_async(name) for name in files)
        file_names = (base_filename(name) for name in files)

        self.default_categories.update(zip(file_names, await asyncio.gather(*load_tasks)))
        print('everything is ok now')

    async def _get_category(self, ctx, category):
        lowered = category.lower()
        with contextlib.suppress(KeyError):
            return self.default_categories[lowered]

        custom_category = self.custom_categories[ctx.guild].get(lowered)
        if custom_category is None:
            raise commands.BadArgument(f"Category {category} doesn't exist... :(")

        # TODO: use github gist or pastebin for custom categories

    @staticmethod
    def _leaderboard_message(inst, *, past=False):
        results = inst.leaderboard
        verb = 'had' if past else 'has'
        formatted = (f'**{u}** {verb} **{p}** point{"s" * (p != 1)}' for u, p in results)
        return ('\n'.join(formatted) if results else 'No one got any points :(')

    @staticmethod
    def _leaderboard_embed(inst, title, field_name, *, past=False):
        message = Trivia._leaderboard_message(inst, past=past)
        return (discord.Embed(title=title, colour=0x00FF00)
               .add_field(name=field_name, value=message)
               )

    @commands.group(aliases=['t'], invoke_without_command=True)
    async def trivia(self, ctx, category):
        """It's trivia..."""
        if self.manager.session_exists(ctx.channel):
             return await ctx.send("A trivia game is already running in this channel...")

        category = await self._get_category(ctx, category)
        with self.manager.temp_session(ctx.channel, TriviaSession(ctx, category)) as inst:
            winner = await inst.run()

            await asyncio.sleep(1.5)
            results_embed = self._leaderboard_embed(inst, 'Trivia Game Ended', 'Final Results', past=True)
            await ctx.send(embed=results_embed)

    @trivia.error
    async def trivia_error(self, ctx, error):
        if isinstance(error.__cause__, asyncio.TimeoutError):
            await ctx.send('Where did everyone go... ;-;')

    @trivia.command(name='categories')
    async def trivia_categories(self, ctx):
        pages = [(k, v.get('description', 'No description'))
                 for k, v in self.all_categories(ctx.guild).items()]
        embeds = EmbedFieldPages(ctx, pages, title=f'List of Categories for {ctx.guild}',
                                 colour=discord.Colour.blurple())
        await embeds.interact()

    @trivia.command(name='stop', aliases=['quit'])
    async def trivia_stop(self, ctx):
        """Stops a running game of trivia"""
        game = self.manager.get_session(ctx.channel)
        if game is None:
            return await ctx.send("There is no trivia game to stop... :|")

        game.stop()
        await ctx.send(f"Trivia stopped...")

    @trivia.command(name='score', aliases=['leaderboard'])
    async def trivia_score(self, ctx):
        """Shows the current score of a running trivia game"""
        trivia_game = self.manager.get_session(ctx.channel)
        if trivia_game is None:
             return await ctx.send("There is no trivia game in this channel")

        score_embed = self._leaderboard_embed(trivia_game, 'Current Leaderboard', '\u200b')
        await ctx.send(embed=score_embed)

    async def _json_from_url(self, url):
        async with self.session.get(url) as resp:
            return await resp.json

    async def trivia_addcustom(self, ctx, *links):
        """Adds a custom game of trivia.

        This can take either a link to pastebin, or a JSON attachment.
        The format of the file must be something like this:
        ```js
        {
            "title": "name of your trivia category",
            "description": "description",
            "questions": [
                {
                    "question": "this is a question",
                    "answers": [
                        some", "possible", "answers"
                    ],
                    "image": "optional link to an image"
                }
            ]

        }
        ```
        """
        pass

def setup(bot):
    bot.add_cog(Trivia(bot))