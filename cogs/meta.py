import discord
import itertools
import json
import os
import random

from collections import defaultdict, deque
from discord.ext import commands
from operator import attrgetter, itemgetter

from .utils import converter
from .utils.misc import str_join, filter_attr, status_color, image_from_url, nice_time, ordinal
from .utils.paginator import DelimPaginator, iterable_say

def _ilen(gen):
    return sum(1 for _ in gen)

def _icon_embed(idable, url, name):
    embed = (discord.Embed(title=f"{idable.name}'s {name}")
            .set_footer(text=f"ID: {idable.id}"))
    return embed.set_image(url=url) if url else embed

def _user_embed(member):
    avatar_url = member.avatar_url or member.default_avatar_url
    playing = f"Playing **{member.game}**"
    real_name = f"{member.name}#{member.discriminator}"
    roles = sorted(member.roles[1:], key=attrgetter("position"), reverse=True)
    server = member.server
    embed = discord.Embed(colour=member.colour, description=playing)
    for name, value in [("Real Name", real_name),
                        (f"Joined {server} at", nice_time(member.joined_at)),
                        ("Created at", nice_time(member.created_at)),
                        ("Highest role", member.top_role), ("Roles", str_join(', ', roles) or "-no roles-"),
                        ]:
        embed.add_field(name=name, value=value)
    embed.set_author(name=member.display_name, icon_url=avatar_url)
    embed.set_footer(text=f"ID: {member.id}")
    embed.set_thumbnail(url=avatar_url)

    return embed

async def _mee6_stats(session, member: discord.member):
    server = member.server
    async with session.get(f"https://mee6.xyz/levels/{server.id}?json=1&limit=-1") as r:
        levels = await r.json()
    players = levels["players"]
    user_stats = discord.utils.find(lambda e: e.get("id") == member.id, players)
    # Because lists start at 0
    if not user_stats:
        return None
    user_stats["rank"] = players.index(user_stats) + 1
    return user_stats

