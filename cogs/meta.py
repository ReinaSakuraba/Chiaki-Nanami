import aiohttp
import discord
import inspect
import json
import random
import sys

from collections import defaultdict, deque
from contextlib import redirect_stdout
from discord.ext import commands
from io import StringIO
from itertools import islice
from operator import attrgetter

from .utils import converter
from .utils.compat import url_color, user_color
from .utils.context_managers import redirect_exception, temp_message
from .utils.converter import BotCommand, union
from .utils.errors import InvalidUserArgument, ResultsNotFound
from .utils.misc import str_join, nice_time, ordinal
from .utils.paginator import iterable_limit_say, iterable_say

def _icon_embed(idable, url, name):
    embed = (discord.Embed(title=f"{idable.name}'s {name}")
            .set_footer(text=f"ID: {idable.id}"))
    return embed.set_image(url=url) if url else embed

async def _mee6_stats(session, member):
    async with session.get(f"https://mee6.xyz/levels/{member.guild.id}?json=1&limit=-1") as r:
        levels = await r.json(content_type=None)
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

def default_last_n(n=50): return lambda: deque(maxlen=n)
class Meta:
    """Info related commands"""

    def __init__(self, bot):
        self.bot = bot
        self.cmd_history = defaultdict(default_last_n())
        self.last_members = defaultdict(default_last_n())
        self.session = aiohttp.ClientSession()

    def __unload(self):
        # Pray it closes
        self.bot.loop.create_task(self.session.close())

    @commands.command()
    @commands.guild_only()
    async def uinfo(self, ctx, *, user: discord.Member=None):
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

    @info.command()
    @commands.guild_only()
    async def user(self, ctx, *, member: converter.ApproximateUser=None):
        """Gets some userful info because why not"""
        await ctx.invoke(self.userinfo, member=member)

    @info.command()
    @commands.guild_only()
    async def mee6(self, ctx, *, member: converter.ApproximateUser=None):
        await ctx.invoke(self.rank, member=member)

    @commands.command()
    @commands.guild_only()
    async def rank(self, ctx, *, member: converter.ApproximateUser=None):
        """Gets mee6 info... if it exists"""
        if member is None:
            member = ctx.author
        avatar_url = member.avatar_url_as(format=None)

        with ctx.typing(), redirect_exception((json.JSONDecodeError, "No stats found. You don't have mee6 in this server... I think.")):
            async with temp_message(ctx, "Fetching data, please wait...") as message:
                stats = await _mee6_stats(self.session, member)

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
        prefix = self.bot.str_prefix(ctx.message)

        def bool_as_answer(b):
            return "YNeos"[not b::2]

        has_roles = [mem for mem in server.members if role in mem.roles]
        member_amount = len(has_roles)
        if member_amount > 20:
            members_name = "Members"
            members_value = f"{member_amount} (use {prefix}inrole '{role}' to figure out who's in that role)"
        else:
            members_name = f"Members ({member_amount})"
            members_value = str_join(", ", has_roles) or '-no one is in this role :(-'

        hex_role_color = str(role.colour).upper()
        permissions = role.permissions.value
        permission_binary = "{0:32b}".format(permissions)
        str_position = ordinal(role.position)
        nice_created_at = nice_time(role.created_at)
        description = f"Just chilling as {server}'s {str_position + 1} role"
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
        features = '\n'.join(server.features) or 'None'

        descrption = f"Owned by {server.owner}"
        prefix = self.bot.str_prefix(ctx.message)

        if member_count < 20:
            member_field_name = f"Members ({member_count})"
            member_field_value = ', '.join([mem.mention for mem in server.members])
        else:
            member_field_name = f"Members"
            member_field_value = f"{member_count} (use '{prefix}info server members' to figure out the members)"

        server_embed = (discord.Embed(title=server.name, description=descrption, timestamp=server.created_at)
                       .add_field(name="Default Channel", value=server.default_channel.mention)
                       .add_field(name="Highest Role", value=highest_role)
                       .add_field(name="Region", value=server.region)
                       .add_field(name="Channel Count", value=len(server.channels))
                       .add_field(name="Role Count", value=len(server.roles))
                       .add_field(name="Custom Emoji Count", value=len(server.emojis))
                       .add_field(name="Verification Level", value=server.verification_level)
                       .add_field(name="Explicit Content Filter", value=server.explicit_content_filter)
                       .add_field(name="Special Features", value=features)
                       .add_field(name=member_field_name, value=member_field_value, inline=False)
                       .set_footer(text=f'ID: {server.id}'))
        if icon:
            server_embed.set_thumbnail(url=icon)
            server_embed.colour = await url_color(icon)
        await ctx.send(embed=server_embed)

    @info.group(aliases=['guild'], invoke_without_command=True)
    @commands.guild_only()
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

    @server.command()
    async def emojis(self, ctx):
        if not ctx.guild.emojis:
            return await ctx.send("This server doesn't have any custom emojis. :'(")
        emojis = map('{0} = {0.name}'.format, ctx.guild.emojis)
        await iterable_say(emojis, ctx=ctx)

    @commands.command()
    @commands.guild_only()
    async def userinfo(self, ctx, *, member: discord.Member=None):
        """Gets some userful info because why not"""
        if member is None:
            member = ctx.author
        await ctx.send(embed=await _user_embed(member))

    @commands.command(name="you")
    async def botinfo(self, ctx):
        pass

    async def _source(self, ctx, thing):
        lines = inspect.getsourcelines(thing)[0]
        await iterable_limit_say(lines, '', ctx=ctx, prefix='```py\n', escape_code=True)

    @commands.command()
    async def source(self, ctx, *, cmd: BotCommand(recursive=True)):
        """Displays the source code for a particular command"""
        # TODO: use GitHub
        await self._source(ctx, cmd.callback)

    async def _inrole(self, ctx, *roles, predicate):
        has_roles = [mem for mem in ctx.guild.members if predicate(mem, *roles)]
        joined_roles = str_join(', ', roles)
        msg = (f"Here are the members who have the {joined_roles} role. ```css\n{str_join(', ', has_roles)}```"
               if has_roles else f"There are no members who have the {joined_roles} role. \U0001f641")
        await ctx.send(msg)

    @commands.command()
    @commands.guild_only()
    async def inrole(self, ctx, *, role: discord.Role):
        """
        Checks which members have a given role
        The role is case sensitive.
        Only one role can be specified. To look at multiple, use `{prefix}inanyrole` or `{prefix}inallrole`.
        """
        await self._inrole(ctx, role, predicate=lambda m, r: r in m.roles)

    @commands.command()
    @commands.guild_only()
    async def inanyrole(self, ctx, *roles: discord.Role):
        """
        Checks which members have any of the given role(s)

        The role(s) are case sensitive.
        If you don't want to mention a role, please put it in quotes,
        especially if there's a space in the role name
        """
        await self._inrole(ctx, *roles, predicate=lambda m, *r: any(r in m.roles for r in roles))

    @commands.command()
    @commands.guild_only()
    async def inallrole(self, ctx, *roles: discord.Role):
        """
        Checks which members have all of the given role(s)

        The role(s) are case sensitive.
        If you don't want to mention a role, please put it in quotes,
        especially if there's a space in the role name
        """
        await self._inrole(ctx, *roles, predicate=lambda m, *r: all(r in m.roles for r in roles))

    @commands.command()
    @commands.guild_only()
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

    async def display_permissions(self, ctx, thing, permissions, extra=''):
        value = permissions.value
        diff_mapper = '\n'.join([f"{'-+'[value]} {attr.title().replace('_', ' ')}" for attr, value in permissions])

        message = (f"The permissions {extra} for **{thing}** is **{value}**."
                   f"\nIn binary it's {bin(value)[2:]}"
                   f"\nThis implies the following values:"
                   f"\n```diff\n{diff_mapper}```"
                   )
        await ctx.send(message)

    @commands.command(aliases=['perms'])
    @commands.guild_only()
    async def permissions(self, ctx, *, member_or_role: union(discord.Member, discord.Role)=None):
        """Shows either a member's Permissions, or a role's Permissions"""
        if member_or_role is None:
            member_or_role = ctx.author
        permissions = getattr(member_or_role, 'permissions', None) or member_or_role.guild_permissions
        await self.display_permissions(ctx, member_or_role, permissions)

    @commands.command(aliases=['permsin'])
    @commands.guild_only()
    async def permissionsin(self, ctx, *, member: discord.Member=None):
        """Shows either a member's Permissions *in the channel*"""
        if member is None:
            member = ctx.author
        await self.display_permissions(ctx, member, ctx.channel.permissions_for(member), extra=f'in {ctx.channel.mention}')

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
        with StringIO() as output, redirect_stdout(output):
            help(thing)
            help_lines = output.getvalue().splitlines()
            await iterable_limit_say(help_lines, ctx=ctx)

    async def lastjoin(self, ctx, n: int=10):
        """Display the last n members that have joined the server. Default is 10. Maximum is 50."""
        if not 0 < n < 50:
            raise InvalidUserArgument("I can only show between 1 and 50 members. Sorry. :(")

        members = str_join(', ', islice(self.last_members[ctx.guild], n))
        message = (f'These are the last {n} members that have joined the server:```\ncss{members}```'
                   if members else "I don't think any members joined this server yet :(")
        await ctx.send(message)

    async def on_member_join(self, member):
        self.last_members[member.guild].append(member)

def setup(bot):
    bot.add_cog(Meta(bot))
