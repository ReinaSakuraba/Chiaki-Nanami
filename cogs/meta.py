import discord
import itertools
import json
import os

from discord.ext import commands
from operator import attrgetter, itemgetter

from .utils import converter
from .utils.misc import str_join, filter_attr, status_color, image_from_url

def _user_embed(member):
    avatar_url = member.avatar_url or member.default_avatar_url
    playing = f"Playing **{member.game}**"
    real_name = f"{member.name}#{member.discriminator}"
    roles = sorted(member.roles[1::], key=attrgetter("position"), reverse=True)
    server = member.server
    
    embed = discord.Embed(colour=member.colour, description=playing)
    for name, value in [("ID", member.id), ("Real Name", real_name),
                        (f"Joined {server} at", member.joined_at),
                        ("Created at", member.created_at), 
                        ("Highest role", member.top_role), ("Roles", str_join(', ', roles) or "-no roles-"),
                        ]:
        embed.add_field(name=name, value=value)
    embed.set_author(name=member.display_name, icon_url=avatar_url)
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
    async def user(self, ctx, *, member: discord.Member=None):
        """Gets some userful info because why not"""
        await ctx.invoke(self.userinfo, member=member)
        
    @info.command(pass_context=True, no_pm=True)
    async def mee6(self, ctx, *, member: converter.ApproximateUser=None):
        await ctx.invoke(self.rank, member=member)
    
    @commands.command(pass_context=True, no_pm=True)
    async def rank(self, ctx, *, member: converter.ApproximateUser=None):
        """Gets mee6 info... if it exists"""
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
        
        await self.bot.say(embed=mee6_embed)
        
    @info.command(pass_context=True)
    async def role(self, ctx, *, role: discord.Role):
        pass
        
    @info.command(pass_context=True)
    async def server(self, ctx):
        server = ctx.message.server
        highest_role = server.roles[-1]
        server_embed = discord.Embed()
        
    @commands.command(pass_context=True, no_pm=True)
    async def userinfo(self, ctx, *, member : discord.Member=None):
        """Gets some userful info because why not"""
        if member is None:
            member = ctx.message.author
        await self.bot.say(embed=_user_embed(member))
        
    @commands.command(name="you", pass_context=True)
    async def botinfo(self):
        pass
        # user = self.bot.user
        # embed = discord.Embed(colour=discord.Colour(0xFFE0E0),)
        
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
        print(image, type(image))
        await self.bot.send_file(ctx.message.channel, name, content=av_fmt)
        os.remove(name)
        image.close()
        
def setup(bot):
    print("meta setup")
    bot.add_cog(Meta(bot))
