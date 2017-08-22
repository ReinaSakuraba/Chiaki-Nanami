import asyncio
import contextlib
import copy
import discord

from datetime import datetime
from discord.ext import commands
from functools import partial
from itertools import starmap

from .utils import errors, search
from .utils.converter import ArgumentParser, duration
from .utils.context_managers import redirect_exception, temp_attr, temp_message
from .utils.database import Database
from .utils.formats import multi_replace
from .utils.misc import duration_units, nice_time, ordinal, str_join


def special_message(message):
    return message if '{user}' in message else f'{{user}}{message}'

welcome_leave_message_check = partial(commands.has_permissions, manage_guild=True)


class LowerRole(commands.RoleConverter):
    async def convert(self, ctx, arg):
        role = await super().convert(ctx, arg)
        author = ctx.author

        top_role = author.top_role
        if role >= top_role and author != ctx.guild.owner:
            raise commands.BadArgument(f"This role ({role}) is higher than or equal "
                                       f"to your highest role ({top_role}).")

        return role


class SelfRole(search.RoleSearch):
    async def convert(self, ctx, arg):
        # Assume this is invoked from the Admin cog, as we don't use self-roles
        # anywhere else.
        if not ctx.guild:
            raise commands.NoPrivateMessage

        self_roles = ctx.cog.get_self_roles(ctx.guild)

        with temp_attr(ctx.guild, 'roles', self_roles):
            try:
                return await super().convert(ctx, arg)
            except commands.BadArgument:
                raise commands.BadArgument(f'{arg} is not a self-assignable role...')


class AutoRole(search.RoleSearch):
    async def _warn(self, warning, ctx):
        prompt = warning + "\nType `yes` or `no`"
        def check(m):
            return (m.channel == ctx.channel
                    and m.author.id == ctx.author.id
                    and m.content.lower() in {'yes', 'no', 'y', 'n'})

        async with temp_message(ctx, warning) as m:
            try:
                answer = await ctx.bot.wait_for('message', timeout=30, check=check)
            except asyncio.TimeoutError:
                raise commands.BadArgument("You took too long. Aborting.")
            else:
                lowered = answer.lower()
                if lowered not in {'yes', 'y'}:
                    raise commands.BadArgument("Aborted.")

    async def convert(self, ctx, arg):
        if not ctx.guild:
            raise commands.NoPrivateMessage

        role = await super().convert(ctx, arg)
        if role.managed:
            raise commands.BadArgument("This is an integration role, I can't assign this to anyone!")

        # Assigning people with the @everyone role is not possible
        if role.is_default():
            # Most likely the person mentioned everyone.
            can_mention_everyone = ctx.author.permissions_in(ctx.channel).mention_everyone
            message = ("Wow, good job. I'm just gonna grab some popcorn now..."
                        if can_mention_everyone else
                       "You're lucky that didn't do anything...")
            raise commands.BadArgument(message)

        if role.permissions.administrator:
            await self._warn("This role has the Administrator permission. "
                             "It's very dangerous and can lead to terrible things. "
                             "Are you sure you wanna make this your auto-assign role?",
                             ctx)

        return role

