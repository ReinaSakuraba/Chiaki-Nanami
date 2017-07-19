import discord
import json
import operator
import re
import textwrap

from collections import namedtuple
from datetime import datetime
from discord.ext import commands
from functools import partial

from .utils import errors
from .utils.context_managers import temp_attr
from .utils.converter import BotCogConverter, BotCommand
from .utils.database import Database
from .utils.formats import multi_replace
from .utils.misc import nice_time, truncate


def default_help_command(func=lambda s: s, **kwargs):
    async def help_command(self, ctx, *, command: BotCommand=None):
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


_message_attrs = 'id author content channel guild created_at'.split()
DummyMessage = namedtuple('DummyMessage', _message_attrs)

# Seriously, fuck JSONs. They can't do namedtuples
class ProblemMessage:
    __slots__ = tuple(_message_attrs)

    def __init__(self, msg):
        for attr in _message_attrs:
            setattr(self, attr, getattr(msg, attr))

    @property
    def embed(self):
        author = self.author
        author_avatar = author.avatar_url_as(format=None)
        id_fmt = "{0}\n({0.id})"
        server_fmt = id_fmt.format(self.guild) if self.guild else "No server"

        return (discord.Embed(timestamp=self.created_at)
               .set_author(name=str(author), icon_url=author_avatar)
               .set_thumbnail(url=author_avatar)
               .add_field(name="Channel:", value=id_fmt.format(self.channel))
               .add_field(name="Server:", value=server_fmt)
               .add_field(name="Message:", value=self.content, inline=False)
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
                'server': getattr(o.guild, "id", None),
                'created_at': str(o.created_at),
                }
        return super().default(o)

def problem_hook(bot, dict_):
    if '__problem__' in dict_:
        kwargs = {
            'id': dict_['id'],
            'author': bot.get_user(dict_['author']),
            'content': dict_['content'],
            'channel': bot.get_channel(dict_['channel']),
            'guild': bot.get_guild(dict_['server']),
            'created_at': datetime.strptime(dict_['created_at'], '%Y-%m-%d %H:%M:%S.%f'),
            }
        return ProblemMessage(DummyMessage(**kwargs))
    return dict_

_bracket_repls = {
    '(': ')', ')': '(',
    '[': ']', ']': '[',
    '<': '>', '>': '<',
}

class Help:
    def __init__(self, bot):
        self.bot = bot
        #self.bot.command(name='help', , aliases='h')(_default_help_command)
        self.bot.loop.create_task(self.load_problems())

    async def load_problems(self):
        # because of the use of Client.get_* methods, we have to wait until the bot is logged in
        # otherwise we'd just get Nones everywhere
        await self.bot.wait_until_ready()
        self.problems = Database('issues.json', encoder=ProblemEncoder, load_later=True,
                                 object_hook=partial(problem_hook, self.bot))
        self.blocked = self.problems.setdefault('blocked', [])
        self.bot.add_database(self.problems)

    help = default_help_command(name='help', aliases=['h'])
    halp = default_help_command(str.upper, name='halp', aliases=['HALP'])
    pleh = default_help_command((lambda s: multi_replace(s[::-1], _bracket_repls)), name='pleh')
    pleh = default_help_command((lambda s: multi_replace(s[::-1].upper(), _bracket_repls)), name='plah', aliases=['PLAH'])
    Halp = default_help_command(str.title, name='Halp')

    @commands.command()
    async def invite(self, ctx):
        """...it's an invite"""
        invite = (discord.Embed(description=self.bot.description, title=str(self.bot.user), colour=self.bot.colour)
                 .set_thumbnail(url=self.bot.user.avatar_url_as(format=None))
                 .add_field(name="Want me in your server?",
                            value=f'[Invite me here!]({self.bot.invite_url})', inline=False)
                 .add_field(name="Need help with using me?",
                            value=f"[Here's the official server!]({self.bot.official_server_invite})", inline=False)
                 .add_field(name="If you're curious about how I work...",
                            value="[Check out the source code!](https://github.com/Ikusaba-san/Chiaki-Nanami/tree/rewrite)", inline=False)
                 )
        await ctx.send(embed=invite)

    @commands.command()
    @commands.cooldown(rate=1, per=30, type=commands.BucketType.user)
    async def contact(self, ctx, *, problem: str):
        """Contacts the bot owner

        Try not to abuse this, as the owner can block you at will.
        """
        msg = ctx.message
        author = msg.author
        if author.id in self.blocked:
            return await ctx.send("{ctx.author.mention}, you have been blocked from contacting the owner")

        # TODO, make this work with namedtuples
        with temp_attr(msg, 'content', msg.content.replace(f'{ctx.prefix}contact', '', 1)):
            problem_message = ProblemMessage(msg)

        self.problems[msg] = problem_message
        await self.bot.owner.send(f"**{self.bot.owner.mention} New message from {author}!**",
                                  embed=problem_message.embed)

    @commands.command()
    @commands.is_owner()
    @errors.private_message_only()
    async def contactblock(self, ctx, *, user: discord.User):
        self.blocked.append(user.id)
        await ctx.send(f"Blocked user {user} successfully!")

    @commands.command(hidden=True)
    @commands.is_owner()
    @errors.private_message_only()
    async def answer(self, ctx, id_: int, *, response: str):
        problem_message = self.problems.pop(id_, None)
        if problem_message is None:
            raise errors.ResultsNotFound(f"Message ID ***{id_}*** doesn't exist, I think")

        avatar = self.bot.owner.avatar_url_as(format=None)
        response_embed = (discord.Embed(colour=0x00FF00, description=response, timestamp=ctx.message.created_at)
                         .set_author(name=str(self.bot.owner), icon_url=avatar)
                         .set_thumbnail(url=self.bot.appinfo.icon_url)
                         )

        msg = f"{problem_message.author.mention}, you have a response for message ***{id_}***:"
        await problem_message.author.send(msg, embed=response_embed)
        await problem_message.channel.send(msg, embed=response_embed)
        await ctx.send(f"Successfully responded to {id_}! Response:", embed=response_embed)

    @commands.command(hidden=True)
    @commands.is_owner()
    @errors.private_message_only()
    async def review(self, ctx, id_: str):
        problem_message = self.problems.get(id_)
        if problem_message:
            await ctx.send(f"**Saved Message from {problem_message.author}:**", embed=problem_message.embed)
        raise errors.ResultsNotFound(f"ID {id_} doesn't exist, I think")

    @commands.command(aliases=['cogs', 'mdls'])
    async def modules(self, ctx):
        """Shows all the *visible* modules that I have loaded"""
        visible_cogs =  ((name, cog.__doc__ or '\n') for name, cog in self.bot.cogs.items()
                         if name and not cog.__hidden__)
        formatted_cogs = [f'`{name}` => {truncate(doc.splitlines()[0], 20, "...")}' for name, doc in visible_cogs]

        modules_embed = (discord.Embed(title="List of my modules",
                                       description='\n'.join(formatted_cogs),
                                       colour=self.bot.colour)
                        .set_footer(text=f'Type `{ctx.prefix}help` for help.')
                        )
        await ctx.send(embed=modules_embed)

    @commands.command(aliases=['cmds'])
    async def commands(self, ctx, cog: BotCogConverter):
        """Shows all the *visible* commands I have in a given cog/module"""
        commands_embeds = await self.bot.formatter.format_help_for(ctx, cog)
        for embed in commands_embeds:
            await ctx.send(embed=embed)

def setup(bot):
    bot.add_cog(Help(bot))
