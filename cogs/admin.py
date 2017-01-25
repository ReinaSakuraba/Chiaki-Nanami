import argparse
import discord
import shlex

from collections import defaultdict
from discord.ext import commands

from .utils import checks
from .utils.database import Database
from .utils.misc import str_join


def _get_chiaki_roles(server, role):
    role_ids = checks.server_roles[server].get(role)
    if role_ids is None:
        return None
    return [discord.utils.get(server.roles, id=id) for id in role_ids]

class Admin:
    """Admin-only commands"""
    __prefix__ = '=>'

    def __init__(self, bot):
        self.bot = bot
        self.self_roles = Database.from_json("admin/selfroles.json",
                                             default_factory=list)
        self.member_messages = Database.from_json("admin/membermessages.json",
                                                  default_factory=lambda: defaultdict(str))

    @commands.command(name='addadminrole', pass_context=True, aliases=['aar'])
    @checks.admin_or_permissions(manage_server=True)
    async def add_admin_role(self, ctx, *, role: discord.Role):
        """Adds a role for the 'Admins' role

        Admins are a special type of administrator. They have access to most of the permission-related
        or server-related commands.
        More than one role can be considered as "Admin"
        (This might be changed)
        """
        checks.add_admin_role(ctx.message.server, role)
        await self.bot.say(f"Made {role} an **Admin role**!")

    @commands.command(name='addmodrole', pass_context=True, aliases=['amr'])
    @checks.admin_or_permissions()
    async def add_mod_role(self, ctx, *, role: discord.Role):
        """Add a role from the 'Moderators' role

        Moderators mainly have access to most of the mod commands, such as mute, kick, and ban.
        More than one role can be considered as "Moderator"
        (This might be changed)
        """
        checks.add_mod_role(ctx.message.server, role)
        await self.bot.say(f"Made {role} an **Moderator role**!")

    async def _chiaki_roles(self, ctx, key):
        roles = _get_chiaki_roles(ctx.message.server, key)
        str_roles = str_join(', ', roles)
        if str_roles:
            await self.bot.say(f"Here are all the {key} roles: ```css\n{str_roles}```")
        else:
            await self.bot.say(f"I don't see any {key} roles.")

    @commands.command(name='admins', pass_context=True)
    async def admin_roles(self, ctx):
        """Gives you all the admin roles, I think"""
        await self._chiaki_roles(ctx, "admin")

    @commands.command(name='moderators', pass_context=True)
    async def mod_roles(self, ctx):
        """Gives you all the moderator roles, I think"""
        await self._chiaki_roles(ctx, "moderator")

    @commands.command(name='removeadminrole', pass_context=True,
                      aliases=['rar', 'remadminrole'])
    @checks.admin_or_permissions()
    async def remove_admin_role(self, ctx, *, role: discord.Role):
        """Removes a role from the 'Admins' role

        Admins are a special type of administrator. They have access to most of the permission-related
        or server-related commands.
        More than one role can be considered as "Admin"
        (This might be changed)
        """
        checks.add_admin_role(ctx.message.server, role)
        await self.bot.say(f"Removed **{role}** from Admins!")

    @commands.command(name='removemodrole',
                      pass_context=True, aliases=['rmr', 'remmodrole'])
    @checks.admin_or_permissions()
    async def remove_mod_role(self, ctx, *, role: discord.Role):
        """Removes a role from the 'Moderators' role

        More than one role can be considered as "Moderator"
        (This might be changed)
        """
        checks.add_mod_role(ctx.message.server, role)
        await self.bot.say(f"Made **{role}** an Moderators!")

    @commands.command(name='addselfrole', pass_context=True, aliases=['asar',])
    @checks.admin_or_permissions()
    async def add_self_role(self, ctx, *, role: discord.Role):
        """Adds a self-assignable role to the server

        A self-assignable role is one that you can assign to yourself
        using =>iam or =>selfrole
        """
        self_roles = self.self_roles[ctx.message.server]
        if role.id in self_roles:
            await self.bot.say("That role is already self-assignable... I think")
            return
        if role > ctx.message.author.top_role:
            await self.bot.say("You can't make a role that is higher than your highest role a self-role.")
            return
        self_roles.append(role.id)
        await self.bot.say(f"**{role}** is now a self-assignable role!")

    @commands.command(name='removeselfrole',
                      pass_context=True, aliases=['rsar', 'remselfrole'])
    @checks.admin_or_permissions()
    async def remove_self_role(self, ctx, *, role: discord.Role):
        """Removes a self-assignable role from the server

        A self-assignable role is one that you can assign to yourself
        using =>iam or =>selfrole
        """
        try:
            self.self_roles[ctx.message.server].remove(role.id)
        except ValueError:
            await self.bot.say("That role was never self-assignable... I think")
        else:
            await self.bot.say(f"**{role}** is no longer a self-assignable role!")

    @commands.command(name='listselfrole', pass_context=True, aliases=['lsar'])
    @checks.admin_or_permissions()
    async def list_self_role(self, ctx):
        """List all the self-assignable roles in the server

        A self-assignable role is one that you can assign to yourself
        using =>iam or =>selfrole
        """
        self_roles_ids = self.self_roles[ctx.message.server]
        self_roles = [discord.utils.get(server.roles, id=id) for id in self_roles_ids]
        str_self_roles = str_join(', ', self_roles)


    async def _self_role(self, member, role_action):
        server = member.server
        self_roles = self.self_roles[ctx.message.server]
        if role.id not in self_roles:
            await self.bot.say("That role is not self-assignable... :neutral_face:")
            return False
        await role_action(member, role)
        return True

    @commands.command(pass_context=True, no_pm=True)
    async def iam(self, ctx, *, role: discord.Role):
        """Gives a self-assignable role (and only a self-assignable role) to yourself."""
        if await self._self_role(ctx.message.author, self.bot.add_roles):
            await self.bot.say(f"You are now **{role}**... I think.")

    @commands.command(pass_context=True, no_pm=True)
    async def iamnot(self, ctx, *, role: discord.Role):
        """Removes a self-assignable role (and only a self-assignable role) to yourself."""
        if await self._self_role(ctx.message.author, self.bot.remove_roles):
            await self.bot.say(f"You are no longer **{role}**... probably.")

    @commands.command(pass_context=True, no_pm=True)
    async def selfrole(self, ctx, *, role: discord.Role):
        """Gives or removes a self-assignable role (and only a self-assignable role)

        This depends on whether or not you have the role already.
        If you don't, it gives you the role. Otherwise it removes it.
        """
        author = ctx.message.author
        if role in author.roles:
            msg = f"You are no longer **{role}**... probably."
            role_action = self.bot.remove_roles
        else:
            msg = f"You are now **{role}**... I think."
            role_action = self.bot.remove_roles
        if await self._self_role(author, role_action):
            await self.bot.say(msg)

    @commands.command(name='addrole', pass_context=True, no_pm=True, aliases=['ar'])
    @checks.admin_or_permissions(manage_roles=True)
    async def add_role(self, ctx, user: discord.Member, *, role: discord.Role):
        """Adds a role to a user

        This role must be lower than both the bot's highest role and your highest role.
        """
        author = ctx.message.author
        # This won't raise an exception, so we have to check for that
        if role >= author.top_role:
            await self.bot.say("You can't add a role that's higher than your highest role, I think")
            return

        try:
            await self.bot.add_roles(user, role)
        except discord.Forbidden:
            msg = (f"I can't give {user} {role}. Either I don't have the right perms, "
                    "or you're trying to add a role that's higher than mine")
        except discord.HTTPException:
            msg = f"Giving {role} to {user} failed, for some reason..."
        else:
            msg = f"Successfully gave {user} **{role}**, I think."
        await self.bot.say(msg)

    @commands.command(name='removerole', pass_context=True, no_pm=True, aliases=['rr'])
    @checks.admin_or_permissions(manage_roles=True)
    async def remove_role(self, ctx, user: discord.Member, *, role: discord.Role):
        """Removes a role from a user

        This role must be lower than both the bot's highest role and your highest role.
        Do not confuse this with =>deleterole, which deletes a role from the server.
        """
        author = ctx.message.author
        # This won't raise an exception, so we have to check for that
        if role >= author.top_role:
            await self.bot.say("You can't remove a role that's higher than your highest role, I think")
            return

        try:
            await self.bot.remove_roles(user, role)
        except discord.Forbidden:
            msg = (f"I can't remove **{role}** from {user}. Either I don't have the right perms, "
                    "or you're trying to remove a role that's higher than mine")
        except discord.HTTPException:
            msg = f"Removing **{role}** from {user} failed, for some reason."
        else:
            msg = f"Successfully removed **{role}** from {user}, I think."
        await self.bot.say(msg)

    @commands.command(name='createrole', pass_context=True, no_pm=True, aliases=['crr'])
    @checks.admin_or_permissions()
    async def create_role(self, ctx, *, args: str):
        """Creates a role with some custom arguments

        name                     The name of the new role. This is the only required role.
        -c/--color/--colour      Colour of the new role. Default is black.
        --perms/--permissions    Permissions of the new role. Default is no permissions (0).
        -h/--hoist               Whether or not the role can be displayed separately. Default is false.
        -m/--mentionable         Whether or not the role can be mentionable. Default is false.
        """
        author = ctx.message.author
        server = ctx.message.server
        if not server:
            await self.bot.say("You can't make roles in a private channel, I think.")
            return

        parser = argparse.ArgumentParser(description='Just a random role thing')
        parser.add_argument('name')
        parser.add_argument('-c', '--color', '--colour', nargs='?', default='#000000')
        parser.add_argument('--permissions', '--perms', nargs='+', type=int, default=0)
        parser.add_argument('--hoist', action='store_true')
        parser.add_argument('-m', '--mentionable', action='store_true')
        parser.add_argument('--pos', '--position', nargs='+', type=int, default=1)

        try:
            args = parser.parse_args(shlex.split(args))
        except Exception as e:
            await self.bot.say(str(e))
            return

        colour_arg = args.color or args.colour
        colour_converter = commands.ColourConverter(ctx, colour_arg)
        try:
            colour = colour_converter.convert()
        except commands.BadArgument:
            await self.bot.say(f"{colour_arg} is not a valid color. It should be hexadecimal.")

        permissions = discord.Permissions(args.permissions)
        if permissions.administrator and not (author.permissions.administrator or author == server.owner):
            await self.bot.say("You are trying to add a role with administrator permissions "
                               "as a non-administrator. Please don't do that.")
            return

        kwargs = {
            'name': args.name,
            'colour': colour,
            'permissions': permissions,
            'hoist': args.hoist,
            'mentionable': args.mentionable,
        }
        try:
            await self.bot.create_role(server, **kwargs)
        except discord.Forbidden:
            msg = "I need the **Manage Roles** perm to create roles, I think."
        except discord.HTTPException:
            msg = "Creating role **{args.name}** failed, for some reason."
        else:
            msg = f"Successfully created **{args.name}**!"
        await self.bot.say(msg)

    @commands.command(name='deleterole', pass_context=True, aliases=['delr'])
    @checks.admin_or_permissions()
    async def delete_role(self, ctx, *, role: discord.Role):
        """Deletes a role from the server

        Do not confuse this with =>removerole, which deletes a role from the server.
        """
        if role >= author.top_role:
            await self.bot.say("You can't delete a role that's higher than your highest role, I think")
            return

        try:
            await self.bot.delete_role(ctx.message.server, role)
        except discord.Forbidden:
            msg = f"I can't delete {role} because I don't have the **Manage Roles** perm, I think."
        except discord.HTTPException:
            msg = f"Deleting **{role}** failed, for some reason..."
        else:
            msg = "Successfully deleted **{role}**, I think."
        await self.bot.say(msg)

    async def editrole(self, ctx, role, *, args: str):
        pass

    @commands.command(pass_context=True)
    @checks.admin_or_permissions()
    async def welcome(self, ctx, *, message: str):
        """Sets the bot's message when a member joins this server"""
        self.member_messages["join"][ctx.message.server] = message
        await self.bot.say("Welcome message has been set")

    async def on_member_join(self, member):
        server = member.server
        message = self.member_messages["join"][server]
        if not message:
            return
        await self.bot.send_message(server, message)

    @commands.command(pass_context=True)
    @checks.admin_or_permissions()
    async def byebye(self, ctx, *, message: str):
        """Sets the bot's message when a member leaves this server"""
        self.member_messages["leave"][ctx.message.server] = message
        await self.bot.say("Leave message has been set")

    async def on_member_leave(self, member):
        server = member.server
        message = self.member_messages["leave"][server]
        if not message:
            return
        await self.bot.send_message(server, message)


def setup(bot):
    bot.add_cog(Admin(bot))
