import discord
import json
import random

from discord.ext import commands
from datetime import datetime

from .utils.converter import BotCogConverter, BotCommand
from .utils.formats import multi_replace
from .utils.misc import emoji_url, truncate

 
CHIAKI_TIP_EPOCH = datetime(2017, 8, 24)
TIP_EMOJI = emoji_url('\N{ELECTRIC LIGHT BULB}')
DEFAULT_TIP = {
    'title': 'You have reached the end of the tips!',
    'description': 'Wait until the next update for more tips!'
}
TOO_FAR_TIP = {
    'title': "You're going a bit too far here!",
    'description': 'Wait until tomorrow or something!'
}


def _get_tip_index():
    return (datetime.utcnow() - CHIAKI_TIP_EPOCH).days


def positive_index(s):
    num = int(s)
    if num <= 0:
        raise commands.BadArgument('Value must be positive.')
    return num


def default_help_command(func=lambda s: s, **kwargs):
    async def help_command(self, ctx, *, command: BotCommand=None):
        await default_help(ctx, command, func=func)
    return commands.command(help=func("Shows this message and stuff"), **kwargs)(help_command)


async def default_help(ctx, command=None, func=lambda s: s):
    command = ctx.bot if command is None else command
    destination = ctx.channel

    page = await ctx.bot.formatter.format_help_for(ctx, command, func)

    if isinstance(page, discord.Embed):
        await destination.send(embed=page)
    else:
        await destination.send(page)


_bracket_repls = {
    '(': ')', ')': '(',
    '[': ']', ']': '[',
    '<': '>', '>': '<',
}


class Help:
    def __init__(self, bot):
        self.bot = bot
        self.bot.remove_command('help')
        self.bot.remove_command('h')
        with open('data/tips.json') as f:
            self.tips_list = json.load(f)

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
                 .add_field(name="If you just to be simple...",
                            value=f'[Invite me with minimal permissions!]({self.bot.minimal_invite_url})', inline=False)
                 .add_field(name="Need help with using me?",
                            value=f"[Here's the official server!]({self.bot.support_invite})", inline=False)
                 .add_field(name="If you're curious about how I work...",
                            value="[Check out the source code!](https://github.com/Ikusaba-san/Chiaki-Nanami/tree/rewrite)", inline=False)
                 )
        await ctx.send(embed=invite)

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

    @commands.command(name='commands', aliases=['cmds'])
    async def commands_(self, ctx, cog: BotCogConverter):
        """Shows all the *visible* commands I have in a given cog/module"""
        commands_embeds = await self.bot.formatter.format_help_for(ctx, cog)
        for embed in commands_embeds:
            await ctx.send(embed=embed)

    async def _show_tip(self, ctx, number):
        if number > _get_tip_index() + 1:
            tip, success = TOO_FAR_TIP, False
        else:
            try:
                tip, success = self.tips_list[number - 1], True
            except IndexError:
                tip, success = DEFAULT_TIP, False

        tip_embed = discord.Embed.from_data(tip)
        tip_embed.colour = ctx.bot.colour
        if success:
            tip_embed.set_author(name=f'Tip of the Day #{number}', icon_url=TIP_EMOJI)

        await ctx.send(embed=tip_embed)

    @commands.command()
    async def tip(self, ctx, number: positive_index = None):
        """Shows a Chiaki Tip via number.

        If no number is specified, it shows the daily tip.
        """
        if number is None:
            number = _get_tip_index() + 1


        await self._show_tip(ctx, number)

    @commands.command()
    async def randomtip(self, ctx):
        """Shows a random tip.

        The tip range is from the first one to today's one.
        """
        number = _get_tip_index() + 1
        await self._show_tip(ctx, random.randint(1, number))


def setup(bot):
    bot.add_cog(Help(bot))
