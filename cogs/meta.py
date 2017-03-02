import aiohttp
import discord
import inspect
import json
import sys

from collections import defaultdict, deque
from contextlib import redirect_stdout
from discord.ext import commands
from io import StringIO
from operator import attrgetter, itemgetter

from .utils import converter
from .utils.compat import url_color, user_color
from .utils.converter import BotCogConverter, RecursiveBotCommandConverter
from .utils.errors import ResultsNotFound
from .utils.misc import str_join, nice_time, ordinal
from .utils.paginator import iterable_limit_say, iterable_say

def _ilen(gen):
    return sum(1 for _ in gen)

def _icon_embed(idable, url, name):
    embed = (discord.Embed(title=f"{idable.name}'s {name}")
            .set_footer(text=f"ID: {idable.id}"))
    return embed.set_image(url=url) if url else embed

async def _mee6_stats(session, member):
    async with session.get(f"https://mee6.xyz/levels/{member.guild.id}?json=1&limit=-1") as r:
        levels = await r.json()
    for idx, user_stats in enumerate(levels['players'], start=1):
        if user_stats.get("id") == member.id:
            user_stats["rank"] = idx
            return user_stats
    raise ResultsNotFound(f"{member} does not have a mee6 level. :frowning:")

async def _user_embed(member):
    avatar_url = member.avatar_url_as(format=None)
    playing = f"Playing **{member.game}**"
    roles = sorted(member.roles[1:], reverse=True)
    server = member.guild
    colour = await user_color(member)
    return  (discord.Embed(colour=colour, description=playing)
            .set_thumbnail(url=avatar_url)
            .set_author(name=member.display_name, icon_url=avatar_url)
            .add_field(name="Real Name", value=str(member))
            .add_field(name=f"Joined {server} at", value=nice_time(member.joined_at))
            .add_field(name="Created at", value=nice_time(member.created_at))
            .add_field(name="Highest role", value=member.top_role)
            .add_field(name="Roles", value=str_join(', ', roles) or "-no roles-", inline=False)
            .set_footer(text=f"ID: {member.id}")
            )