class Meta:
    """Info related commands"""
    __prefix__ = '?'

    def __init__(self, bot):
        self.bot = bot
        self.cmd_history = defaultdict(lambda: deque(maxlen=50))

    @commands.command(pass_context=True, no_pm=True)
    async def uinfo(self, ctx, *, user : discord.Member=None):
        """Gets some useful info because why not"""
        if user is None:
            user = ctx.message.author
        print(type(user))
        fmt = ("    Name: {0.name}\n"
               "      ID: {0.id}\n"
               " Hashtag: {0.discriminator}\n"
               "Nickname: {0.display_name}\n"
               " Created: {0.created_at}\n"
               "  Joined: {0.joined_at}\n"
               "   Roles: {1}\n"
               "  Status: {0.status}\n"
               )
        roles = list(map(str, user.roles[1:]))[::-1]
        roles = ', '.join(roles)
        await self.bot.say("```\n{}\n```".format(fmt.format(user, roles)))

    @commands.group(pass_context=True)
    async def info(self, ctx):
        """Super-command for all info-related commands"""
        if ctx.invoked_subcommand is None:
            subcommands = '\n'.join(ctx.command.commands.keys())
            await self.bot.say(f"```\nAvailable info commands:\n{subcommands}```")

    @info.command(pass_context=True, no_pm=True)
    async def user(self, ctx, *, member: converter.ApproximateUser=None):
        """Gets some userful info because why not"""
        await ctx.invoke(self.userinfo, member=member)

    @info.command(pass_context=True, no_pm=True)
    async def mee6(self, ctx, *, member: converter.ApproximateUser=None):
        await ctx.invoke(self.rank, member=member)

    @commands.command(pass_context=True, no_pm=True)
    async def rank(self, ctx, *, member: converter.ApproximateUser=None):
        """Gets mee6 info... if it exists"""
        message = await self.bot.say("Fetching data, please wait...")
        if member is None:
            member = ctx.message.author

        avatar_url = member.avatar_url or member.default_avatar_url
        try:
            stats = await _mee6_stats(self.bot.http.session, member)
        except json.JSONDecodeError:
            await self.bot.say("No stats found. You don't have mee6 in this server... I think.")
            return
        if not stats:
            await self.bot.say(f"This user ({member}) does not have a mee6 level. :frowning:")
            return

        description = f"Currently sitting at {stats['rank']}!"
        xp_progress = "{xp}/{lvl_xp} ({xp_percent}%)".format(**stats)
        xp_remaining = stats['lvl_xp'] - stats['xp']

        mee6_embed = discord.Embed(colour=member.colour, description=description)

        mee6_embed.set_author(name=member.display_name, icon_url=avatar_url)
        mee6_embed.set_thumbnail(url=avatar_url)
        mee6_embed.add_field(name="Level", value=stats['lvl'])
        mee6_embed.add_field(name="Total XP", value=stats['total_xp'])
        mee6_embed.add_field(name="Level XP",  value=xp_progress)
        mee6_embed.add_field(name="XP Remaining to next level",  value=xp_remaining)
        mee6_embed.set_footer(text=f"ID: {member.id}")

        await self.bot.delete_message(message)
        await self.bot.say(embed=mee6_embed)

    @info.command(pass_context=True)
    async def role(self, ctx, *, role: converter.ApproximateRole):
        get_bool_as_ans = lambda b: "Yes" if b else "No"

        has_roles = [mem for mem in ctx.message.server.members if role in mem.roles]
        member_amount = len(has_roles)
        if member_amount > 20:
            members_name = "Members"
            members_value = f"{member_amount} (use ?inrole '{role}' to figure out who's in that role)"
        else:
            members_name = f"Members ({member_amount})"
            members_value = str_join(", ", has_roles)

        hex_role_color = str(role.colour).upper()
        permissions = role.permissions.value
        permission_binary = "{0:32b}".format(permissions)
        str_position = ordinal(role.position)
        nice_created_at = nice_time(role.created_at)
        description = f"Just chilling as the {str_position} role"
        footer = f"Created at: {nice_created_at} | ID: {role.id}"

        # I think there's a way to make a solid color thumbnail, idk though
        role_embed = discord.Embed(title=role.name, colour=role.colour, description=description)
        role_embed.add_field(name="Colour", value=hex_role_color)
        role_embed.add_field(name="Permissions", value=permissions)
        role_embed.add_field(name="Permissions (as binary)", value=permission_binary)
        role_embed.add_field(name="Mentionable?", value=get_bool_as_ans(role.mentionable))
        role_embed.add_field(name="Displayed separately?", value=get_bool_as_ans(role.hoist))
        role_embed.add_field(name="Integration role?", value=get_bool_as_ans(role.managed))
        role_embed.add_field(name=members_name, value=members_value, inline=False)
        role_embed.set_footer(text=footer)

        await self.bot.say(embed=role_embed)

    async def _default_server_info(self, ctx):
        server = ctx.message.server

        channel_count = len(server.channels)
        member_count = len(server.members)
        is_large = "(Very large!)" * server.large
        members_comment = f"{member_count} members {is_large}"
        server_icon_url = server.icon_url
        # TODO: Find the average color of the server's icon and use that for the embed color
        colour = random.randrange(255 ** 3)
        highest_role = server.role_hierarchy[0]
        nice_created_at = nice_time(server.created_at)
        footer = f"Created at: {nice_created_at} | ID: {server.id}"

        if member_count < 20:
            member_field_name = f"Members ({member_count})"
            member_field_value = ', '.join([mem.mention for mem in server.members])
        else:
            member_field_name = f"Members"
            member_field_value = f"{member_count} (use '?info server members' to figure out the members)"
        server_embed = discord.Embed(title=server.name, colour=colour, description=members_comment)
        if server_icon_url:
            server_embed.set_thumbnail(url=server_icon_url)
        server_embed.add_field(name="Owner", value=server.owner)
        server_embed.add_field(name="Highest Role", value=highest_role)
        server_embed.add_field(name="Channel Count", value=len(server.channels))
        server_embed.add_field(name="Role Count", value=len(server.roles))
        server_embed.add_field(name=member_field_name, value=member_field_value)
        server_embed.set_footer(text=footer)
        await self.bot.say(embed=server_embed)

    @info.group(pass_context=True)
    async def server(self, ctx):
        print(ctx.subcommand_passed, ctx.invoked_subcommand)
        if not ctx.message.server:
            await self.bot.say("You are not in a server. Why are you using this command?")
            return
        if ctx.subcommand_passed == "server":
            await self._default_server_info(ctx)
        elif ctx.invoked_subcommand is None:
            subcommands = '\n'.join(ctx.command.commands.keys())
            await self.bot.say(f"```\nAvailable server commands:\n{subcommands}```")

    @server.command(pass_context=True)
    async def channels(self, ctx):
        await iterable_say(', ', ctx.message.server.channels, self.bot)

    @server.command(pass_context=True)
    async def members(self, ctx):
        members = sorted(ctx.message.server.members, key=attrgetter("top_role"), reverse=True)
        await iterable_say(', ', members, self.bot, prefix='```css\n')

    @server.command(pass_context=True)
    async def icon(self, ctx):
        server = ctx.message.server
        await self.bot.say(embed=_icon_embed(server, server.icon_url, "icon"))

    @server.command(pass_context=True)
    async def roles(self, ctx):
        await iterable_say(', ', ctx.message.server.role_hierarchy, self.bot)

    @commands.command(pass_context=True, no_pm=True)
    async def userinfo(self, ctx, *, member : discord.Member=None):
        """Gets some userful info because why not"""
        if member is None:
            member = ctx.message.author
        await self.bot.say(embed=_user_embed(member))

    @commands.command(name="you", pass_context=True)
    async def botinfo(self, ctx):
        bot = self.bot
        user = bot.user
        appinfo = await bot.application_info()
        description = ("\"{0}\"\nMade in Python using {1.__title__}.py {1.__version__}!"
                       ).format(appinfo.description, discord)
        app_icon_url = appinfo.icon_url
        print(app_icon_url)
        user_icon_url = user.avatar_url or user.default_avatar_url
        bot_embed = (discord.Embed(title=appinfo.name, description=description, colour=0xFFDDDD)
                    .set_author(name=f"{user.name} | {appinfo.id}", icon_url=user_icon_url)
                    .add_field(name="Owner", value=appinfo.owner)
                    .add_field(name="Uptime", value=bot.str_uptime)
                    .add_field(name="Cogs running", value=len(bot.cogs))
                    .add_field(name="Databases", value=len(bot.databases))
                    .add_field(name="Servers", value=len(bot.servers))
                    .add_field(name="Members I see", value=_ilen(bot.get_all_members()))
                    .add_field(name="Channels I see", value=_ilen(bot.get_all_channels()))
                    )
        if app_icon_url:
            bot_embed.set_thumbnail(url=app_icon_url)
        for name, value in sorted(bot.commands_counter.items(), key=itemgetter(0)):
            bot_embed.add_field(name=name, value=value)
        await self.bot.say(embed=bot_embed)


    @commands.command(pass_context=True)
    async def inrole(self, ctx, *roles : discord.Role):
        """
        Checks which members have a particular role(s)

        The role(s) are case sensitive.
        If you don't want to mention a role, please put it in quotes,
        especially if there's a space in the role name
        """
        has_roles = set(mem for mem in ctx.message.server.members
                        for role in roles if role in mem.roles)
        fmt = "Here are the members who have the {} roles".format(str_join(', ', roles))
        role_fmt = "```css\n{}```"
        await self.bot.say(fmt + role_fmt.format(str_join(', ', has_roles)))

    @commands.command(pass_context=True)
    async def permroles(self, ctx, *, perm: str):
        """
        Checks which roles have a particular permission

        The permission is case insensitive.
        """
        print("executed")
        perm_attr = perm.replace(' ', '_').lower()
        fmt = "Here are the roles who have the {} perm".format(perm.title())
        roles_that_have_perms = [role for role in ctx.message.server.roles
                                 if getattr(role.permissions, perm_attr)]
        role_fmt = "```css\n{}```"
        await self.bot.say(fmt + role_fmt.format(str_join(', ', roles_that_have_perms)))

    @commands.command(pass_context=True)
    async def permroles(self, ctx, *, perm: str):
        """
        Checks which roles have a particular permission

        The permission is case insensitive.
        """
        print("executed")
        perm_attr = perm.replace(' ', '_').lower()
        fmt = "Here are the roles who have the {} perm".format(perm.title())
        roles_that_have_perms = [role for role in ctx.message.server.roles
                                 if getattr(role.permissions, perm_attr)]
        role_fmt = "```css\n{}```"
        await self.bot.say(fmt + role_fmt.format(str_join(', ', roles_that_have_perms)))

    @commands.command(pass_context=True, aliases=['av'])
    async def avatar(self, ctx, *, user : converter.ApproximateUser=None):
        if user is None:
            user = ctx.message.author

        nick = ' ({})'.format(user.nick) * (user.nick is not None)
        av_fmt = f"**{user.name}#{user.discriminator}{nick}'s avatar**"
        avatar_url = user.avatar_url or user.default_avatar_url
        avatar = user.avatar or user.default_avatar

        # Pay no attention to this ugliness
        image, name = await image_from_url(avatar_url, avatar, self.bot.http.session)
        await self.bot.send_file(ctx.message.channel, name, content=av_fmt)
        os.remove(name)
        image.close()

    @commands.command(pass_context=True)
    async def cmdhistory(self, ctx):
        """Displays up to the last 50 commands you've input"""
        history = self.cmd_history[ctx.message.author]
        if not history:
            msg = "You have not input any commands..."
        else:
            msg = f"Your last {len(history)} commands:\n```\n{', '.join(history)}```"
        await self.bot.say(msg)

    async def on_command(self, cmd, ctx):
        self.cmd_history[ctx.message.author].append(ctx.message.content)

def setup(bot):
    bot.add_cog(Meta(bot))
