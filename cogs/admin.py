import argparse
import discord
import operator

from datetime import datetime
from discord.ext import commands

from .utils import checks
from .utils.converter import bot_cog_default
from .utils.database import Database
from .utils.errors import InvalidUserArgument
from .utils.misc import multi_replace, nice_time, ordinal, str_join, try_call, try_async_call

def _sanitize_prefix(prefix):
    if prefix[-1].isalnum():
        raise InvalidUserArgument("Your prefix cannot end with a letter or number.")
    return prefix

class Admin:
    """Admin-only commands"""
    __prefix__ = '=>'

    def __init__(self, bot):
        self.bot = bot
        self.self_roles = Database.from_json("admin/selfroles.json", default_factory=list)
        self.member_messages = Database.from_json("admin/membermessages.json")
        self.bot.add_database(checks.server_roles)

    def _check_role_position(self, ctx, role, action):
        author, server = ctx.message.author, ctx.message.server
        top_role = author.top_role
        if role >= top_role and not checks.is_owner_predicate(ctx):
            raise InvalidUserArgument(f"You can't {action} a role higher than or equal "
                                      f"to your highest role (**{top_role}**)")

    async def _set_chiaki_role(self, ctx, key, role, action):
        # if role is not None:
            # self._check_role_position(ctx, role, action)
        checks.assign_role(ctx.message.server, key, role)
        msg = (f"Made {role} an **{key} role**!" if role is not None else
               f"Removed the **{key}** role, please set it back")
        await self.bot.say(msg)

    async def _try_action(self, func, *, on_success, on_forbidden, on_http_exc):
        alts = {
            discord.Forbidden: on_forbidden,
            discord.HTTPException: on_http_exc,
            }
        result = await try_async_call(func, on_success=on_success, exception_alts=alts)
        await self.bot.say(result.message)

    async def _chiaki_roles(self, ctx, key):
        server = ctx.message.server
        id = checks.get_role(server, key)
        role = discord.utils.get(server.roles, id=id)
        await self.bot.say(f'**{role}** is your \"{key}\" role.' if role is not None else
                           f'There are no "{key}" roles. Please set one soon.')

    @commands.command(name='setadminrole', pass_context=True, no_pm=True, aliases=['sar'])
    @checks.is_admin()
    async def set_admin_role(self, ctx, *, role: discord.Role):
        """Adds a role for the 'Admins' role

        Admins are a special type of administrator. They have access to most of the permission-related
        or server-related commands.
        More than one role can be considered as "Admin"
        (This might be changed)
        """
        await self._set_chiaki_role(ctx, checks.ChiakiRole.admin, role, 'assign an Admin role to')

    @commands.command(name='addmodrole', pass_context=True, no_pm=True, aliases=['amr'])
    @checks.is_admin()
    async def add_mod_role(self, ctx, *, role: discord.Role):
        """Add a role from the 'Moderators' role

        Moderators mainly have access to most of the mod commands, such as mute, kick, and ban.
        More than one role can be considered as "Moderator"
        (This might be changed)
        """
        await self._set_chiaki_role(ctx, checks.ChiakiRole.mod, role, 'assign an Moderator role to')

    @commands.command(name='admins', pass_context=True)
    async def admin_roles(self, ctx):
        """Gives you all the admin roles, I think"""
        await self._chiaki_roles(ctx, checks.ChiakiRole.admin)

    @commands.command(name='moderators', pass_context=True)
    async def mod_roles(self, ctx):
        """Gives you all the moderator roles, I think"""
        await self._chiaki_roles(ctx, checks.ChiakiRole.mod)

    @commands.command(name='removeadminrole', pass_context=True, no_pm=True, aliases=['rar'])
    @checks.is_admin()
    async def remove_admin_role(self, ctx):
        """Revokes a role from the 'Admins'

        Admins are a special type of administrator. They have access to most of the permission-related
        or server-related commands.
        More than one role can be considered as "Admin"
        (This might be changed)
        """
        await self._set_chiaki_role(ctx, checks.ChiakiRole.admin, None, 'remove an Admin role from')

    @commands.command(name='removemodrole', pass_context=True, no_pm=True, aliases=['rmr', 'remmodrole'])
    @checks.is_admin()
    async def remove_mod_role(self, ctx, *, role: discord.Role):
        """Revokes a role from the 'Moderators' role

        More than one role can be considered as "Moderator"
        (This might be changed)
        """
        await self._set_chiaki_role(ctx, checks.ChiakiRole.mod, None, 'remove an Admin role from')

    @commands.command(name='addselfrole', pass_context=True, no_pm=True, aliases=['asar',])
    @checks.is_admin()
    async def add_self_role(self, ctx, *, role: discord.Role):
        """Adds a self-assignable role to the server

        A self-assignable role is one that you can assign to yourself
        using =>iam or =>selfrole
        """
        self_roles = self.self_roles[ctx.message.server]
        if role.id in self_roles:
            raise InvalidUserArgument("That role is already self-assignable... I think")
        self._check_role_position(ctx, role, "assign as a self role")
        self_roles.append(role.id)
        await self.bot.say(f"**{role}** is now a self-assignable role!")

    @commands.command(name='removeselfrole', pass_context=True, no_pm=True, aliases=['rsar',])
    @checks.is_admin()
    async def remove_self_role(self, ctx, *, role: discord.Role):
        """Removes a self-assignable role from the server

        A self-assignable role is one that you can assign to yourself
        using =>iam or =>selfrole
        """
        self._check_role_position(ctx, role, "remove as a self role")
        result = try_call(lambda: self.self_roles[ctx.message.server].remove(role.id),
                          on_success=f"**{role}** is no longer a self-assignable role!",
                          exception_alts={ValueError: "That role was never self-assignable... I think."})
        await self.bot.say(result.message)


    @commands.command(name='listselfrole', pass_context=True, no_pm=True, aliases=['lsar'])
    @checks.is_admin()
    async def list_self_role(self, ctx):
        """List all the self-assignable roles in the server

        A self-assignable role is one that you can assign to yourself
        using =>iam or =>selfrole
        """
        self_roles_ids = self.self_roles[ctx.message.server]
        self_roles = [discord.utils.get(server.roles, id=id) for id in self_roles_ids]
        str_self_roles = str_join(', ', self_roles)

    async def _self_role(self, member, role_action, role):
        server = member.server
        self_roles = self.self_roles[server]
        if role.id not in self_roles:
            raise InvalidUserArgument("That role is not self-assignable... :neutral_face:")
        await role_action(member, role)

    @commands.command(pass_context=True, no_pm=True)
    async def iam(self, ctx, *, role: discord.Role):
        """Gives a self-assignable role (and only a self-assignable role) to yourself."""
        await self._self_role(ctx.message.author, self.bot.add_roles, role)
        await self.bot.say(f"You are now **{role}**... I think.")

    @commands.command(pass_context=True, no_pm=True)
    async def iamnot(self, ctx, *, role: discord.Role):
        """Removes a self-assignable role (and only a self-assignable role) from yourself."""
        await self._self_role(ctx.message.author, self.bot.remove_roles, role)
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
        await self._self_role(author, role_action, role)
        await self.bot.say(msg)

    @commands.command(name='addrole', pass_context=True, no_pm=True, aliases=['ar'])
    @checks.admin_or_permissions(manage_roles=True)
    async def add_role(self, ctx, user: discord.Member, *, role: discord.Role):
        """Adds a role to a user

        This role must be lower than both the bot's highest role and your highest role.
        """
        # This normally won't raise an exception, so we have to check for that
        self._check_role_position(ctx, role, "add")
        await self._try_action(lambda: self.bot.add_roles(user, role),
                               on_success=f"Successfully gave {user} **{role}**, I think.",
                               on_forbidden=(f"I can't give {user} {role}. Either I don't have the right perms, "
                                              "or you're trying to add a role that's higher than mine"),
                               on_http_exc=f"Giving {role} to {user} failed, for some reason...")

    @commands.command(name='removerole', pass_context=True, no_pm=True, aliases=['rr'])
    @checks.admin_or_permissions(manage_roles=True)
    async def remove_role(self, ctx, user: discord.Member, *, role: discord.Role):
        """Removes a role from a user

        This role must be lower than both the bot's highest role and your highest role.
        Do not confuse this with deleterole, which deletes a role from the server.
        """
        self._check_role_position(ctx, role, "remove")
        await self._try_action(lambda: self.bot.remove_roles(user, role),
                               on_success=f"Successfully removed **{role}** from {user}, I think.",
                               on_forbidden=(f"I can't remove **{role}** from {user}. Either I don't have the right perms, "
                                              "or you're trying to remove a role that's higher than mine"),
                               on_http_exc=f"Removing **{role}** from {user} failed, for some reason.")

    @commands.command(name='createrole', pass_context=True, no_pm=True, aliases=['crr'])
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
        author, server = ctx.message.author, ctx.message.server

        parser = argparse.ArgumentParser(description='Just a random role thing')
        parser.add_argument('name')
        parser.add_argument('-c', '--color', '--colour', nargs='?', default='#000000')
        parser.add_argument('--permissions', '--perms', nargs='+', type=int, default=0)
        parser.add_argument('--hoist', action='store_true')
        parser.add_argument('-m', '--mentionable', action='store_true')

        try:
            args = parser.parse_args(args)
        except Exception as e:
            raise commands.BadArgument(f"Failed to parse args. Exception: ```\n{e}```")
        except SystemExit:     # parse_args aborts the program on error (which sucks)
            raise commands.BadArgument(f"Failed to parse args. Exception unknown.")

        colour = commands.ColourConverter(ctx, args.color).convert()

        permissions = discord.Permissions(args.permissions)
        if permissions.administrator and not (author.permissions.administrator or author == server.owner):
            raise InvalidUserArgument("You are trying to add a role with administrator permissions "
                                      "as a non-administrator. Please don't do that.")

        fields = {
            'name': args.name,
            'colour': colour,
            'permissions': permissions,
            'hoist': args.hoist,
            'mentionable': args.mentionable,
        }

        await self._try_action(lambda: self.bot.create_role(server, **fields),
                               on_success=f"Successfully created **{args.name}**!",
                               on_forbidden="I need the **Manage Roles** perm to create roles, I think.",
                               on_http_exc=f"Creating role **{args.name}** failed, for some reason.")

    @commands.command(name='editrole', pass_context=True, no_pm=True, aliases=['er'])
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
        author, server = ctx.message.author, ctx.message.server
        parser = argparse.ArgumentParser(description='Just a random role thing')
        parser.add_argument('-n', '--name', nargs='?', default=old_role.name)
        parser.add_argument('-c', '--color', '--colour', nargs='?', default=str(old_role.colour))
        parser.add_argument('--permissions', '--perms', nargs='+', type=int, default=old_role.permissions.value)
        parser.add_argument('--hoist', action='store_true')
        parser.add_argument('-m', '--mentionable', action='store_true')
        parser.add_argument('--pos', '--position', nargs='?', type=int, default=None)

        try:
            args = parser.parse_args(args)
        except Exception as e:
            raise commands.BadArgument(f"Failed to parse args. Exception: ```\n{e}```")
        except SystemExit:     # parse_args aborts the program on error (which sucks)
            raise commands.BadArgument(f"Failed to parse args. Exception unknown")

        colour = commands.ColourConverter(ctx, args.color).convert()
        position = args.pos

        permissions = discord.Permissions(args.permissions)
        if permissions.administrator and not (author.permissions.administrator or author == server.owner):
            raise InvalidUserArgument("You are trying to edit a role to have administrator permissions "
                                      "as a non-administrator. Please don't do that.")

        kwargs = {
            'name': args.name,
            'colour': colour,
            'permissions': permissions,
            'hoist': args.hoist,
            'mentionable': args.mentionable,
        }
        async def attempt_edit():
            if position is not None:
                if not position:
                    raise InvalidUserArgument("The new position cannot be 0.")
                await self.bot.move_role(server, old_role, position)
            await self.bot.edit_role(server, old_role, **kwargs)

        await self._try_action(attempt_edit, on_success=f"Successfully edited **{old_role}**!",
                               on_forbidden="I need the **Manage Roles** perm to edit roles, I think.",
                               on_http_exc=f"Editing role **{old_role}** failed, for some reason.")

    @commands.command(name='deleterole', pass_context=True, no_pm=True, aliases=['delr'])
    @checks.is_admin()
    async def delete_role(self, ctx, *, role: discord.Role):
        """Deletes a role from the server

        Do not confuse this with removerole, which deletes a role from the server.
        """
        self._check_role_position(ctx, role, "delete")
        await self._try_action(lambda: self.bot.delete_role(ctx.message.server, role),
                               on_success=f"Successfully deleted **{role.name}**!",
                               on_forbidden="I need the **Manage Roles** perm to delete roles, I think.",
                               on_http_exc=f"Deleting role **{role.name}** failed, for some reason.")

    @commands.command(pass_context=True, no_pm=True)
    @checks.admin_or_permissions(manage_server=True)
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
        self.member_messages.setdefault("join", {})[ctx.message.server.id] = message
        await self.bot.say("Welcome message has been set")

    async def on_member_join(self, member):
        server = member.server
        message = self.member_messages.setdefault("join", {}).get(server.id)
        member_count = len(server.members)
        if not message:
            return

        replacements = {
            "{user}": member.mention,
            "{server}": str(server),
            "{count}": str(member_count),
            "{countord}": ordinal(member_count),
            "{joinedat}": nice_time(member.joined_at)
        }

        message = multi_replace(message, replacements)
        await self.bot.send_message(server, message)

    @commands.command(pass_context=True, no_pm=True)
    @checks.admin_or_permissions(manage_server=True)
    async def byebye(self, ctx, *, message: str):
        """Sets the bot's message when a member leaves this server"""
        self.member_messages.setdefault("leave", {})[ctx.message.server.id] = message
        await self.bot.say("Leave message has been set")

    async def on_member_leave(self, member):
        server = member.server
        message = self.member_messages["leave"].get(server.id)
        if not message:
            return

        replacements = {
            "{user}": member.mention,
            "{server}": str(server),
            "{count}": str(member_count),
            "{leftat}": f'{datetime.now() :%c}',
            "{joinedat}": nice_time(member.joined_at)
        }

        message = multi_replace(message, replacements)
        await self.bot.send_message(server, message)

    @commands.command(pass_context=True, no_pm=True)
    @checks.is_admin()
    async def prefix(self, ctx, cog: bot_cog_default("default"), prefix: _sanitize_prefix):
        """Sets a prefix for a particular cog (or "default")"""
        cog_references = self.bot.custom_prefixes[ctx.message.server]
        cog_references[cog] = [prefix]
        await self.bot.say(f"Successfully set **{cog}**'s prefix to \"{prefix}\"!")

    @commands.command(name="addprefix", pass_context=True, no_pm=True)
    @checks.is_admin()
    async def add_prefix(self, ctx, cog: bot_cog_default("default"), prefix: _sanitize_prefix):
        """Adds a prefix for a particular cog (or "default")"""
        cog_references = self.bot.custom_prefixes[ctx.message.server]
        prefixes = cog_references.setdefault(cog, [])
        if prefix in prefixes:
            await self.bot.say(f"\"{prefix}\" was already added to **{cog}**...")
        else:
            prefixes.append(prefix)
            await self.bot.say(f"Successfully added prefix \"{prefix}\" to **{cog}**!")

    @commands.command(name="removeprefix", pass_context=True, no_pm=True)
    @checks.is_admin()
    async def remove_prefix(self, ctx, cog: bot_cog_default("default"), prefix: _sanitize_prefix):
        """Removes a prefix for a particular cog (or "default")"""

        cog_references = self.bot.custom_prefixes[ctx.message.server]
        prefixes = cog_references.get(cog, [])
        result = try_call(lambda: prefixes.remove(prefix),
                          on_success=f"Successfully removed prefix \"{prefix}\" in **{cog}**!",
                          exception_alts={ValueError: f"\"{prefix}\" was never in **{cog}**..."})
        await self.bot.say(result.message)
        if not prefixes:
            cog_references.pop(cog, None)

    @commands.command(name="resetprefix", pass_context=True, no_pm=True, aliases=['clearprefix'])
    @checks.is_admin()
    async def reset_prefix(self, ctx, cog: bot_cog_default("default")):
        """Resets a prefix for a particular cog (or "default")"""

        cog_references = self.bot.custom_prefixes[ctx.message.server]
        result = try_call(lambda: cog_references.pop(cog),
                          on_success=f"Done. **{cog}** no longer has any custom prefixes",
                          exception_alts={KeyError: f"**{cog}** never had any custom prefixes..."})
        await self.bot.say(result.message)

    @commands.command(name="usedefaultprefix", pass_context=True, no_pm=True, aliases=['udpf'])
    @checks.is_admin()
    async def use_default_prefix(self, ctx, option: bool):
        """Sets whether or not the default prefix (either defined in the server
        or the bot's default prefix) should be used
        """
        cog_references = self.bot.custom_prefixes[ctx.message.server]
        cog_references["use_default_prefix"] = option
        default_prefix = cog_references.setdefault("default", [self.bot.default_prefix])
        msg = "{default_prefix if opt else 'Custom prefixes'} will now be used for all modules."
        await self.bot.say(msg)

def setup(bot):
    bot.add_cog(Admin(bot), "Administrator", "Administration")
