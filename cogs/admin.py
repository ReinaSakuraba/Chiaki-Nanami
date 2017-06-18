import contextlib
import discord

from discord.ext import commands
from functools import partial
from itertools import starmap

from .utils import checks, errors
from .utils.converter import ArgumentParser, duration
from .utils.context_managers import redirect_exception
from .utils.database import Database
from .utils.misc import duration_units, multi_replace, nice_time, ordinal, str_join

class Admin:
    """Admin-only commands"""
    __aliases__ = "Administrator", "Administration"

    def __init__(self, bot):
        self.bot = bot
        self.self_roles = Database("admin/selfroles.json", default_factory=list)
        self.welcome_message_config = Database("admin/onjoin.json", default_factory=dict)
        self.leave_message_config = Database("admin/onleave.json", default_factory=dict)
        self.bot.add_database(checks.server_roles)

    def __local_check(self, ctx):
        return bool(ctx.guild)

    @staticmethod
    def _check_role_position(member, role, action):
        if member.id == member.guild.owner.id:
            return

        top_role = author.top_role
        if role >= top_role:
            raise errors.InvalidUserArgument(f"You can't {action} a role higher than or equal "
                                             f"to your highest role (**{top_role}**)")

    @staticmethod
    async def _set_chiaki_role(ctx, key, role, action):
        # if role is not None:
            # self._check_role_position(ctx.author, role, action)
        checks.assign_role(ctx.guild, key, role)
        msg = (f"Made {role} an **{key} role**!" if role is not None else
               f"Reset the **{key}** role to **{checks.DEFAULT}**")
        await ctx.send(msg)

    @staticmethod
    async def _chiaki_roles(ctx, key):
        server = ctx.guild
        id = checks.get_role(server, key)
        role = discord.utils.get(server.roles, id=id) or checks.DEFAULT
        await ctx.send(f'**{role}** is your current \"{key}\" role.')

    async def _chiaki_role_command(self, ctx, key, role):
        if role is None:
            await self._chiaki_roles(ctx, key)
        else:
            await self._set_chiaki_role(ctx, key, role, 'assign an {key} role to')

    @commands.command(name='adminrole', aliases=['adr'])
    @checks.is_admin()
    async def admin_role(self, ctx, *, role: discord.Role=None):
        """Sets a role for the 'Admin' role. If no role is specified, it shows what role is assigned as the Admin role.

        Admins are a special type of administrator. They have access to most of the permission-related
        or server-related commands.
        Only one role can be assigned as Admin. Default role is a role named "Bot Admin".
        """
        await self._chiaki_role_command(ctx, checks.ChiakiRole.admin, role)

    @commands.command(name='modrole', aliases=['mr'])
    @checks.is_admin()
    async def mod_role(self, ctx, *, role: discord.Role=None):
        """Sets a role for the 'Moderator' role.
        If no role is specified, it shows what role is assigned as the Moderator role.

        Moderators mainly have access to most of the mod commands, such as mute, kick, and ban.
        Only one role can be assigned as Moderator. Default role is a role named "Bot Admin".
        """
        await self._chiaki_role_command(ctx, checks.ChiakiRole.mod, role)

    @commands.command(name='resetadminrole', aliases=['radr'])
    @checks.is_admin()
    async def reset_admin_role(self, ctx):
        """Resets the Admin role to the default role."""
        await self._set_chiaki_role(ctx, checks.ChiakiRole.admin, None, 'remove an Admin role from')

    @commands.command(name='resetmodrole', aliases=['rmr'])
    @checks.is_admin()
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
        self._check_role_position(ctx.author, role, "assign as a self role")
        self_roles.append(role.id)
        await ctx.send(f"**{role}** is now a self-assignable role!")

    @commands.command(name='removeselfrole', aliases=['rsar', ])
    @checks.is_admin()
    async def remove_self_role(self, ctx, *, role: discord.Role):
        """Removes a self-assignable role from the server

        A self-assignable role is one that you can assign to yourself
        using `{prefix}iam` or `{prefix}selfrole`
        """
        self._check_role_position(ctx.author, role, "remove as a self role")
        with redirect_exception((ValueError, "That role was never self-assignable... I think.")):
            self.self_roles[ctx.guild].remove(role.id)
        await ctx.send(f"**{role}** is no longer a self-assignable role!")

    @commands.command(name='listselfrole', aliases=['lsar'])
    async def list_self_role(self, ctx):
        """List all the self-assignable roles in the server

        A self-assignable role is one that you can assign to yourself
        using `{prefix}iam` or `{prefix}selfrole`
        """
        self_roles_ids = self.self_roles[ctx.guild]
        getter = partial(discord.utils.get, ctx.guild.roles)
        self_roles = [getter(id=id) for id in self_roles_ids]

        msg = (f'List of self-assignable roles: \n{str_join(", ", self_roles)}' 
               if self_roles else 'There are no self-assignable roles...')
        await ctx.send(msg)

    async def _self_role(self, role_action, role):
        self_roles = self.self_roles[role.guild]
        if role.id not in self_roles:
            raise errors.InvalidUserArgument("That role is not self-assignable... :neutral_face:")
        await role_action(role)

    @commands.command()
    async def iam(self, ctx, *, role: discord.Role):
        """Gives a self-assignable role (and only a self-assignable role) to yourself."""
        await self._self_role(ctx.author.add_roles, role)
        await ctx.send(f"You are now **{role}**... I think.")

    @commands.command()
    async def iamnot(self, ctx, *, role: discord.Role):
        """Removes a self-assignable role (and only a self-assignable role) from yourself."""
        await self._self_role(ctx.author.remove_roles, role)
        await ctx.send(f"You are no longer **{role}**... probably.")

    @commands.command()
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

    @commands.command(name='addrole', aliases=['ar'])
    @checks.admin_or_permissions(manage_roles=True)
    async def add_role(self, ctx, user: discord.Member, *, role: discord.Role):
        """Adds a role to a user

        This role must be lower than both the bot's highest role and your highest role.
        """
        # This normally won't raise an exception, so we have to check for that
        self._check_role_position(ctx.author, role, 'add')
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
        self._check_role_position(ctx.author, role, 'remove')
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

        colour = await ctx.command.do_conversion(ctx, discord.Colour, args.color)

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

        colour = await ctx.command.do_conversion(ctx, discord.Colour, args.color)

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

        Do not confuse this with `{prefix}removerole`, which removes a role from a member.
        """
        self._check_role_position(ctx.author, role, "delete")
        with redirect_exception((discord.Forbidden, "I need the **Manage Roles** perm to delete roles, I think."),
                                (discord.HTTPException, f"Deleting role **{role.name}** failed, for some reason.")):
            await role.delete()
        await ctx.send(f"Successfully deleted **{role.name}**!")

    # ---------------- WELCOME AND LEAVE MESSAGE STUFF -------------

    _message_format = """
        Sets the channel where I will {thing}. 
        If no arguments are given, it shows the current channel.

        By default it's the server's default channel. 
        If the channel gets deleted or doesn't exist, the message will 
        redirect to the server's default channel.
        """

    _delete_after_format = """
        Sets the time it takes for {thing} messages to be auto-deleted.
        Passing it with no arguments will return the current duration.

        A number less than or equal 0 will disable automatic deletion.
        """

    async def _channel_config(self, ctx, channel, *, thing):
        db = getattr(self, f'{thing}_message_config')
        if channel:
            db[ctx.guild]['channel'] = channel.id
            await ctx.send(f'Ok, {channel.mention} it is then!')
        else:
            channel_id = db[ctx.guild].get('channel')
            channel = self.bot.get_channel(channel_id) or ctx.guild.default_channel
            await ctx.send(f"I'm gonna say the {thing} message in {channel.mention}")

    async def _delete_after_config(self, ctx, duration, *, thing):
        db = getattr(self, f'{thing}_message_config')
        if duration is None:
            duration = db[ctx.guild].get('delete_after')
            message = (f"I won't delete the {thing} message." if not duration else 
                       f"I will delete the {thing} message after {duration_units(duration)}.")
            await ctx.send(message)
        else:
            auto_delete = duration > 0
            db[ctx.guild]['delete_after'] = duration if auto_delete else None
            message = (f"Ok, I'm deleting the {thing} message after {duration_units(duration)}" if auto_delete else
                       f"Ok, I won't delete the {thing} message.")
            await ctx.send(message)

    # TODO: Allow embeds in welcome messages
    # XXX: Should I actually do it though? It will be very complicated and Nadeko-like
    @commands.group(aliases=['hi'])
    @checks.admin_or_permissions(manage_guild=True)
    async def welcome(self, ctx):
        """Shows the current welcome message for the server, if one was provided."""
        if ctx.invoked_subcommand is None and not ctx.subcommand_passed:
            message = self.welcome_message_config[ctx.guild].get('message')
            await ctx.send(f'The current welcome message is {message}')

    @welcome.command(name='message', aliases=['msg'])
    async def welcome_message(self, ctx, *, message: str):
        """Sets the bot's message when a member joins this server.

        The following special formats can be in the message:
        `{{user}}`     = the member that joined. If one isn't placed, it's placed at the beginning of the message.
        `{{server}}`   = Optional, the name of the server.
        `{{count}}`    = how many members are in the server now. ,
        `{{countord}}` = like `{{count}}`, but as an ordinal.
        `{{joinedat}}` = The date and time when the member joined
        """
        if "{user}" not in message:
            message = "{user} " + message

        self.welcome_message_config[ctx.guild]['message'] = message
        await ctx.send(f"Welcome message has been set to *{message}*")

    @welcome.command(name='channel', aliases=['chnl'],
                     help=_message_format.format(thing='greet the user'))
    async def welcome_channel(self, ctx, *, channel: discord.TextChannel=None):
        await self._channel_config(ctx, channel, thing='welcome')

    @welcome.command(name='delete', aliases=['del'], help=_delete_after_format.format(thing='welcome'))
    @checks.admin_or_permissions(manage_guild=True)
    async def welcome_delete(self, ctx, duration: duration=None):
        await self._delete_after_config(ctx, duration, thing='welcome')

    @welcome.command(name='remove', aliases=['disable'])
    async def remove_welcome(self, ctx):
        """Removes the bot's message when a member joins this server."""
        with redirect_exception((KeyError, 'This server never had a welcome message.')):
            del self.welcome_message_config[ctx.guild]['message']
        await ctx.send('Successfully removed the welcome message.')

    async def on_member_join(self, member):
        guild = member.guild
        data = self.welcome_message_config[member.guild]
        message = data.get('message')
        if not message:
            return

        channel_id = data.get('channel')
        channel = self.bot.get_channel(channel_id) or guild.default_channel

        member_count = len(guild.members)

        replacements = {
            '{user}': member.mention,
            '{server}': str(guild),
            '{count}': str(member_count),
            '{countord}': ordinal(member_count),
            # TODO: Should I use %c...?
            '{joinedat}': nice_time(member.joined_at)
        }

        delete_after = data.get('delete_after')

        # Not using str.format because that will raise KeyError on anything surrounded in {}
        message = multi_replace(message, replacements)
        await channel.send(message, delete_after=delete_after)

    @commands.group(aliases=['bye'])
    @checks.admin_or_permissions(manage_guild=True)
    async def byebye(self, ctx):
        if ctx.invoked_subcommand is None and not ctx.subcommand_passed:
            message = self.leave_message_config[ctx.guild.id].get('message')
            await ctx.send(f'The current leave message is {message}')

    @byebye.command(name='message', aliases=['msg'])
    async def byebye_message(self, ctx, *, message):
        """Sets the bot's message when a member leaves this server

        Unlike {prefix}welcome, the only prefix you can specify is {{user}}.
        """

        if "{user}" not in message:
            message = "{user} " + message
        self.leave_message_config[str(ctx.guild.id)]['message'] = message
        await ctx.send(f"Leave message has been set to *{message}*")

    @byebye.command(name='channel', aliases=['chnl'],
                    help=_message_format.format(thing='mourn for the user'))
    async def byebye_channel(self, ctx, *, channel: discord.TextChannel=None):  
        await self._channel_config(ctx, channel, thing='leave')

    @byebye.command(name='delete', aliases=['del'], help=_delete_after_format.format(thing='leave'))
    async def byebye_delete(self, ctx, duration: duration=None):
        await self._delete_after_config(ctx, duration, thing='leave')

    @byebye.command(name='remove', aliases=['disable'])
    async def remove_byebye(self, ctx):
        """Removes the bot's message when a member leaves this server."""
        with redirect_exception((KeyError, 'This server never had a leave message.')):
            del self.leave_message_config[ctx.guild]['message']
        await ctx.send('Successfully removed the leave message.')

    # Hm, this needs less repetition
    # XXX: Lower the repetition
    async def on_member_remove(self, member):
        guild = member.guild
        data = self.leave_message_config[guild]
        message = data.get('message')
        if not message:
            return

        channel_id = data.get('channel')
        channel = self.bot.get_channel(channel_id) or guild.default_channel
        delete_after = data.get('delete_after')

        message = message.replace("{user}", str(member))
        await channel.send(message, delete_after=delete_after)

    # ------------------------- PREFIX RELATED STUFF -------------------

    @commands.group(aliases=['prefixes'])
    @checks.is_admin()
    async def prefix(self, ctx):
        """Shows the prefixes that you can use in this server."""
        if ctx.invoked_subcommand is not None:
            return

        prefixes = await self.bot.get_prefix(ctx.message)
        description = '\n'.join(starmap('`{0}.` {1}'.format, enumerate(prefixes, start=1)))
        embed = discord.Embed(title=f'Prefixes you can use in {ctx.guild}', 
                              colour=self.bot.colour, description=description)
        await ctx.send(embed=embed)

    @prefix.command(name='add')
    @checks.is_admin()
    async def add_prefix(self, ctx, *, prefix):
        """Adds a custom prefix for this server"""
        prefixes = self.bot.custom_prefixes.setdefault(ctx.guild, [])
        if prefix in prefixes:
            await ctx.send(f"\"{prefix}\" was already a custom prefix...")
        else:
            prefixes.append(prefix)
            await ctx.send(f"Successfully added prefix \"{prefix}\"!")

    @prefix.command(name='remove')
    @checks.is_admin()
    async def remove_prefix(self, ctx, *, prefix):
        """Removes a prefix for this server"""
        prefixes = self.bot.custom_prefixes.get(ctx.guild)
        if not prefixes:
            raise errors.InvalidUserArgument("This server doesn't use any custom prefixes")

        with redirect_exception((ValueError, f"\"{prefix}\" was never a custom prefix in this server...")):
            prefixes.remove(prefix)
        await ctx.send(f"Successfully removed \"{prefix}\"!")

    @prefix.command(name="reset")
    @checks.is_admin()
    async def reset_prefix(self, ctx):
        """Resets the server's custom prefixes back to the default prefix ({prefix})"""
        with redirect_exception((KeyError, f"**{ctx.guild}** never had any custom prefixes...")):
            del self.bot.custom_prefixes[ctx.guild]
        await ctx.send(f"Done. **{ctx.guild}** no longer has any custom prefixes")

    async def on_guild_role_delete(self, role):
        with contextlib.suppress(ValueError):
            self.self_roles[role.guild].remove(role.id)

def setup(bot):
    bot.add_cog(Admin(bot))
