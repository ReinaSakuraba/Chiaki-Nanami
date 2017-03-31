import discord
import json
import operator
import re
import textwrap

from collections import namedtuple
from datetime import datetime
from discord.ext import commands

from .utils import checks, errors
from .utils.converter import BotCogConverter
from .utils.database import Database
from .utils.misc import multi_replace, nice_time, truncate

_mentions_transforms = {
    '@everyone': '@\u200beveryone',
    '@here': '@\u200bhere'
}

async def _default_help_command(ctx, *commands):
    """Shows this message and stuff"""
    await default_help(ctx, *commands)

def default_help_command(func=lambda s: s, **kwargs):
    async def help_command(self, ctx, *commands):
        await default_help(ctx, *commands, func=func)
    return commands.command(pass_context=True, help=func("Shows this message and stuff"), **kwargs)(help_command)

async def default_help(ctx, *commands_ : str, func=lambda s:s):
    _mention_pattern = re.compile('|'.join(_mentions_transforms))

    bot = command = ctx.bot
    destination = ctx.message.channel

    def repl(obj):
        return _mentions_transforms.get(obj.group(0), '')

    for key in commands_:
        try:
            key = _mention_pattern.sub(repl, key)
            command = command.commands.get(key)
            if command is None:
                raise errors.ResultsNotFound(func(bot.command_not_found.format(key)))
        except AttributeError:
            raise errors.InvalidUserArgument(func(bot.command_has_no_subcommands.format(command, key)))

    page = bot.formatter.format_help_for(ctx, command, func)

    if isinstance(page, discord.Embed):
        await bot.send_message(destination, embed=page)
    else:
        await bot.send_message(ctx.message.author, page)


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
        author_avatar = author.avatar_url or author.default_avatar_url
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

def problem_hook(bot):
    def hook(dct):
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
    return hook

_bracket_swap = {'(': ')', ')': '(', 
                 '[': ']', ']': '[',
                 '<': '>', '>': '<',
                 }

class Help:
    def __init__(self, bot):
        self.bot = bot
        #self.bot.command(name='help', pass_context=True, aliases='h')(_default_help_command)

    async def on_ready(self):
        self.problems = Database.from_json('issues.json', encoder=ProblemEncoder,
                                           object_hook=problem_hook(self.bot))
        self.bot.add_database(self.problems)
        
    help = default_help_command(name='help', aliases=['h'])
    halp = default_help_command(str.upper, name='halp', aliases=['HALP'])
    pleh = default_help_command((lambda s: multi_replace(s[::-1], _bracket_swap)), name='pleh')
    pleh = default_help_command((lambda s: multi_replace(s[::-1].upper(), _bracket_swap)), name='plah', aliases=['PLAH'])
    Halp = default_help_command(str.title, name='Halp')
        
    @commands.command()
    async def invite(self):
        """...it's an invite"""
        await self.bot.say(textwrap.dedent(f"""\
        This is the link to invite me, I think.
        {self.bot.invite_url}

        And here's the official server:
        {self.bot.official_server_invite}

        And here's the source code if you want it:
        https://github.com/Ikusaba-san/Chiaki-Nanami
        """))

    @commands.command(pass_context=True)
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

    @commands.command(pass_context=True)
    @checks.is_owner()
    @errors.private_message_only()
    async def contactblock(self, ctx, *, user: discord.User):
        self.problems.setdefault('blocked', []).append(user.id)
        await self.bot.say(f"Blocked user {user} successfully!")

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    @errors.private_message_only()
    async def answer(self, ctx, id: str, *, response: str):
        problem_message = self.problems.get(id)
        if problem_message is None:
            raise errors.ResultsNotFound(f"Message ID ***{id}*** doesn't exist, I think")

        appinfo = await self.bot.application_info()
        owner = appinfo.owner
        avatar = owner.avatar_url or owner.default_avatar_url
        footer = f"Message sent on {nice_time(ctx.message.timestamp)}"
        response_embed = (discord.Embed(colour=0x00FF00)
                         .set_author(name=str(owner), icon_url=avatar)
                         .set_thumbnail(url=appinfo.icon_url)
                         .add_field(name="Response:", value=response)
                         .set_footer(text=footer)
                         )
        msg = f"{problem_message.author.mention}, you have a response for message ***{id}***:"
        await self.bot.send_message(problem_message.author, msg, embed=response_embed)
        await self.bot.send_message(problem_message.channel, msg, embed=response_embed)
        self.problems.pop(id)
        await self.bot.say(f"Successfully responded to {id}! Response:", embed=response_embed)

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    @errors.private_message_only()
    async def review(self, ctx, id: str):
        problem_message = self.problems.get(id)
        if problem_message:
            await self.bot.say(f"**Saved Message from {problem_message.author}:**",
                               embed=problem_message.embed)
        raise errors.ResultsNotFound(f"ID {id} doesn't exist, I think")

    @commands.command(aliases=['cogs'])
    async def modules(self):
        modules_embed = discord.Embed(title="List of my modules", colour=self.bot.colour)
        for name, cog_dict in self.bot.cog_command_namespace.items():
            if cog_dict['hidden']: continue
            doc = cog_dict['cog'].__doc__ or 'No description... yet.'
            modules_embed.add_field(name=name, value=truncate(doc.splitlines()[0], 20, '...'))
        modules_embed.set_footer(text='Type "->commands {module_name}" for all the commands on a module')
        await self.bot.say(embed=modules_embed)
       
    @commands.command(pass_context=True, aliases=['cmds'])
    async def commands(self, ctx, cog_name: BotCogConverter):
        commands_embed = self.bot.formatter.format_help_for(ctx, cog_name.name)
        await self.bot.say(embed=commands_embed)

def setup(bot):
    bot.add_cog(Help(bot))
