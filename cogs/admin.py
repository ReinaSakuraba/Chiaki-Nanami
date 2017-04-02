import discord

from discord.ext import commands

from .utils import checks, errors
from .utils.converter import ArgumentParser, make_converter
from .utils.context_managers import redirect_exception
from .utils.database import Database
from .utils.misc import multi_replace, nice_time, ordinal, str_join

class Admin:
    """Admin-only commands"""

    def __init__(self, bot):
        self.bot = bot
        self.self_roles = Database("admin/selfroles.json", default_factory=list)
        self.member_messages = Database("admin/membermessages.json")
        self.bot.add_database(checks.server_roles)

    def __local_check(self, ctx):
        return bool(ctx.guild)

    @staticmethod
    def _check_role_position(ctx, role, action):
        author = ctx.author
        top_role = author.top_role
        if role >= top_role and not checks.is_owner_predicate(ctx):
            raise errors.InvalidUserArgument(f"You can't {action} a role higher than or equal "
                                             f"to your highest role (**{top_role}**)")

    @staticmethod
    async def _set_chiaki_role(ctx, key, role, action):
        # if role is not None:
            # self._check_role_position(ctx, role, action)
        checks.assign_role(ctx.guild, key, role)
        msg = (f"Made {role} an **{key} role**!" if role is not None else
               f"Reset the **{key}** role to **{checks.DEFAULT}**")
        await ctx.send(msg)

    @staticmethod
    async def _chiaki_roles(ctx, key):
        server = ctx.guild
        id = checks.get_role(server, key)
        role = discord.utils.get(server.roles, id=id)
        await ctx.send(f'**{role}** is your \"{key}\" role.')

    async def _chiaki_role_command(self, ctx, key, role):
        if role is None:
            await self._chiaki_roles(ctx, key)
        else:
            await self._set_chiaki_role(ctx, key, role, 'assign an {key} role to')

    @commands.command(name='adminrole', aliases=['ar'])
    async def admin_role(self, ctx, *, role: discord.Role=None):
        """Sets a role for the 'Admin' role. If no role is specified, it shows what role is assigned as the Admin role.

        Admins are a special type of administrator. They have access to most of the permission-related
        or server-related commands.
        Only one role can be assigned as Admin. Default role is Bot Admin.
        """
        await self._chiaki_role_command(ctx, checks.ChiakiRole.admin, role)

    @commands.command(name='modrole', aliases=['mr'])
    @checks.is_admin()
    async def mod_role(self, ctx, *, role: discord.Role=None):
        """Sets a role for the 'Moderator' role.
        If no role is specified, it shows what role is assigned as the Moderator role.

        Moderators mainly have access to most of the mod commands, such as mute, kick, and ban.
        Only one role can be assigned as Moderator. Default role is Bot Admin.
        """
        await self._chiaki_role_command(ctx, checks.ChiakiRole.mod, role)

    @commands.command(name='resetadminrole', aliases=['rar'])
    async def reset_admin_role(self, ctx):
        """Resets the Admin role to the default role."""
        await self._set_chiaki_role(ctx, checks.ChiakiRole.admin, None, 'remove an Admin role from')

    @commands.command(name='resetmodrole', aliases=['rmr'])
    async def reset_mod_role(self, ctx):
        """Resets the Admin role to the default role."""
        await self._set_chiaki_role(ctx, checks.ChiakiRole.mod, None, 'remove the Moderator role from')

    @commands.command(name='addselfrole', aliases=['asar', ])
    @checks.is_admin()
    async def add_self_role(self, ctx, *, role: discord.Role):
        """Adds a self-assignable role to the server

        A self-assignable role is one that you can assign to yourself
        using `{prefix}iam` or `{prefix}selfrole`
        """
        self_roles = self.self_roles[ctx.guild]
        if role.id in self_roles:
            raise errors.InvalidUserArgument("That role is already self-assignable... I think")
        self._check_role_position(ctx, role, "assign as a self role")
        self_roles.append(role.id)
        await ctx.send(f"**{role}** is now a self-assignable role!")

    @commands.command(name='removeselfrole', aliases=['rsar', ])
    @checks.is_admin()
    async def remove_self_role(self, ctx, *, role: discord.Role):
        """Removes a self-assignable role from the server

        A self-assignable role is one that you can assign to yourself
        using `{prefix}iam` or `{prefix}selfrole`
        """
        self._check_role_position(ctx, role, "remove as a self role")
        with redirect_exception((ValueError, "That role was never self-assignable... I think.")):
            self.self_roles[ctx.guild].remove(role.id)
        await ctx.send(f"**{role}** is no longer a self-assignable role!")

    @commands.command(name='listselfrole', aliases=['lsar'])
    @checks.is_admin()
    async def list_self_role(self, ctx):
        """List all the self-assignable roles in the server

        A self-assignable role is one that you can assign to yourself
        using `{prefix}iam` or `{prefix}selfrole`
        """
        self_roles_ids = self.self_roles[ctx.guild]
        self_roles = [discord.utils.get(ctx.guild.roles, id=id) for id in self_roles_ids]
        str_self_roles = str_join(', ', self_roles)
        with redirect_exception((discord.Forbidden, "I don't think I have the Manage Roles perm... or maybe the role is too high..."),
                                (discord.HTTPException, "Hm, it seems like this didn't work...")):
            await ctx.send(str_self_roles)

    async def _self_role(self, role_action, role):
        self_roles = self.self_roles[role.guild]
        if role.id not in self_roles:
            raise errors.InvalidUserArgument("That role is not self-assignable... :neutral_face:")
        await role_action(role)

    @commands.command(no_pm=True)
    async def iam(self, ctx, *, role: discord.Role):
        """Gives a self-assignable role (and only a self-assignable role) to yourself."""
        await self._self_role(ctx.author.add_roles, role)
        await ctx.send(f"You are now **{role}**... I think.")

    @commands.command(no_pm=True)
    async def iamnot(self, ctx, *, role: discord.Role):
        """Removes a self-assignable role (and only a self-assignable role) from yourself."""
        await self._self_role(ctx.author.remove_roles, role)
        await ctx.send(f"You are no longer **{role}**... probably.")

    @commands.command(no_pm=True)
    async def selfrole(self, ctx, *, role: discord.Role):
        """Gives or removes a self-assignable role (and only a self-assignable role)

        This depends on whether or not you have the role already.
        If you don't, it gives you the role. Otherwise it removes it.
        """
        author = ctx.author
        msg, role_action = ((f"You are no longer **{role}**... probably.", author.remove_roles)
                            if role in author.roles else
                            (f"You are now **{role}**... I think.", author.add_roles))
        await self._self_role(role_action, role)
        await ctx.send(msg)

    @commands.command(name='addrole', aliases=['adr'])
    @checks.admin_or_permissions(manage_roles=True)
    async def add_role(self, ctx, user: discord.Member, *, role: discord.Role):
        """Adds a role to a user

        This role must be lower than both the bot's highest role and your highest role.
        """
        # This normally won't raise an exception, so we have to check for that
        self._check_role_position(ctx, role, "add")
        with redirect_exception((discord.Forbidden, f"I can't give {user} {role}. Either I don't have the right perms, "
                                                     "or you're trying to add a role that's higher than mine"),
                                (discord.HTTPException, f"Giving {role} to {user} failed. Not sure why though...")):
            await user.add_roles(role)
        await ctx.send(f"Successfully gave {user} **{role}**, I think.")

    @commands.command(name='removerole', aliases=['rr'])
    @checks.admin_or_permissions(manage_roles=True)
    async def remove_role(self, ctx, user: discord.Member, *, role: discord.Role):
        """Removes a role from a user

        This role must be lower than both the bot's highest role and your highest role.
        Do not confuse this with `{prefix}deleterole`, which deletes a role from the server.
        """
        self._check_role_position(ctx, role, "remove")
        with redirect_exception((discord.Forbidden, f"I can't remove **{role}** from {user}. Either I don't have the right perms, "
                                                     "or you're trying to remove a role that's higher than mine"),
                                (discord.HTTPException, f"Removing {role} from {user} failed. Not sure why though...")):
            await user.remove_roles(role)
        await ctx.send(f"Successfully removed **{role}** from {user}, I think.")

    @commands.command(name='createrole', aliases=['crr'])
    @checks.is_admin()
    async def create_role(self, ctx, *args: str):
        """Creates a role with some custom arguments:

        `name`
        The name of the new role. This is the only required role.

        `-c / --color / --colour`
        Colour of the new role. Default is grey/black.

        `--perms / --permissions`
        Permissions of the new role. Default is no permissions (0).

        `-h / --hoist`
        Whether or not the role can be displayed separately. Default is false.

        `-m / --mentionable`
        Whether or not the role can be mentioned. Default is false.

        """
        author, guild = ctx.author, ctx.guild

        parser = ArgumentParser(description='Just a random role thing')
        parser.add_argument('name')
        parser.add_argument('-c', '--color', '--colour', nargs='?', default='#000000')
        parser.add_argument('--permissions', '--perms', nargs='+', type=int, default=0)
        parser.add_argument('--hoist', action='store_true')
        parser.add_argument('-m', '--mentionable', action='store_true')

        args = parser.parse_args(args)

        colour = make_converter(commands.ColourConverter, ctx, args.color).convert()

        permissions = discord.Permissions(args.permissions)
        if permissions.administrator and not (author.permissions.administrator or author.id == guild.owner.id):
            raise errors.InvalidUserArgument("You are trying to add a role with administrator permissions "
                                             "as a non-administrator. Please don't do that.")

        fields = {
            'name': args.name,
            'colour': colour,
            'permissions': permissions,
            'hoist': args.hoist,
            'mentionable': args.mentionable,
        }

        with redirect_exception((discord.Forbidden, "I think I need the **Manage Roles** perm to create roles."),
                                (discord.HTTPException, f"Creating role **{args.name}** failed, for some reason.")):
            await guild.create_role(**fields)
        await ctx.send(f"Successfully created **{args.name}**!")

    @commands.command(name='editrole', aliases=['er'])
    @checks.is_admin()
    async def edit_role(self, ctx, old_role: discord.Role, *args: str):
        """Edits a role with some custom arguments:

        `name`
        New name of the role. Default is the old role's name.

        `-c / --color / --colour`
        New colour of the role. Default is the old role's colour.

        `--perms / --permissions`
        New permissions of the role. Default is the old role's permissions.

        `-h / --hoist`
        Whether or not the role can be displayed separately. Default is false.

        `-m / --mentionable`
        Whether or not the role can be mentioned. Default is false.

        `--pos, --position`
        The new position of the role. This cannot be zero.
        """
        author, server = ctx.author, ctx.guild
        parser = ArgumentParser(description='Just a random role thing')
        parser.add_argument('-n', '--name', nargs='?', default=old_role.name)
        parser.add_argument('-c', '--color', '--colour', nargs='?', default=str(old_role.colour))
        parser.add_argument('--permissions', '--perms', nargs='+', type=int, default=old_role.permissions.value)
        parser.add_argument('--hoist', action='store_true')
        parser.add_argument('-m', '--mentionable', action='store_true')
        parser.add_argument('--pos', '--position', nargs='?', type=int, default=old_role.position)

        args = parser.parse_args(args)

        permissions = discord.Permissions(args.permissions)
        if permissions.administrator and not (author.permissions.administrator or author.id == server.owner.id):
            raise errors.InvalidUserArgument("You are trying to edit a role to have administrator permissions "
                                             "as a non-administrator. Please don't do that.")

        colour = make_converter(commands.ColourConverter, ctx, args.color).convert()
        fields = {
            'name': args.name,
            'colour': colour,
            'permissions': permissions,
            'hoist': args.hoist,
            'mentionable': args.mentionable,
            'position': args.position,
        }

        with redirect_exception((discord.Forbidden, "I need the **Manage Roles** perm to edit roles, I think."),
                                (discord.HTTPException, f"Editing role **{role.name}** failed, for some reason.")):
            await old_role.edit(**fields)
        await ctx.send(f"Successfully edited **{old_role}**!")

    @commands.command(name='deleterole', aliases=['delr'])
    @checks.is_admin()
    async def delete_role(self, ctx, *, role: discord.Role):
        """Deletes a role from the server

        Do not confuse this with `{prefix}removerole`, which deletes a role from the server.
        """
        self._check_role_position(ctx, role, "delete")
        with redirect_exception((discord.Forbidden, "I need the **Manage Roles** perm to delete roles, I think."),
                                (discord.HTTPException, f"Deleting role **{role.name}** failed, for some reason.")):
            await role.delete()
        await ctx.send(f"Successfully deleted **{role.name}**!")

    @commands.command(no_pm=True)
    @checks.admin_or_permissions(manage_guild=True)
    async def welcome(self, ctx, *, message: str):
        """Sets the bot's message when a member joins this server.

        The following special formats can be in the message:
        {user}     = the member that joined. If one isn't placed, it's placed at the beginning of the message.
        {server}   = Optional, the name of the server.
        {count}    = how many members are in the server now. ,
        {countord} = like {count}, but as an ordinal.
        {joinedat} = The date and time when the member joined
        """
        if "{user}" not in message:
            message = "{user} " + message
        self.member_messages.setdefault("join", {})[str(ctx.guild.id)] = message
        await ctx.send(f'Welcome message has been set to "*{message}*"')

    @commands.command(name='removewelcome', aliases=['rhi'])
    @checks.admin_or_permissions(manage_guild=True)
    async def remove_welcome(self, ctx, *, message: str):
        """Removes the bot's message when a member joins this server.
        """
        if self.member_messages.setdefault("join", {}).pop(str(ctx.guild.id), None):
            await ctx.send(f'Successfully removed the welcome message.')
        else:
            await ctx.send(f'This server never had a welcome message.')

    async def on_member_join(self, member):
        guild = member.guild
        message = self.member_messages.setdefault('join', {}).get(str(guild.id))
        if not message:
            return
        member_count = len(guild.members)

        replacements = {
            '{user}': member.mention,
            '{server}': str(guild),
            '{count}': member_count,
            '{countord}': ordinal(member_count),
            '{joinedat}': nice_time(member.joined_at)
        }

        message = multi_replace(message, replacements)
        await guild.default_channel.send(message)

    @commands.command(no_pm=True)
    @checks.admin_or_permissions(manage_guild=True)
    async def byebye(self, ctx, *, message: str):
        """Sets the bot's message when a member leaves this server"""
        self.member_messages.setdefault("leave", {})[str(ctx.guild.id)] = message
        await ctx.send(f"Leave message has been set to *{message}*")

    @commands.command(name='removebyebye', aliases=['rbye'])
    @checks.admin_or_permissions(manage_guild=True)
    async def remove_byebye(self, ctx, *, message: str):
        """Removes the bot's message when a member leaves this server."""
        if self.member_messages.setdefault("leave", {}).pop(str(ctx.guild.id), None):
            await ctx.send(f'Successfully removed the leave message.')
        else:
            await ctx.send(f'This server never had a leave message.')

    async def on_member_leave(self, member):
        guild = member.guild
        message = self.member_messages.setdefault("leave", {}).get(str(guild.id))
        if not message:
            return

        message = message.replace("{user}", member.mention)
        await guild.default_channel.send(message)

    @commands.command(no_pm=True)
    @checks.is_admin()
    async def prefix(self, ctx, *, prefix=None):
        """Sets a custom prefix for a this server cog.

        If no arguments are specified, it shows the custom prefixes for this server.
        """
        if prefix is None:
            prefixes = self.bot.custom_prefixes.get(ctx.guild, [self.bot.default_prefix])
            await ctx.send(f"{ctx.guild}'s custom prefix(es) are {', '.join(prefixes)}")
            return
        self.bot.custom_prefixes[ctx.guild] = [prefix]
        await ctx.send(f"Successfully set {ctx.guild}'s prefix to \"{prefix}\"!")

    @commands.command(name="addprefix", no_pm=True)
    @checks.is_admin()
    async def add_prefix(self, ctx, *, prefix):
        """Adds a prefix for this server"""
        prefixes = self.bot.custom_prefixes.setdefault(ctx.guild, [])
        if prefix in prefixes:
            await ctx.send(f"\"{prefix}\" was already added to **{name}**...")
        else:
            prefixes.append(prefix)
            await ctx.send(f"Successfully added prefix \"{prefix}\" to **{name}**!")

    @commands.command(name="removeprefix", aliases=['rpf'])
    @checks.is_admin()
    async def remove_prefix(self, ctx, *, prefix):
        """Removes a prefix for this server"""
        prefixes = self.bot.custom_prefixes.get(ctx.guild)
        if not prefixes:
            raise errors.InvalidUserArgument("This server doesn't use any custom prefixes")

        with redirect_exception((ValueError, f"\"{prefix}\" was never in **{name}**...")):
            prefixes.remove(prefix)
        await ctx.send("Successfully removed prefix \"{prefix}\" in **{name}**!")

    @commands.command(name="resetprefix", aliases=['clrpf'])
    @checks.is_admin()
    async def reset_prefix(self, ctx):
        """Resets the server's custom prefixes back to the default prefix ({prefix})"""
        if self.bot.custom_prefixes.pop(ctx.guild, None):
            await ctx.send(f"Done. **{ctx.guild}** no longer has any custom prefixes")
        else:
            await ctx.send(f"**{ctx.guild}** never had any custom prefixes...")

def setup(bot):
    bot.add_cog(Admin(bot), "Administrator", "Administration")