class Admin:
    """Admin-only commands"""
    __aliases__ = "Administrator", "Administration"

    def __init__(self, bot):
        self.bot = bot
        self.self_roles = Database("admin/selfroles.json", default_factory=list)
        self.auto_assign_roles = Database("admin/autoroles.json")
        self.welcome_message_config = Database("admin/onjoin.json", default_factory=dict)
        self.leave_message_config = Database("admin/onleave.json", default_factory=dict)

    def __local_check(self, ctx):
        return bool(ctx.guild)

    def get_self_roles(self, server):
        ids = self.self_roles[server]
        getter = partial(discord.utils.get, server.roles)
        roles = (getter(id=id) for id in ids)
        # in case there are any non-existent roles
        return list(filter(None, roles))

    @commands.command(name='addselfrole', aliases=['asar', ])
    @commands.has_permissions(manage_roles=True, manage_guild=True)
    async def add_self_role(self, ctx, *, role: LowerRole):
        """Adds a self-assignable role to the server

        A self-assignable role is one that you can assign to yourself
        using `{prefix}iam` or `{prefix}selfrole`
        """
        self_roles = self.self_roles[ctx.guild]
        if role.id in self_roles:
            return await ctx.send("That role is already self-assignable... I think")

        self_roles.append(role.id)
        await ctx.send(f"**{role}** is now a self-assignable role!")

    @commands.command(name='removeselfrole', aliases=['rsar', ])
    @commands.has_permissions(manage_roles=True, manage_guild=True)
    async def remove_self_role(self, ctx, *, role: SelfRole):
        """Removes a self-assignable role from the server

        A self-assignable role is one that you can assign to yourself
        using `{prefix}iam` or `{prefix}selfrole`
        """
        self.self_roles[ctx.guild].remove(role.id)
        await ctx.send(f"**{role}** is no longer a self-assignable role!")

    @commands.command(name='listselfrole', aliases=['lsar'])
    async def list_self_role(self, ctx):
        """List all the self-assignable roles in the server

        A self-assignable role is one that you can assign to yourself
        using `{prefix}iam` or `{prefix}selfrole`
        """
        self_roles = self.get_self_roles(ctx.guild)
        msg = (f'List of self-assignable roles: \n{str_join(", ", self_roles)}'
               if self_roles else 'There are no self-assignable roles...')
        await ctx.send(msg)

    @commands.command()
    async def iam(self, ctx, *, role: SelfRole):
        """Gives a self-assignable role (and only a self-assignable role) to yourself."""
        if role in ctx.author.roles:
            return await ctx.send(f"You are {role} already...")

        await ctx.author.add_roles(role)
        await ctx.send(f"You are now **{role}**... I think.")

    @commands.command()
    async def iamnot(self, ctx, *, role: SelfRole):
        """Removes a self-assignable role (and only a self-assignable role) from yourself."""
        if role not in ctx.author.roles:
            return await ctx.send(f"You aren't {role} already...")

        await ctx.author.remove_roles(role)
        await ctx.send(f"You are no longer **{role}**... probably.")

    @commands.command()
    async def selfrole(self, ctx, *, role: SelfRole):
        """Gives or removes a self-assignable role (and only a self-assignable role)

        This depends on whether or not you have the role already.
        If you don't, it gives you the role. Otherwise it removes it.
        """
        author = ctx.author
        msg, role_action = ((f"You are no longer **{role}**... probably.", author.remove_roles)
                            if role in author.roles else
                            (f"You are now **{role}**... I think.", author.add_roles))
        await role_action(role)
        await ctx.send(msg)

    # ----------- Auto-Assign Role commands -----------------
    @commands.command(name='autorole', aliases=['aar'])
    @commands.has_permissions(manage_roles=True, manage_guild=True)
    async def auto_assign_role(self, ctx, role: AutoRole):
        """Sets a role that new members will get when they join the server.

        This can be removed with `{prefix}delautorole` or `{prefix}daar`
        """
        self.auto_assign_roles[ctx.guild.id] = role.id
        await ctx.send(f"I'll now give new members {role}. Hope that's ok with you (and them :p)")

    @commands.command(name='delautorole', aliases=['daar'])
    @commands.has_permissions(manage_roles=True, manage_guild=True)
    async def del_auto_assign_role(self, ctx):
        try:
            del self.auto_assign_roles[ctx.guild.id]
        except KeyError:
            await ctx.send("There's no auto-assign role here...")
        else:
            await ctx.send("Ok, no more auto-assign roles :(")

    async def _add_auto_role(self, member):
        server = member.guild
        role = self.auto_assign_roles.get(server)
        if role is None:
            return

        # TODO: respect the high verification level
        await member.add_roles(discord.Object(id=role))


    @commands.command(name='addrole', aliases=['ar'])
    @commands.has_permissions(manage_roles=True)
    async def add_role(self, ctx, member: discord.Member, *, role: LowerRole):
        """Adds a role to a user

        This role must be lower than both the bot's highest role and your highest role.
        """
        if role in member.roles:
            return await ctx.send(f'{member} already has **{role}**... \N{NEUTRAL FACE}')

        await member.add_roles(role)
        await ctx.send(f"Successfully gave {member} **{role}**, I think.")

    @commands.command(name='removerole', aliases=['rr'])
    @commands.has_permissions(manage_roles=True)
    async def remove_role(self, ctx, member: discord.Member, *, role: LowerRole):
        """Removes a role from a user

        This role must be lower than both the bot's highest role and your highest role.
        Do not confuse this with `{prefix}deleterole`, which deletes a role from the server.
        """
        if role not in member.roles:
            return await ctx.send(f"{member} doesn't have **{role}**... \N{NEUTRAL FACE}")

        await member.remove_roles(role)
        await ctx.send(f"Successfully removed **{role}** from {member}, I think.")

    @commands.command(name='createrole', aliases=['crr'])
    @commands.has_permissions(manage_roles=True)
    async def create_role(self, ctx, *args: str):
        """Creates a role with some custom arguments:

        `name`
        The name of the new role. This is the only required role.

        `-c / --color / --colour`
        Colour of the new role. Default is grey/black.

        `--perms / --permissions`
        Permissions of the new role. Default is no permissions (0).

        `-h / --hoist`
        Whether or not the role can be displayed separately. This is a flag. If it's not specified, it's False.

        `-m / --mentionable`
        Whether or not the role can be mentioned. This is a flag. If it's not specified , it's False.


        """
        author, guild = ctx.author, ctx.guild

        parser = ArgumentParser(add_help=False, allow_abbrev=False)
        parser.add_argument('name')
        parser.add_argument('-c', '--color', '--colour', nargs='?', default='#000000')
        parser.add_argument('--permissions', '--perms', nargs='?', type=int, default=0)
        parser.add_argument('-h', '--hoist', action='store_true')
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

        await guild.create_role(**fields)
        await ctx.send(f"Successfully created **{args.name}**!")

    @commands.command(name='editrole', aliases=['er'])
    @commands.has_permissions(manage_roles=True)
    async def edit_role(self, ctx, old_role: LowerRole, *args: str):
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
        Whether or not the role can be mentioned. This is a flag. If it's not added, it's False.

        `--pos, --position`
        The new position of the role. This cannot be zero.
        """
        author, server = ctx.author, ctx.guild
        parser = ArgumentParser(add_help=False, allow_abbrev=False)
        parser.add_argument('-n', '--name', nargs='?', default=old_role.name)
        parser.add_argument('-c', '--color', '--colour', nargs='?', default=str(old_role.colour))
        parser.add_argument('--permissions', '--perms', nargs='+', type=int, default=old_role.permissions.value)
        parser.add_argument('-h', '--hoist', nargs='?', default=old_role.hoist)
        parser.add_argument('-m', '--mentionable', nargs='?', default=old_role.mentionable)
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
            'position': args.pos,
        }

        await old_role.edit(**fields)
        await ctx.send(f"Successfully edited **{old_role}**!")

    @commands.command(name='deleterole', aliases=['delr'])
    @commands.has_permissions(manage_roles=True)
    async def delete_role(self, ctx, *, role: LowerRole):
        """Deletes a role from the server

        Do not confuse this with `{prefix}removerole`, which removes a role from a member.
        """
        await role.delete()
        await ctx.send(f"Successfully deleted **{role.name}**!")

    @add_role.error
    @remove_role.error
    @create_role.error
    @edit_role.error
    @delete_role.error
    async def role_error(self, ctx, error):
        if not isinstance(error, commands.CommandInvokeError):
            return

        verb = ctx.command.callback.__name__.partition('_')[0]
        role = ctx.args[2] if verb in ['create', 'edit'] else ctx.kwargs['role']

        print(type(error.original))
        if isinstance(error.original, discord.Forbidden):
            if not ctx.guild.me.permissions_in(ctx.channel).manage_roles:
                await ctx.send('{ctx.author.mention}, I need the Manage roles permission pls...')

            # We can't modify an add, remove, or delete an integration role, obviously.
            elif getattr(role, 'managed', False):       # ->createrole uses a string for the role.
                await ctx.send(f"{role} is an intergration role, I can't do anything with that!")

            # Assume the role was too high otherwise.
            else:
                await ctx.send('The role was higher than my highest role. '
                               'Check the hierachy please! \U0001f605')

        elif isinstance(error.original, discord.HTTPException):      # Something strange happened.
            # will probably refactor this out into another function later.
            if verb.endswith('e'):
                verb = verb[:-1]

            message = (f'{verb.title()}ing {role} failed for some reason... '
                        'Send this error to the dev if you can:\n'
                       f'{type(error).__name__}: {error}')

            await ctx.send(message)

    # ---------------- WELCOME AND LEAVE MESSAGE STUFF -------------

    _channel_format = """
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

    async def _toggle_config(self, ctx, do_thing, *, thing, text):
        db = getattr(self, f'{thing}_message_config')[ctx.guild]
        if do_thing is None:
            do_thing = not db.get('enabled', False)

        print(do_thing)
        db['enabled'] = do_thing
        to_say = (f"Yay I will {text}" if do_thing else
                  "Oki I'll just sit in my corner then :~")
        await ctx.send(to_say)

    async def _message_config(self, ctx, message, *, thing):
        db = getattr(self, f'{thing}_message_config')[ctx.guild]
        if message:
            db['message'] = message
            await ctx.send(f"{thing.title()} message has been set to *{message}*")
        else:
            message = db.get('message')
            to_say = f"I will say {message} to the user." if message else "I won't say anything..."
            await ctx.send(to_say)

    async def _channel_config(self, ctx, channel, *, thing):
        db = getattr(self, f'{thing}_message_config')[ctx.guild]
        if channel:
            db['channel'] = channel.id
            await ctx.send(f'Ok, {channel.mention} it is then!')
        else:
            channel_id = db.get('channel')
            channel = self.bot.get_channel(channel_id)
            if not channel:
                message = ("I don't have a channel at the moment, "
                           f"set one with `{ctx.prefix}{ctx.command} my_channel`")
            else:
                message = f"I'm gonna say the {thing} message in {channel.mention}"
            await ctx.send(message)

    async def _delete_after_config(self, ctx, duration, *, thing):
        db = getattr(self, f'{thing}_message_config')[ctx.guild]
        if duration is None:
            duration = db.get('delete_after')
            message = (f"I won't delete the {thing} message." if not duration else
                       f"I will delete the {thing} message after {duration_units(duration)}.")
            await ctx.send(message)
        else:
            auto_delete = duration > 0
            db['delete_after'] = duration if auto_delete else None
            message = (f"Ok, I'm deleting the {thing} message after {duration_units(duration)}" if auto_delete else
                       f"Ok, I won't delete the {thing} message.")
            await ctx.send(message)

    # TODO: Allow embeds in welcome messages
    # XXX: Should I actually do it though? It will be very complicated and Nadeko-like
    @commands.group(aliases=['hi'], invoke_without_command=True)
    @welcome_leave_message_check()
    async def welcome(self, ctx, do_welcome: bool = None):
        """Sets whether or not I announce when someone joins the server.
        Specifying with no arguments will toggle it.
        """
        await self._toggle_config(ctx, do_welcome, thing='welcome',
                                  text='welcome all new members to the server! ^o^')

    @welcome.command(name='message', aliases=['msg'])
    @welcome_leave_message_check()
    async def welcome_message(self, ctx, *, message: special_message = None):
        """Sets the bot's message when a member joins this server.

        The following special formats can be in the message:
        `{{user}}`     = The member that joined. If one isn't placed, it's placed at the beginning of the message.
        `{{uid}}`      = The ID of member that joined.
        `{{server}}`   = The name of the server.
        `{{count}}`    = How many members are in the server now.
        `{{countord}}` = Like `{{count}}`, but as an ordinal, eg instead of `5` it becomes `5th`.
        `{{time}}`     = The date and time when the member joined.
        """
        await self._message_config(ctx, message, thing='welcome')

    @welcome.command(name='channel', aliases=['chnl'],
                     help=_channel_format.format(thing='greet the user'))
    @welcome_leave_message_check()
    async def welcome_channel(self, ctx, *, channel: discord.TextChannel=None):
        await self._channel_config(ctx, channel, thing='welcome')

    @welcome.command(name='delete', aliases=['del'], help=_delete_after_format.format(thing='welcome'))
    @welcome_leave_message_check()
    async def welcome_delete(self, ctx, duration: duration = None):
        await self._delete_after_config(ctx, duration, thing='welcome')

    @commands.group(aliases=['bye'], invoke_without_command=True)
    @welcome_leave_message_check()
    async def byebye(self, ctx, do_bye: bool = None):
        """Sets whether or not I announce when someone leaves the server.
        Specifying with no arguments will toggle it.
        """
        await self._toggle_config(ctx, do_bye, thing='leave',
                                  text='mourn the loss of members. ;-;')

    @byebye.command(name='message', aliases=['msg'])
    @welcome_leave_message_check()
    async def byebye_message(self, ctx, *, message: special_message = None):
        """Sets the bot's message when a member leaves this server

        The following special formats can be in the message:
        `{{user}}`     = The member that joined. If one isn't placed, it's placed at the beginning of the message.
        `{{uid}}`      = The ID of member that left.
        `{{server}}`   = The name of the server.
        `{{count}}`    = How many members are in the server now.
        `{{countord}}` = Like `{{count}}`, but as an ordinal, eg instead of `5` it becomes `5th`.
        `{{time}}`     = The date and time when the member left the server.
        """

        await self._message_config(ctx, message, thing='leave')

    @byebye.command(name='channel', aliases=['chnl'],
                    help=_channel_format.format(thing='mourn for the user'))
    @welcome_leave_message_check()
    async def byebye_channel(self, ctx, *, channel: discord.TextChannel = None):
        await self._channel_config(ctx, channel, thing='leave')

    @byebye.command(name='delete', aliases=['del'], help=_delete_after_format.format(thing='leave'))
    @welcome_leave_message_check()
    async def byebye_delete(self, ctx, duration: duration = None):
        await self._delete_after_config(ctx, duration, thing='leave')

    async def _maybe_do_message(self, member, config, time):
        guild = member.guild
        config = config[member.guild]
        if not config.get('enabled', False):
            return

        message = config.get('message')
        if not message:
            return

        channel_id = config.get('channel')
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return

        delete_after = config.get('delete_after')

        member_count = len(guild.members)

        replacements = {
            '{user}': member.mention,
            '{uid}': str(member.id),
            '{server}': str(guild),
            '{count}': str(member_count),
            '{countord}': ordinal(member_count),
            # TODO: Should I use %c...?
            '{time}': nice_time(time)
        }


        # Not using str.format because that will raise KeyError on anything surrounded in {}
        message = multi_replace(message, replacements)
        await channel.send(message, delete_after=delete_after)

    async def on_member_join(self, member):
        await self._maybe_do_message(member, self.welcome_message_config, member.joined_at)
        await self._add_auto_role(member)

    # Hm, this needs less repetition
    # XXX: Lower the repetition
    async def on_member_remove(self, member):
        await self._maybe_do_message(member, self.leave_message_config, datetime.utcnow())

    # ------------------------- PREFIX RELATED STUFF -------------------

    @commands.group(aliases=['prefixes'])
    @commands.has_permissions(manage_guild=True)
    async def prefix(self, ctx):
        """Shows the prefixes that you can use in this server."""
        if ctx.invoked_subcommand is not None:
            return

        prefixes = self.bot.get_guild_prefixes(ctx.guild)
        # remove the duplicate mention prefix, so the mentions don't show up twice
        del prefixes[-1]

        description = '\n'.join(starmap('`{0}.` {1}'.format, enumerate(prefixes, start=1)))
        embed = discord.Embed(title=f'Prefixes you can use in {ctx.guild}',
                              colour=self.bot.colour, description=description)
        await ctx.send(embed=embed)

    @prefix.command(name='add')
    @commands.has_permissions(manage_guild=True)
    async def add_prefix(self, ctx, *, prefix):
        """Adds a custom prefix for this server"""
        prefixes = self.bot.custom_prefixes.setdefault(ctx.guild, [])
        if prefix in prefixes:
            await ctx.send(f"\"{prefix}\" was already a custom prefix...")
        else:
            prefixes.append(prefix)
            await ctx.send(f"Successfully added prefix \"{prefix}\"!")

    @prefix.command(name='remove')
    @commands.has_permissions(manage_guild=True)
    async def remove_prefix(self, ctx, *, prefix):
        """Removes a prefix for this server"""
        prefixes = self.bot.custom_prefixes.get(ctx.guild)
        if not prefixes:
            raise errors.InvalidUserArgument("This server doesn't use any custom prefixes")

        with redirect_exception((ValueError, f"\"{prefix}\" was never a custom prefix in this server...")):
            prefixes.remove(prefix)
        await ctx.send(f"Successfully removed \"{prefix}\"!")

    @prefix.command(name="reset")
    @commands.has_permissions(manage_guild=True)
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
