import discord

from discord.ext import commands

from .utils import checks, errors
from .utils.converter import ArgumentParser, bot_cog_default
from .utils.database import Database
from .utils.misc import multi_replace, nice_time, ordinal, str_join

def _sanitize_prefix(prefix):
    if prefix[-1].isalnum():
        raise commands.BadArgument("Your prefix cannot end with a letter or number.")
    return prefix

def _check_role_position(ctx, role, action):
    author = ctx.author
    top_role = author.top_role
    if role >= top_role and not checks.is_owner_predicate(ctx):
        raise errors.InvalidUserArgument(f"You can't {action} a role higher than or equal "
                                         f"to your highest role (**{top_role}**)")

class Admin:
    """Admin-only commands"""
    __prefix__ = '=>'

    def __init__(self, bot):
        self.bot = bot
        self.self_roles = Database.from_json("admin/selfroles.json", default_factory=list)
        self.member_messages = Database.from_json("admin/membermessages.json")
        self.bot.add_database(checks.server_roles)

    async def _set_chiaki_role(self, ctx, key, role, action):
        # if role is not None:
            # _check_role_position(ctx, role, action)
        checks.assign_role(ctx.guild, key, role)
        msg = (f"Made {role} an **{key} role**!" if role is not None else
               f"Reset the **{key}** role to **{checks.DEFAULT}**")
        await ctx.send(msg)

    async def _chiaki_roles(self, ctx, key):
        server = ctx.guild
        id = checks.get_role(server, key)
        role = discord.utils.get(server.roles, id=id)
        await ctx.send(f'**{role}** is your \"{key}\" role.')

    async def _chiaki_role_command(self, ctx, key, role):
        if role is None:
            await self._chiaki_roles(ctx, key)
        else:
            await self._set_chiaki_role(ctx, key, role, 'assign an {key} role to')

    @commands.command(name='adminrole', no_pm=True, aliases=['ar'])
    async def admin_role(self, ctx, *, role: discord.Role=None):
        """Sets a role for the 'Admin' role. If no role is specified, it shows what role is assigned as the Admin role.

        Admins are a special type of administrator. They have access to most of the permission-related
        or server-related commands.
        Only one role can be assigned as Admin. Default role is Bot Admin.
        """
        await self._chiaki_role_command(ctx, checks.ChiakiRole.admin, role)

    @commands.command(name='modrole', no_pm=True, aliases=['mr'])
    @checks.is_admin()
    async def mod_role(self, ctx, *, role: discord.Role=None):
        """Sets a role for the 'Moderator' role.
        If no role is specified, it shows what role is assigned as the Moderator role.

        Moderators mainly have access to most of the mod commands, such as mute, kick, and ban.
        Only one role can be assigned as Moderator. Default role is Bot Admin.
        """
        await self._chiaki_role_command(ctx, checks.ChiakiRole.mod, role)

    @commands.command(name='resetadminrole', no_pm=True, aliases=['rar'])
    async def reset_admin_role(self, ctx):
        """Resets the Admin role to the default role."""
        await self._set_chiaki_role(ctx, checks.ChiakiRole.admin, None, 'remove an Admin role from')

    @commands.command(name='resetmodrole', no_pm=True, aliases=['rmr'])
    async def reset_mod_role(self, ctx):
        """Resets the Admin role to the default role."""
        await self._set_chiaki_role(ctx, checks.ChiakiRole.mod, None, 'remove the Moderator role from')

    @commands.command(name='addselfrole', no_pm=True, aliases=['asar', ])
    @checks.is_admin()
    async def add_self_role(self, ctx, *, role: discord.Role):
        """Adds a self-assignable role to the server

        A self-assignable role is one that you can assign to yourself
        using =>iam or =>selfrole
        """
        self_roles = self.self_roles[ctx.guild]
        if role.id in self_roles:
            raise errors.InvalidUserArgument("That role is already self-assignable... I think")
        _check_role_position(ctx, role, "assign as a self role")
        self_roles.append(role.id)
        await ctx.send(f"**{role}** is now a self-assignable role!")

    @commands.command(name='removeselfrole', no_pm=True, aliases=['rsar', ])
    @checks.is_admin()
    async def remove_self_role(self, ctx, *, role: discord.Role):
        """Removes a self-assignable role from the server

        A self-assignable role is one that you can assign to yourself
        using =>iam or =>selfrole
        """
        _check_role_position(ctx, role, "remove as a self role")
        try:
            self.self_roles[ctx.guild].remove(role.id)
        except ValueError:
            await ctx.send("That role was never self-assignable... I think.")
        else:
            await ctx.send(f"**{role}** is no longer a self-assignable role!")

    @commands.command(name='listselfrole', no_pm=True, aliases=['lsar'])
    @checks.is_admin()
    async def list_self_role(self, ctx):
        """List all the self-assignable roles in the server

        A self-assignable role is one that you can assign to yourself
        using =>iam or =>selfrole
        """
        self_roles_ids = self.self_roles[ctx.guild]
        self_roles = [discord.utils.get(ctx.guild.roles, id=id) for id in self_roles_ids]
        str_self_roles = str_join(', ', self_roles)
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

    @commands.command(name='addrole', no_pm=True, aliases=['ar'])
    @checks.admin_or_permissions(manage_roles=True)
    async def add_role(self, ctx, user: discord.Member, *, role: discord.Role):
        """Adds a role to a user

        This role must be lower than both the bot's highest role and your highest role.
        """
        # This normally won't raise an exception, so we have to check for that
        _check_role_position(ctx, role, "add")
        try:
            await user.add_roles(role)
        except discord.Forbidden:
            await ctx.send(f"I can't give {user} {role}. Either I don't have the right perms, "
                           "or you're trying to add a role that's higher than mine")
        except discord.HTTPException:
            await ctx.send(f"Giving {role} to {user} failed, for some reason...")
        else:
            await ctx.send(f"Successfully gave {user} **{role}**, I think.")

    @commands.command(name='removerole', no_pm=True, aliases=['rr'])
    @checks.admin_or_permissions(manage_roles=True)
    async def remove_role(self, ctx, user: discord.Member, *, role: discord.Role):
        """Removes a role from a user

        This role must be lower than both the bot's highest role and your highest role.
        Do not confuse this with deleterole, which deletes a role from the server.
        """
        _check_role_position(ctx, role, "remove")
        try:
            await user.remove_roles(role)
        except discord.Forbidden:
            await ctx.send(f"I can't remove **{role}** from {user}. Either I don't have the right perms, "
                            "or you're trying to remove a role that's higher than mine")
        except discord.HTTPException:
            await ctx.send(f"Removing **{role}** from {user} failed, for some reason.")
        else:
            await ctx.send(f"Successfully removed **{role}** from {user}, I think.")

    @commands.command(name='createrole', no_pm=True, aliases=['crr'])
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

        colour_converter = commands.ColourConverter()
        colour_converter.prepare(ctx, args.color)
        colour = colour_converter.convert()

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

        try:
            await guild.create_role(**fields)
        except discord.Forbidden:
            await ctx.send("I need the **Manage Roles** perm to create roles, I think.")
        except discord.HTTPException:
            await ctx.send(f"Creating role **{args.name}** failed, for some reason.")
        else:
            await ctx.send(f"Successfully created **{args.name}**!")

    @commands.command(name='editrole', no_pm=True, aliases=['er'])
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

        colour_converter = commands.ColourConverter()
        colour_converter.prepare(ctx, args.color)
        colour = colour_converter.convert()

        permissions = discord.Permissions(args.permissions)
        if permissions.administrator and not (author.permissions.administrator or author.id == server.owner.id):
            raise errors.InvalidUserArgument("You are trying to edit a role to have administrator permissions "
                                             "as a non-administrator. Please don't do that.")

        kwargs = {
            'name': args.name,
            'colour': colour,
            'permissions': permissions,
            'hoist': args.hoist,
            'mentionable': args.mentionable,
            'position': args.position,
        }

        try:
            await old_role.edit(**kwargs)
        except discord.Forbidden:
            await ctx.send("I need the **Manage Roles** perm to edit roles, I think.")
        except discord.HTTPException:
            await ctx.send(f"Editing role **{old_role}** failed, for some reason.")
        else:
            await ctx.send(f"Successfully edited **{old_role}**!")

    @commands.command(name='deleterole', no_pm=True, aliases=['delr'])
    @checks.is_admin()
    async def delete_role(self, ctx, *, role: discord.Role):
        """Deletes a role from the server

        Do not confuse this with removerole, which deletes a role from the server.
        """
        _check_role_position(ctx, role, "delete")
        try:
            await role.delete()
        except discord.Forbidden:
            await ctx.send("I need the **Manage Roles** perm to delete roles, I think.")
        except discord.HTTPException:
            await ctx.send(f"Deleting role **{role.name}** failed, for some reason.")
        else:
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

    async def on_member_leave(self, member):
        guild = member.guild
        message = self.member_messages.setdefault("leave", {}).get(str(guild.id))
        if not message:
            return

        message = message.replace("{user}", member.mention)
        await guild.default_channel.send(message)

    @commands.command(no_pm=True)
    @checks.is_admin()
    async def prefix(self, ctx, cog: bot_cog_default("default"), prefix: _sanitize_prefix):
        """Sets a prefix for a particular cog (or "default")"""
        self.bot.custom_prefixes[ctx.guild][cog.name] = [prefix]
        await ctx.send(f"Successfully set **{cog.name}**'s prefix to \"{prefix}\"!")

    @commands.command(name="addprefix", no_pm=True)
    @checks.is_admin()
    async def add_prefix(self, ctx, cog: bot_cog_default("default"), prefix: _sanitize_prefix):
        """Adds a prefix for a particular cog (or "default")"""
        name = cog.name
        cog_references = self.bot.custom_prefixes[ctx.guild]
        prefixes = cog_references.setdefault(name, [])
        if prefix in prefixes:
            await ctx.send(f"\"{prefix}\" was already added to **{name}**...")
        else:
            prefixes.append(prefix)
            await ctx.send(f"Successfully added prefix \"{prefix}\" to **{name}**!")

    @commands.command(name="removeprefix", no_pm=True)
    @checks.is_admin()
    async def remove_prefix(self, ctx, cog: bot_cog_default("default"), prefix: _sanitize_prefix):
        """Removes a prefix for a particular cog (or "default")"""
        name = cog.name
        cog_references = self.bot.custom_prefixes[ctx.guild]
        prefixes = cog_references.get(name, [])
        try:
            prefixes.remove(prefix)
        except ValueError:
            await ctx.send(f"\"{prefix}\" was never in **{name}**...")
        else:
            if not prefixes:
                cog_references.pop(name, None)
            await ctx.send("Successfully removed prefix \"{prefix}\" in **{name}**!")

    @commands.command(name="resetprefix", no_pm=True, aliases=['clearprefix'])
    @checks.is_admin()
    async def reset_prefix(self, ctx, cog: bot_cog_default("default")):
        """Resets a prefix for a particular cog (or "default")"""
        name = cog.name
        cog_references = self.bot.custom_prefixes[ctx.guild]
        try:
            cog_references.pop(name)
        except KeyError:
            await ctx.send(f"**{name}** never had any custom prefixes...")
        else:
            ctx.send(f"Done. **{name}** no longer has any custom prefixes")

    @commands.command(name="usedefaultprefix", no_pm=True, aliases=['udpf'])
    @checks.is_admin()
    async def use_default_prefix(self, ctx, option: bool):
        """Sets whether or not the default prefix (either defined in the server
        or the bot's default prefix) should be used
        """
        cog_references = self.bot.custom_prefixes[ctx.guild]
        cog_references["use_default_prefix"] = option
        default_prefix = cog_references.setdefault("default", [self.bot.default_prefix])
        await ctx.send(f"{default_prefix if option else 'Custom prefixes'} will now be used for all modules.")

def setup(bot):
    bot.add_cog(Admin(bot), "Administrator", "Administration")
