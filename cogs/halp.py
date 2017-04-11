import discord
import json
import operator
import re
import textwrap

from collections import namedtuple
from datetime import datetime
from discord.ext import commands
from functools import partial

from .utils import checks, errors
from .utils.converter import BotCogConverter, BotCommand
from .utils.database import Database
from .utils.misc import multi_replace, nice_time, truncate
from .utils.paginator import iterable_limit_say

def default_help_command(func=lambda s: s, **kwargs):
    async def help_command(self, ctx, *, command: BotCommand(recursive=True)=None):
        await default_help(ctx, command, func=func)
    return commands.command(help=func("Shows this message and stuff"), **kwargs)(help_command)

async def default_help(ctx, command=None, func=lambda s:s):
    command = ctx.bot if command is None else command
    destination = ctx.channel

    page = await ctx.bot.formatter.format_help_for(ctx, command, func)

    if isinstance(page, discord.Embed):
        await destination.send(embed=page)
    else:
        await destination.send(page)


_message_attrs = 'id author content channel server timestamp'.split()
DummyMessage = namedtuple('DummyMessage', _message_attrs)

# Seriously, fuck JSONs. They can't do namedtuples
class ProblemMessage:
    __slots__ = tuple(_message_attrs)

    def __init__(self, msg):
        for attr in _message_attrs:
            setattr(self, attr, getattr(msg, attr))

    @property
    def nice_timestamp(self):
        return nice_time(self.timestamp)

    @property
    def embed(self):
        author = self.author
        description = f"Sent on {self.nice_timestamp}"
        author_avatar = author.avatar_url_as(format=None)
        content = self.content.replace('->contact', '', 1)
        id_fmt = "{0}\n({0.id})"
        server_fmt = id_fmt.format(self.server) if self.server else "No server"
        return (discord.Embed(description=description)
                .set_author(name=str(author), icon_url=author_avatar)
                .set_thumbnail(url=author_avatar)
                .add_field(name="Channel:", value=id_fmt.format(self.channel))
                .add_field(name="Server:", value=server_fmt)
                .add_field(name="Message:", value=content, inline=False)
                .set_footer(text=f"Message ID: {self.id}")
                )

class ProblemEncoder(json.JSONEncoder):
    def default(self, o):
        if type(o) is ProblemMessage:
            return {
                '__problem__': True,
                'id': o.id,
                'author': o.author.id,
                'content': o.content,
                'channel': o.channel.id,
                'server': getattr(o.server, "id", None),
                'timestamp': str(o.timestamp),
                }
        return super().default(o)

def problem_hook(bot, dct):
    if '__problem__' in dct:
        kwargs = {
            'id': dct['id'],
            'author': discord.utils.get(bot.get_all_members(), id=dct['author']),
            'content': dct['content'],
            'channel': bot.get_channel(dct['channel']),
            'server': bot.get_server(dct['server']),
            'timestamp': datetime.strptime(dct['timestamp'], '%Y-%m-%d %H:%M:%S.%f'),
            }
        return ProblemMessage(DummyMessage(**kwargs))
    return dct

_bracket_repls = {'(': ')', ')': '(',
                  '[': ']', ']': '[',
                  '<': '>', '>': '<',
                 }