class Meta:
    """Info related commands"""
    __prefix__ = '?'

    def __init__(self, bot):
        self.bot = bot
        self.cmd_history = defaultdict(lambda: deque(maxlen=50))
        # Could use self.bot.http.session but that's incredibly bad practice
        # (not sure why though...)
        self.session = aiohttp.ClientSession()

    def __unload(self):
        # Pray it closes
        self.bot.loop.create_task(self.session.close())

    @commands.command(no_pm=True)
    async def uinfo(self, ctx, *, user : discord.Member=None):
        """Gets some basic userful info because why not"""
        if user is None:
            user = ctx.author
        fmt = ("    Name: {0.name}\n"
               "      ID: {0.id}\n"
               " Hashtag: {0.discriminator}\n"
               "Nickname: {0.display_name}\n"
               " Created: {0.created_at}\n"
               "  Joined: {0.joined_at}\n"
               "   Roles: {1}\n"
               "  Status: {0.status}\n"
               )
        roles = str_join(', ', reversed(user.roles[1:]))
        await ctx.send("```\n{}\n```".format(fmt.format(user, roles)))

    @commands.group()
    async def info(self, ctx):
        """Super-command for all info-related commands"""
        if ctx.invoked_subcommand is None:
            subcommands = '\n'.join(ctx.command.commands.keys())
            await ctx.send(f"```\nAvailable info commands:\n{subcommands}```")

    @info.command(no_pm=True)
    async def user(self, ctx, *, member: converter.ApproximateUser=None):
        """Gets some userful info because why not"""
        await ctx.invoke(self.userinfo, member=member)

    @info.command(no_pm=True)
    async def mee6(self, ctx, *, member: converter.ApproximateUser=None):
        await ctx.invoke(self.rank, member=member)

    @commands.command(no_pm=True)
    async def rank(self, ctx, *, member: converter.ApproximateUser=None):
        """Gets mee6 info... if it exists"""
        message = await ctx.send("Fetching data, please wait...")
        if member is None:
            member = ctx.author
        avatar_url = member.avatar_url_as(format=None)

        with ctx.typing():
            try:
                stats = await _mee6_stats(self.session, member)
            except json.JSONDecodeError:
                return await ctx.send("No stats found. You don't have mee6 in this server... I think.")
            finally:
                await message.delete()

        description = f"Currently sitting at {stats['rank']}!"
        xp_progress = "{xp}/{lvl_xp} ({xp_percent}%)".format(**stats)
        xp_remaining = stats['lvl_xp'] - stats['xp']
        colour = await user_color(member)

        mee6_embed = (discord.Embed(colour=colour, description=description)
                     .set_author(name=member.display_name, icon_url=avatar_url)
                     .set_thumbnail(url=avatar_url)
                     .add_field(name="Level", value=stats['lvl'])
                     .add_field(name="Total XP", value=stats['total_xp'])
                     .add_field(name="Level XP",  value=xp_progress)
                     .add_field(name="XP Remaining to next level",  value=xp_remaining)
                     .set_footer(text=f"ID: {member.id}")
                     )

        await ctx.send(embed=mee6_embed)

    @info.command()
    async def role(self, ctx, *, role: converter.ApproximateRole):
        server = ctx.guild
        bool_as_answer = lambda b: "YNeos"[not b::2]
        prefix = self.bot.str_prefix(self, server)

        has_roles = [mem for mem in server.members if role in mem.roles]
        member_amount = len(has_roles)
        if member_amount > 20:
            members_name = "Members"
            members_value = f"{member_amount} (use {prefix}inrole '{role}' to figure out who's in that role)"
        else:
            members_name = f"Members ({member_amount})"
            members_value = str_join(", ", has_roles)

        hex_role_color = str(role.colour).upper()
        permissions = role.permissions.value
        permission_binary = "{0:32b}".format(permissions)
        str_position = ordinal(role.position)
        nice_created_at = nice_time(role.created_at)
        description = f"Just chilling as {server}'s {str_position} role"
        footer = f"Created at: {nice_created_at} | ID: {role.id}"

        # I think there's a way to make a solid color thumbnail, idk though
        role_embed = (discord.Embed(title=role.name, colour=role.colour, description=description)
                     .add_field(name="Colour", value=hex_role_color)
                     .add_field(name="Permissions", value=permissions)
                     .add_field(name="Permissions (as binary)", value=permission_binary)
                     .add_field(name="Mentionable?", value=bool_as_answer(role.mentionable))
                     .add_field(name="Displayed separately?", value=bool_as_answer(role.hoist))
                     .add_field(name="Integration role?", value=bool_as_answer(role.managed))
                     .add_field(name=members_name, value=members_value, inline=False)
                     .set_footer(text=footer)
                     )

        await ctx.send(embed=role_embed)

    async def _default_server_info(self, ctx, server):
        channel_count = len(server.channels)
        member_count = len(server.members)
        is_large = "(Very large!)" * bool(server.large)
        members_comment = f"{member_count} members {is_large}"
        icon = server.icon_url
        highest_role = server.role_hierarchy[0]
        nice_created_at = nice_time(server.created_at)
        footer = f"Created at: {nice_created_at} | ID: {server.id}"
        prefix = self.bot.str_prefix(self, server)

        if member_count < 20:
            member_field_name = f"Members ({member_count})"
            member_field_value = ', '.join([mem.mention for mem in server.members])
        else:
            member_field_name = f"Members"
            member_field_value = f"{member_count} (use '{prefix}info server members' to figure out the members)"

        server_embed = (discord.Embed(title=server.name, description=members_comment)
                       .add_field(name="Owner", value=server.owner)
                       .add_field(name="Highest Role", value=highest_role)
                       .add_field(name="Channel Count", value=len(server.channels))
                       .add_field(name="Role Count", value=len(server.roles))
                       .add_field(name=member_field_name, value=member_field_value)
                       .set_footer(text=footer))
        if icon:
            server_embed.set_thumbnail(url=icon)
            server_embed.colour = await url_color(icon)
        await ctx.send(embed=server_embed)

    @info.group(no_pm=True, aliases=['guild'], invoke_without_command=True)
    async def server(self, ctx):
        if ctx.subcommand_passed in ['server', 'guild']:
            await self._default_server_info(ctx, ctx.guild)
        elif ctx.invoked_subcommand is None:
            subcommands = '\n'.join(ctx.command.commands)
            await ctx.send(f"```\nAvailable server commands:\n{subcommands}```")

    @server.command()
    async def channels(self, ctx):
        await iterable_say(ctx.guild.channels, ', ', ctx=ctx)

    @server.command()
    async def members(self, ctx):
        members = sorted(ctx.guild.members, key=attrgetter("top_role"), reverse=True)
        await iterable_say(members, ', ', ctx=ctx, prefix='```css\n')

    @server.command()
    async def icon(self, ctx):
        server = ctx.guild
        await ctx.send(embed=_icon_embed(server, server.icon_url, "icon"))

    @server.command()
    async def roles(self, ctx):
        await iterable_say(ctx.guild.role_hierarchy, ', ', ctx=ctx)

    @commands.command(no_pm=True)
    async def userinfo(self, ctx, *, member : discord.Member=None):
        """Gets some userful info because why not"""
        if member is None:
            member = ctx.author
        await ctx.send(embed=await _user_embed(member))

    @commands.command(name="you", )
    async def botinfo(self, ctx):
        bot = self.bot
        user = bot.user
        appinfo = await bot.application_info()

        discord_lib = "{0.__title__}.py {0.__version__}".format(discord)
        app_icon_url = appinfo.icon_url
        user_icon_url = user.avatar_url or user.default_avatar_url
        bot_embed = (discord.Embed(title=appinfo.name, description=self.bot.description, colour=self.bot.colour)
                    .set_author(name=f"{user.name} | {appinfo.id}", icon_url=user_icon_url)
                    .add_field(name="Library", value=discord_lib)
                    .add_field(name="Python", value=str_join('.', sys.version_info[:3]))
                    .add_field(name="Owner", value=appinfo.owner)
                    .add_field(name="Uptime", value=bot.str_uptime)
                    .add_field(name="Cogs running", value=len(bot.cogs))
                    .add_field(name="Databases", value=len(bot.databases))
                    .add_field(name="Servers", value=len(bot.servers))
                    .add_field(name="Members I see", value=len(set(bot.get_all_members())))
                    .add_field(name="Channels I see", value=_ilen(bot.get_all_channels()))
                    )
        if app_icon_url:
            bot_embed.set_thumbnail(url=app_icon_url)
        for name, value in sorted(bot.counter.items()):
            bot_embed.add_field(name=name, value=value)
        await ctx.send(embed=bot_embed)

    async def _source(self, ctx, thing):
        lines = inspect.getsourcelines(thing)[0]
        await iterable_limit_say(lines, '', ctx=ctx, prefix='```py\n', escape_code=True)

    @commands.command()
    async def source(self, ctx, *, cmd: RecursiveBotCommandConverter):
        """Displays the source code for a particular command"""
        # TODO: use GitHub
        await self._source(ctx, cmd[1].callback)

    @commands.command()
    async def inrole(self, ctx, *roles : discord.Role):
        """
        Checks which members have a particular role(s)

        The role(s) are case sensitive.
        If you don't want to mention a role, please put it in quotes,
        especially if there's a space in the role name
        """
        has_roles = [mem for mem in ctx.guild.members
                     if any(role in mem.roles for role in roles)]
        fmt = f"Here are the members who have the {str_join(', ', roles)} roles"
        await ctx.send(fmt + f"```css\n{str_join(', ', has_roles)}```")

    @commands.command()
    async def permroles(self, ctx, *, perm: str):
        """
        Checks which roles have a particular permission

        The permission is case insensitive.
        """
        perm_attr = perm.replace(' ', '_').lower()
        roles_that_have_perms = [role for role in ctx.guild.roles
                                 if getattr(role.permissions, perm_attr)]
        fmt = f"Here are the roles who have the {perm.title()} perm."
        await ctx.send(fmt + f"```css\n{str_join(', ', roles_that_have_perms)}```")

    @commands.command(aliases=['av'])
    async def avatar(self, ctx, *, user: converter.ApproximateUser=None):
        if user is None:
            user = ctx.author
        avatar_url = user.avatar_url_as(format=None)
        colour = await user_color(user)
        nick = getattr(user, 'nick', None)
        description = f"*(Also known as \"{nick}\")*" * bool(nick)

        av_embed = (discord.Embed(colour=colour, description=description)
                   .set_author(name=f"{user}'s Avatar", icon_url=avatar_url, url=avatar_url)
                   #.add_field(name="Link", value=f"[Click me for avatar!]({avatar_url})")
                   .set_image(url=avatar_url)
                   .set_footer(text=f"ID: {user.id}")
                   )
        await ctx.send(embed=av_embed)

    @commands.command()
    async def cmdhistory(self, ctx):
        """Displays up to the last 50 commands you've input"""
        history = self.cmd_history[ctx.author]
        msg = (f"Your last {len(history)} commands:\n```\n{', '.join(history)}```"
               if history else "You have not input any commands...")
        await ctx.send(msg)

    async def on_command(self, ctx):
        self.cmd_history[ctx.author].append(ctx.message.content)

    @commands.command(usage=['pow', 'os.system'], aliases=['pyh'])
    async def pyhelp(self, ctx, thing):
        """Gives you the help string for a builtin python function.
        (or any sort of function, for that matter)
        """
        # Someone told me a "lib" already does this. Is that true? If so, what lib is it?
        with StringIO() as output:
            with redirect_stdout(output):
                help(thing)
            help_lines = output.getvalue().splitlines()
            await iterable_limit_say(help_lines, ctx=ctx)

def setup(bot):
    bot.add_cog(Meta(bot))
