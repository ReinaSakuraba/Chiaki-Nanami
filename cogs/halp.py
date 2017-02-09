import discord
import json
import re

from collections import namedtuple
from datetime import datetime
from discord.ext import commands

from .utils import checks
from .utils.database import Database
from .utils.errors import private_message_only, ResultsNotFound
from .utils.misc import multi_replace, nice_time

_mentions_transforms = {
    '@everyone': '@\u200beveryone',
    '@here': '@\u200bhere'
}

async def _default_help_command(ctx, *commands):
    """Shows this message and stuff"""
    await default_help(ctx, *commands)

async def default_help(ctx, *commands : str, func=lambda s:s):
    _mention_pattern = re.compile('|'.join(_mentions_transforms))

    bot = ctx.bot
    destination = ctx.message.author if bot.pm_help else ctx.message.channel

    def repl(obj):
        return _mentions_transforms.get(obj.group(0), '')

    is_bot = is_cog = False
    # help by itself just lists our own commands.
    if len(commands) == 0:
        pages = bot.formatter.format_help_for(ctx, bot)
        is_bot = True
    elif len(commands) == 1:
        # try to see if it is a cog name
        name = _mention_pattern.sub(repl, commands[0])
        command = None
        if name in bot.cogs:
            command = bot.cogs[name]
            is_cog = True
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
        characters = sum(map(len, pages))
        # modify destination based on length of pages.
        if characters > 1000:
            destination = ctx.message.author
        if is_bot or is_cog:
            for page in pages:
                await bot.send_message(destination, func(page))
        else:
            prefix = bot.str_prefix(command, ctx.message.server)
            names = [command.qualified_name.split()[-1], *command.aliases]
            signature = bot.formatter.get_command_signature()
            usage = getattr(command, '__usage__', ['No example... yet.'])
            usages = '\n'.join([f"`{prefix}{u}`" for u in usage])
            cmd_name = f"`{prefix}{command.full_parent_name} {' / '.join(names)}`"
            cmd_embed = (discord.Embed(title=cmd_name, description=command.help, colour=bot.colour)
                        .add_field(name="Structure", value=f'`{signature}`')
                        .add_field(name="Usage", value=usages, inline=False)
                        .set_footer(text='"{0}" is in the module *{0.cog_name}*'.format(command))
                        )
            await bot.send_message(destination, embed=cmd_embed)


_message_attrs = 'id author content channel server timestamp'.split()
DummyMessage = namedtuple('DummyMessage', _message_attrs)

class ProblemMessage:
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
            problem = ProblemMessage(DummyMessage(**kwargs))
            return problem
        return dct
    return hook

_bracket_swap = {'(': ')', ')': '(', '[': ']', ']': '[' }
class Help:
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.load_database())
        self.bot.commands.pop('help', None)
        self.bot.command(name='help', pass_context=True, aliases='h')(_default_help_command)

    # Unlike most databases, this requires the bot be ready first before loading the database
    async def load_database(self):
        await self.bot.wait_until_ready()
        self.problems = Database.from_json('issues.json', encoder=ProblemEncoder,
                                           object_hook=problem_hook(self.bot))
        self.problems.setdefault('blocked', [])
        self.bot.add_database(self.problems)

    @commands.command(pass_context=True, aliases=['HALP'])
    async def halp(self, ctx, *commands : str):
        """HALP"""
        await default_help(ctx, *commands, func=str.upper)

    @commands.command(pass_context=True)
    async def pleh(self, ctx, *commands : str):
        await default_help(ctx, *commands, func=lambda s: multi_replace(s[::-1], _bracket_swap))

    @commands.command(pass_context=True, aliases=['PLAH'])
    async def plah(self, ctx, *commands : str):
        await default_help(ctx, *commands, func=lambda s: multi_replace(s[::-1].upper(), _bracket_swap))

    @commands.command(pass_context=True)
    async def Halp(self, ctx, *commands : str):
        await default_help(ctx, *commands, func=str.title)

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
        # print(problem_message, repr(problem_message))
        await self.bot.send_message(owner, f"**{owner.mention} New message from {author}!**",
                                    embed=problem_message.embed)

    @commands.command(pass_context=True)
    @checks.is_owner()
    @private_message_only()
    async def contactblock(self, ctx, *, user: discord.User):
        self.problems["blocked"].append(user.id)
        await self.bot.say(f"Blocked user {user} successfully")

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    @private_message_only()
    async def answer(self, ctx, id: str, *, response: str):
        problem_message = self.problems.get(id)
        if problem_message is None:
            raise ResultsNotFound(f"Message ID ***{id}*** doesn't exist, I think")

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

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    @private_message_only()
    async def review(self, ctx, id: str):
        problem_message = self.problems.get(id)
        if problem_message:
            await self.bot.say(f"**Saved Message from {problem_message.author}:**",
                               embed=problem_message.embed)
        raise ResultsNotFound(f"Hash {id} doesn't exist, I think")

    @commands.command()
    async def modules(self):
        modules = sorted({cmd.cog_name for cmd in self.bot.commands.values() if cmd.cog_name})
        module_names = '\n'.join(['+ ' + cog for cog in modules])
        await self.bot.say(f"Available Modules: ```css\n{module_names}```")

def setup(bot):
    bot.add_cog(Help(bot))
