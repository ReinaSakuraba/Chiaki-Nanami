import asyncio
import collections
import contextlib
import discord
import functools
import glob
import itertools
import json
import os
import random

from discord.ext import commands

from .manager import SessionManager
from ..utils.misc import base_filename, emoji_url

QUESTION_GAME_TIMEOUT = 60
class TriviaSession:
    def __init__(self, ctx, category):
        self.ctx = ctx
        self.category = category
        self.finished = asyncio.Event()
        self.answered = asyncio.Event()
        self.scoreboard = collections.Counter()

    def _check_answer(self, m):
        if m.channel != self.ctx.channel:
            return False
        # Prevent other bots from accidentally answering the question
        # This issue has happened numberous times with other bots.
        if m.author.bot:
            return False
        self.answered.set()
        user_answer = m.content.lower()
        # Use the bad answer recognition in x^3 for some nice disrespect
        return any(a.lower() in user_answer for a in self.answers)

    def _question_embed(self, n):
        leader = self.leader
        leader_text = f'{leader[0]} with {leader[1]} points' if leader else None
        description = self.category.get('description', discord.Embed.Empty)
        return (discord.Embed(description=description, colour=random.randint(0, 0xFFFFFF))
               .set_author(name=self.category.get('title', 'Trivia'))
               .add_field(name=f'Question #{n}', value=self.question)
               .set_footer(text=f'Current leader: {leader_text}')
               ) 

    def _answer_embed(self, answerer, action):
        description = f'The answer was **{self.answers[0]}**.'
        return (discord.Embed(colour=0x00FF00, description=description)
               .set_author(name=f'{answerer} {action}!')
               .set_thumbnail(url=answerer.avatar_url_as(format=None))
               .set_footer(text=f'{answerer} now has {self.scoreboard[answerer]} points.')
               )

    @staticmethod
    def _timeout_embed(answer):
        return (discord.Embed(description=f'The answer was **{answer}**', colour=0xFF0000)
               .set_author(name='Times up!', icon_url=emoji_url('\N{ALARM CLOCK}'))
               .set_footer(text='No one got any points :(')
               )

    async def __run(self):
        for q in itertools.count(1):
            self.question, self.answers = self.next_question()
            await self.ctx.send(embed=self._question_embed(q))
            try:
                msg = await self.ctx.bot.wait_for('message', timeout=10, check=self._check_answer)
            except asyncio.TimeoutError:
                await self.ctx.send(embed=self._timeout_embed(self.answers[0]))
            else:
                self.scoreboard[msg.author] += 1
                if self.scoreboard[msg.author] >= 10:
                    await self.ctx.send(embed=self._answer_embed(msg.author, 'wins the game'))
                    break
                else:
                    await self.ctx.send(embed=self._answer_embed(msg.author, 'got it'))
            finally:
                await asyncio.sleep(random.uniform(1.5, 3))
        await self.stop()

    async def run(self):
        task = self.ctx.bot.loop.create_task
        self.runner = task(self.__run())
        self.time_out_checker = task(self.check_time_out())
        await self.finished.wait()

    async def stop(self, force=False):
        self.force_closed = force
        with contextlib.suppress(BaseException):
            self.runner.cancel()
        with contextlib.suppress(BaseException):
            self.time_out_checker.cancel()
        self.finished.set()

    async def check_time_out(self):
        while True:
            try:
                await asyncio.wait_for(self.answered.wait(), QUESTION_GAME_TIMEOUT)
            except asyncio.TimeoutError:
                await self.ctx.send("Um, is anyone here...?")
                break
            else:
                self.answered.clear()
        await self.stop(force=True)

    def next_question(self):
        question = random.choice(self.category['questions'])
        return question['question'], question['answers']

    @property
    def leader(self):
        leaderboard = self.leaderboard
        return leaderboard[0] if leaderboard else None

    @property
    def leaderboard(self):
        return self.scoreboard.most_common()


def _load_json(file):
    with open(file) as f:
        return json.load(f)


class Trivia:
    """It's trivia and stuff"""
    FILE_PATH = os.path.join('.', 'data', 'games', 'trivia')

    def __init__(self, bot):
        self.bot = bot
        self.manager = SessionManager()
        self.bot.loop.create_task(self._load_categories())

    def __unload(self):
        # stop running any currently running trivia games
        self.manager.cancel_all(loop=self.bot.loop)

    async def _load_categories(self):
        load_async = functools.partial(self.bot.loop.run_in_executor, None, _load_json)
        files = glob.glob(f'{self.FILE_PATH}/*.json')
        load_tasks = (load_async(name) for name in files)
        file_names = (base_filename(name) for name in files)

        self.default_catergories = dict(zip(file_names, await asyncio.gather(*load_tasks)))
        print('everything is ok now')

    async def _get_category(self, ctx, category):
        lowered = category.lower()
        with contextlib.suppress(KeyError):
            return self.default_catergories[lowered]

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

    @commands.group(invoke_without_command=True)
    async def trivia(self, ctx, category):
        """It's trivia..."""
        if self.manager.session_exists(ctx.channel):
             return await ctx.send("A trivia game is already running in this channel...")

        category = await self._get_category(ctx, category)
        with self.manager.temp_session(ctx.channel, TriviaSession(ctx, category)) as inst:
            await inst.run()
            if inst.force_closed:
                return

            await asyncio.sleep(1.5)
            results_embed = self._leaderboard_embed(inst, 'Trivia Game Ended', 'Final Results', past=True)
            await ctx.send(embed=results_embed)

    @trivia.command(name='stop', aliases=['quit'])
    async def trivia_stop(self, ctx):
        """Stops a running game of trivia"""
        game = self.manager.get_session(ctx.channel)
        if game is None:
            return await ctx.send("There is no trivia game to stop... :|")

        await game.stop()
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