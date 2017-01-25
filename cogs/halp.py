import discord
import functools
import hashlib
import json
import re

from collections import namedtuple
from datetime import datetime
from discord.ext import commands

from .utils import checks
from .utils.database import Database
from .utils.misc import nice_time, str_swap, str_join

_mentions_transforms = {
    '@everyone': '@\u200beveryone',
    '@here': '@\u200bhere'
}

async def default_help(ctx, func=lambda s:s, *commands : str):
    commands = [s.lower() for s in commands]

    _mention_pattern = re.compile('|'.join(_mentions_transforms.keys()))

    bot = ctx.bot
    destination = ctx.message.author if bot.pm_help else ctx.message.channel

    def repl(obj):
        return _mentions_transforms.get(obj.group(0), '')

    # help by itself just lists our own commands.
    if len(commands) == 0:
        pages = bot.formatter.format_help_for(ctx, bot)
    elif len(commands) == 1:
        # try to see if it is a cog name
        name = _mention_pattern.sub(repl, commands[0])
        command = None
        if name in bot.cogs:
            command = bot.cogs[name]
        else:
            command = bot.commands.get(name)
            if command is None:
                await bot.send_message(destination, bot.command_not_found.format(name))
                return

        pages = bot.formatter.format_help_for(ctx, command)
    else:
        name = _mention_pattern.sub(repl, commands[0])
        command = bot.commands.get(name)
        if command is None:
            await bot.send_message(destination, bot.command_not_found.format(name))
            return

        for key in commands[1:]:
            try:
                key = _mention_pattern.sub(repl, key)
                command = command.commands.get(key)
                if command is None:
                    await bot.send_message(destination, bot.command_not_found.format(key))
                    return
            except AttributeError:
                await bot.send_message(destination, bot.command_has_no_subcommands.format(command, key))
                return

        pages = bot.formatter.format_help_for(ctx, command)

    if bot.pm_help is None:
        characters = sum(map(lambda l: len(l), pages))
        # modify destination based on length of pages.
        if characters > 1000:
            destination = ctx.message.author

        for page in pages:
            await bot.send_message(destination, func(page))

_message_attrs = 'author content channel server timestamp'.split()
DummyMessage = namedtuple('DummyMessage', _message_attrs)

def problem_hook(bot, dct):
    if '__problem__' in dct:
        kwargs = {
            'author': discord.utils.get(bot.get_all_members(), id=dct['author']),
            'content': dct['content'],
            'channel': bot.get_channel(dct['channel']),
            'server': bot.get_server(dct['server']),
            'timestamp': datetime.strptime(dct['timestamp'], '%Y-%m-%d %H:%M:%S.%f'),
            }
        problem = ProblemMessage(DummyMessage(**kwargs))
        return problem
    return dct

class ProblemMessage:
    def __init__(self, msg):
        for attr in _message_attrs:
            setattr(self, attr, getattr(msg, attr))

    def __iter__(self):
        return iter([getattr(self, attr) for attr in _message_attrs])

    def __hash__(self):
        return hash(self.hash)

    @property
    def nice_timestamp(self):
        return nice_time(self.timestamp)

    @property
    def embed(self):
        description = "Sent from {0.channel} in {0.server}".format(self)
        author = self.author
        author_avatar = author.avatar_url or author.default_avatar_url
        content = self.content.replace('->contact', '', 1)
        return (discord.Embed(description=description)
                .set_author(name=str(author), icon_url=author_avatar)
                .set_thumbnail(url=author_avatar)
                .add_field(name="Message:", value=content)
                .add_field(name="Sent:", value=self.nice_timestamp, inline=False)
                .set_footer(text=self.hash)
                )

    @property
    def hash(self):
        print(list(self))
        return hashlib.sha256(str_join('', self).encode('utf-8')).hexdigest()

class ProblemEncoder(json.JSONEncoder):
    def default(self, o):
        if type(o) is ProblemMessage:
            return {
                '__problem__': True,
                'author': o.author.id,
                'content': o.content,
                'channel': o.channel.id,
                'server': getattr(o.server, "id", None),
                'timestamp': str(o.timestamp),
                }
        return super().default(o)

class Help:
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.load_database())

    # Unlike most databases, this requires the bot be ready first before loading the database
    async def load_database(self):
        await self.bot.wait_until_ready()
        hook = functools.partial(problem_hook, self.bot)
        self.problems = Database.from_json("issues.json", encoder=ProblemEncoder,
                        object_hook=hook)
        self.problems.setdefault("blocked", [])

    @commands.command(pass_context=True, aliases=['HALP'])
    async def halp(self, ctx, *commands : str):
        await default_help(ctx, str.upper, *commands)

    @commands.command(pass_context=True)
    async def pleh(self, ctx, *commands : str):
        await default_help(ctx, lambda s: str_swap(s[::-1], '(', ')'), *commands)

    @commands.command(pass_context=True, aliases=['PLAH'])
    async def plah(self, ctx, *commands : str):
        await default_help(ctx, lambda s: str_swap(s[::-1].upper(), '(', ')'), *commands)

    @commands.command(pass_context=True)
    async def Halp(self, ctx, *commands : str):
        await default_help(ctx, str.title, *commands)

    @commands.command(pass_context=True)
    async def contact(self, ctx, *, problem: str):
        """Contacts the bot owner

        Try not to abuse this, as the owner can block you at will.
        """
        author = ctx.message.author
        if author.id in self.problems["blocked"]:
            await self.bot.reply("You have been blocked from contacting the owner")
            return
        appinfo = await self.bot.application_info()
        owner = appinfo.owner
        # TODO, make this work with namedtuples
        problem_message = ProblemMessage(ctx.message)
        self.problems[problem_message.hash] = problem_message
        # print(problem_message, repr(problem_message))
        await self.bot.send_message(owner, f"**{owner.mention} New message from {author}!**",
                                    embed=problem_message.embed)

    @commands.command(pass_context=True)
    @checks.is_owner()
    async def contactblock(self, ctx, *, user: discord.User):
        if not ctx.message.channel.is_private:
            return
        self.problems["blocked"].append(user.id)
        await self.bot.say(f"Blocked user {user} successfully")

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    async def answer(self, ctx, hash: str, *, response: str):
        if not ctx.message.channel.is_private:
            return
        problem_message = self.problems.get(hash)
        if problem_message is None:
            await self.bot.say(f"Hash {hash} doesn't exist, I think")
            return

        appinfo = await self.bot.application_info()
        footer = f"Message sent on {nice_time(ctx.message.timestamp)}"
        response_embed = (discord.Embed(colour=discord.Colour(0x00FF00))
                         .set_thumbnail(url=appinfo.icon_url)
                         .add_field(name="Response:", value=response)
                         .set_footer(text=footer)
                         )
        msg = f"{problem_message.author.mention}, you have a response for message {hash}:"
        await self.bot.send_message(problem_message.author, msg, embed=response_embed)
        await self.bot.send_message(problem_message.channel, msg, embed=response_embed)
        self.problems.pop(hash)

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    async def review(self, ctx, hash: str):
        if not ctx.message.channel.is_private:
            return
        problem_message = self.problems.get(hash)
        print(problem_message)
        if problem_message is None:
            await self.bot.say(f"Hash {hash} doesn't exist, I think")
        else:
            await self.bot.say(f"**Saved Message from {problem_message.author}:**" , embed=problem_message.embed)

    async def modules(self):
        modules = '\n'.join(['+' + cog.name for cog in self.bot.cogs])
        await self.bot.say(f"Available Modules: ```css\n{modules}```")

def setup(bot):
    bot.add_cog(Help(bot))