class Help:
    def __init__(self, bot):
        self.bot = bot
        #self.bot.command(name='help', , aliases='h')(_default_help_command)

    async def on_ready(self):
        self.problems = Database('issues.json', encoder=ProblemEncoder, load_later=True,
                                 object_hook=partial(problem_hook, self.bot))
        self.bot.add_database(self.problems)

    help = default_help_command(name='help', aliases=['h'])
    halp = default_help_command(str.upper, name='halp', aliases=['HALP'])
    pleh = default_help_command((lambda s: multi_replace(s[::-1], _bracket_repls)), name='pleh')
    pleh = default_help_command((lambda s: multi_replace(s[::-1].upper(), _bracket_repls)), name='plah', aliases=['PLAH'])
    Halp = default_help_command(str.title, name='Halp')

    @commands.command()
    async def invite(self, ctx):
        """...it's an invite"""
        await ctx.send(textwrap.dedent(f"""\
        I am not a not a public bot yet... but here's the invite link just in case:
        {self.bot.invite_url}

        But in the meantime, here's a link to the offical Chiaki Nanami server:
        {self.bot.official_server_invite}

        And here's the source code if you want it:
        https://github.com/Ikusaba-san/Chiaki-Nanami
        """))

    @commands.command()
    async def contact(self, ctx, *, problem: str):
        """Contacts the bot owner

        Try not to abuse this, as the owner can block you at will.
        """
        msg = ctx.message
        author = msg.author
        if author.id in self.problems["blocked"]:
            await self.bot.reply("You have been blocked from contacting the owner")
            return
        owner = (await self.bot.application_info()).owner
        # TODO, make this work with namedtuples
        problem_message = ProblemMessage(msg)
        self.problems[msg] = problem_message
        await self.bot.send_message(owner, f"**{owner.mention} New message from {author}!**",
                                    embed=problem_message.embed)

    @commands.command()
    @checks.is_owner()
    @errors.private_message_only()
    async def contactblock(self, ctx, *, user: discord.User):
        self.problems.setdefault('blocked', []).append(user.id)
        await ctx.send(f"Blocked user {user} successfully!")

    @commands.command(hidden=True)
    @checks.is_owner()
    @errors.private_message_only()
    async def answer(self, ctx, id_: int, *, response: str):
        problem_message = self.problems.pop(id_, None)
        if problem_message is None:
            raise errors.ResultsNotFound(f"Message ID ***{id_}*** doesn't exist, I think")

        appinfo = await self.bot.application_info()
        owner = appinfo.owner
        avatar = owner.avatar_url_as(format=None)
        footer = f"Message sent on {ctx.message.timestamp}"
        response_embed = (discord.Embed(colour=0x00FF00)
                         .set_author(name=str(owner), icon_url=avatar)
                         .set_thumbnail(url=appinfo.icon_url)
                         .add_field(name="Response:", value=response)
                         .set_footer(text=footer)
                         )
        msg = f"{problem_message.author.mention}, you have a response for message ***{id_}***:"
        await problem_message.author.send(msg, embed=response_embed)
        await problem_message.channel.send(msg, embed=response_embed)
        await ctx.send(f"Successfully responded to {id_}! Response:", embed=response_embed)

    @commands.command(hidden=True)
    @checks.is_owner()
    @errors.private_message_only()
    async def review(self, ctx, id_: str):
        problem_message = self.problems.get(id_)
        if problem_message:
            await ctx.send(f"**Saved Message from {problem_message.author}:**", embed=problem_message.embed)
        raise errors.ResultsNotFound(f"ID {id_} doesn't exist, I think")

    @commands.command(aliases=['cogs'])
    async def modules(self, ctx):
        modules_embed = discord.Embed(title="List of my modules", colour=self.bot.colour)
        prefix = await self.bot.get_prefix(ctx.message)

        visible_cogs =  ((name, cog) for name, cog in self.bot.cogs.items() if name and not cog.__hidden__)
        for name, cog in sorted(visible_cogs, key=operator.itemgetter(0)):
            doc = cog.__doc__ or 'No description... yet.'
            modules_embed.add_field(name=name, value=truncate(doc.splitlines()[0], 20, '...'))

        modules_embed.set_footer(text='Type "{prefix}commands {{module_name}}" for all the commands on a module')
        await ctx.send(embed=modules_embed)

    @commands.command(aliases=['cmds'])
    async def commands(self, ctx, cog: BotCogConverter):
        commands_embed = await self.bot.formatter.format_help_for(ctx, cog)
        await ctx.send(embed=commands_embed)

def setup(bot):
    bot.add_cog(Help(bot))
