import asyncio
import asyncqlio
import asyncpg
import contextlib
import discord
import enum

from datetime import datetime
from discord.ext import commands
from functools import partial
from itertools import starmap

from .utils import errors, prompt, search, time
from .utils.context_managers import redirect_exception, temp_attr, temp_message
from .utils.formats import multi_replace
from .utils.misc import nice_time, ordinal, str_join


_Table = asyncqlio.table_base()


class SelfRoles(_Table):
    guild_id = asyncqlio.Column(asyncqlio.BigInt)
    role_id = asyncqlio.Column(asyncqlio.BigInt, primary_key=True, unique=True)

class AutoRoles(_Table):
    guild_id = asyncqlio.Column(asyncqlio.BigInt, primary_key=True)
    role_id = asyncqlio.Column(asyncqlio.BigInt, primary_key=True)

class ServerMessage(_Table, table_name='server_messages'):
    guild_id = asyncqlio.Column(asyncqlio.BigInt, primary_key=True)
    is_welcome = asyncqlio.Column(asyncqlio.Boolean, primary_key=True)
    channel_id = asyncqlio.Column(asyncqlio.BigInt, default=-1, primary_key=True)
    enabled = asyncqlio.Column(asyncqlio.Boolean, default=False)
    delete_after = asyncqlio.Column(asyncqlio.SmallInt, default=0)
    message_text = asyncqlio.Column(asyncqlio.String(2000), default='', nullable=True)


class ServerMessageType(enum.Enum):
    leave = False
    welcome = True

    def __str__(self):
        return self.name


welcome_leave_message_check = partial(commands.has_permissions, manage_guild=True)


def special_message(message):
    return message if '{user}' in message else f'{{user}}{message}'


class LowerRole(commands.RoleConverter):
    async def convert(self, ctx, arg):
        role = await super().convert(ctx, arg)
        author = ctx.author

        top_role = author.top_role
        if role >= top_role and author != ctx.guild.owner:
            raise commands.BadArgument(f"This role ({role}) is higher than or equal "
                                       f"to your highest role ({top_role}).")

        return role


class LowerRoleSearch(search.RoleSearch, LowerRole):
    pass


async def _warn(warning, ctx):
    warning += "\n\n(Type `yes` or `no`)"

    def check(m):
        return m.content.lower() in {'yes', 'no', 'y', 'n'}

    try:
        answer = await prompt.prompt(warning, ctx, timeout=30, check=check)
    except asyncio.TimeoutError:
        raise commands.BadArgument("You took too long. Aborting.")
    else:
        if answer.content.lower() not in {'yes', 'y'}:
            raise commands.BadArgument("Aborted.")


async def _check_role(ctx, role, thing):
    if role.managed:
        raise commands.BadArgument("This is an integration role, I can't assign this to anyone!")

    # Assigning people with the @everyone role is not possible
    if role.is_default():
        message = ("Wow, good job. I'm just gonna grab some popcorn now..."
                   if ctx.message.mention_everyone else
                   "You're lucky that didn't do anything...")
        raise commands.BadArgument(message)

    if role.permissions.administrator:
        message = ("This role has the Administrator permission. "
                   "It's very dangerous and can lead to terrible things. "
                   f"Are you sure you wanna make this {thing} role?")
        await _warn(message, ctx)


async def _get_self_roles(ctx):
    server = ctx.guild
    query = ctx.session.select.from_(SelfRoles).where(SelfRoles.guild_id == server.id)

    getter = partial(discord.utils.get, server.roles)
    roles = (getter(id=row.role_id) async for row in query)
    # in case there are any non-existent roles
    return [r async for r in roles if r]


class SelfRole(search.RoleSearch):
    async def convert(self, ctx, arg):
        if not ctx.guild:
            raise commands.NoPrivateMessage

        self_roles = await _get_self_roles(ctx)
        if not self_roles:
            message = ("This server has no self-assignable roles. "
                       f"Use `{ctx.prefix}asar` to add one.")
            raise commands.BadArgument(message)

        with temp_attr(ctx.guild, 'roles', self_roles):
            try:
                return await super().convert(ctx, arg)
            except commands.BadArgument:
                raise commands.BadArgument(f'{arg} is not a self-assignable role...')


class AutoRole(search.RoleSearch):
    async def convert(self, ctx, arg):
        if not ctx.guild:
            raise commands.NoPrivateMessage

        role = await super().convert(ctx, arg)
        await _check_role(ctx, role, thing='an auto-assign')
        return role


class Prefix(commands.Converter):
    async def convert(self, ctx, argument):
        user_id = ctx.bot.user.id
        if argument.startswith((f'<@{user_id}>', f'<@!{user_id}>')):
            raise commands.BadArgument('That is a reserved prefix already in use.')
        return argument

class Admin:
    """Admin-only commands"""
    __aliases__ = "Administrator", "Administration"

    def __init__(self, bot):
        self.bot = bot
        self._md = self.bot.db.bind_tables(_Table)

    def __local_check(self, ctx):
        return bool(ctx.guild)

    @commands.command(name='addselfrole', aliases=['asar', ])
    @commands.has_permissions(manage_roles=True, manage_guild=True)
    async def add_self_role(self, ctx, *, role: LowerRoleSearch):
        """Adds a self-assignable role to the server

        A self-assignable role is one that you can assign to yourself
        using `{prefix}iam` or `{prefix}selfrole`
        """
        await _check_role(ctx, role, thing='a self-assignable')
        try:
            await ctx.session.add(SelfRoles(guild_id=ctx.guild.id, role_id=role.id))
        except asyncpg.UniqueViolationError:
            await ctx.send(f'{role} is already a self-assignable role.')
        else:
            await ctx.send(f"**{role}** is now a self-assignable role!")

    @commands.command(name='removeselfrole', aliases=['rsar', ])
    @commands.has_permissions(manage_roles=True, manage_guild=True)
    async def remove_self_role(self, ctx, *, role: SelfRole):
        """Removes a self-assignable role from the server

        A self-assignable role is one that you can assign to yourself
        using `{prefix}iam` or `{prefix}selfrole`
        """
        await ctx.session.remove(SelfRoles(guild_id=ctx.guild.id, role_id=role.id))
        await ctx.send(f"**{role}** is no longer a self-assignable role!")

    @commands.command(name='listselfrole', aliases=['lsar'])
    async def list_self_role(self, ctx):
        """List all the self-assignable roles in the server

        A self-assignable role is one that you can assign to yourself
        using `{prefix}iam` or `{prefix}selfrole`
        """
        self_roles = await _get_self_roles(ctx)
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
        query = ctx.session.select(AutoRoles).where(AutoRoles.guild_id == ctx.guild.id)
        auto_role = await query.first()

        if auto_role is None:
            await ctx.session.add(AutoRoles(guild_id=ctx.guild.id, role_id=role.id))
        elif auto_role.role_id == role.id:
            return await ctx.send("You silly baka, you've already made this auto-assignable!")
        else:
            auto_role.role_id = role.id
            await ctx.session.merge(auto_role)

        await ctx.send(f"I'll now give new members {role}. Hope that's ok with you (and them :p)")

    @commands.command(name='delautorole', aliases=['daar'])
    @commands.has_permissions(manage_roles=True, manage_guild=True)
    async def del_auto_assign_role(self, ctx):
        query = ctx.session.select(AutoRoles).where(AutoRoles.guild_id == ctx.guild.id)
        role = await query.first()
        if role is None:
            return await ctx.send("There's no auto-assign role here...")

        await ctx.session.remove(role)
        await ctx.send("Ok, no more auto-assign roles :(")

    async def _add_auto_role(self, member):
        server = member.guild
        async with self.bot.db.get_session() as session:
            query = session.select.from_(AutoRoles).where(AutoRoles.guild_id == server.id)
            role = await query.first()

        if role is None:
            return
        # TODO: respect the high verification level
        await member.add_roles(discord.Object(id=role.role_id))

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
    async def create_role(self, ctx, *, name: str):
        """Creates a role with a given name."""
        reason = f'Created through command from {ctx.author} ({ctx.author.id})'
        await ctx.guild.create_role(reason=reason, name=name)
        await ctx.send(f"Successfully created **{name}**!")

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
    @delete_role.error
    async def role_error(self, ctx, error):
        if not isinstance(error, commands.CommandInvokeError):
            return

        verb = ctx.command.callback.__name__.partition('_')[0]
        role = ctx.kwargs['name'] if verb == 'create' else ctx.kwargs['role']

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

    async def _get_server_message_setting(self, session, guild_id, thing):
        query = session.select(ServerMessage).where((ServerMessage.guild_id == guild_id)
                                                    & (ServerMessage.is_welcome == thing.value))
        return await query.first()

    async def _setdefault_server_message_setting(self, session, guild_id, thing):
        config = await self._get_server_message_setting(session, guild_id, thing)
        return config or ServerMessage(guild_id=guild_id, is_welcome=thing.value)

    async def _toggle_config(self, ctx, do_thing, *, thing, text):
        config = await self._setdefault_server_message_setting(ctx.session, ctx.guild.id, thing)    
        config.enabled = do_thing if do_thing is not None else not config.enabled
        await ctx.session.add(config)

        to_say = (f"Yay I will {text}" if config.enabled else
                  "Oki I'll just sit in my corner then :~")
        await ctx.send(to_say)

    async def _message_config(self, ctx, message, *, thing):
        config = await self._setdefault_server_message_setting(ctx.session, ctx.guild.id, thing)

        if message:
            config.message_text = message
            await ctx.session.add(config)
            await ctx.send(f"{thing.name.title()} message has been set to *{message}*")
        else:
            message = config.message_text
            to_say = f"I will say {message} to the user." if message else "I won't say anything..."
            await ctx.send(to_say)

    async def _channel_config(self, ctx, channel, *, thing):
        config = await self._setdefault_server_message_setting(ctx.session, ctx.guild.id, thing)

        if channel:
            config.channel_id = channel.id
            await ctx.session.add(config)
            await ctx.send(f'Ok, {channel.mention} it is then!')
        else:
            channel = self.bot.get_channel(config.channel_id)
            if not channel:
                message = ("I don't have a channel at the moment, "
                           f"set one with `{ctx.prefix}{ctx.command} my_channel`")
            else:
                message = f"I'm gonna say the {thing} message in {channel.mention}"
            await ctx.send(message)

    async def _delete_after_config(self, ctx, duration, *, thing):
        config = await self._setdefault_server_message_setting(ctx.session, ctx.guild.id, thing)

        if duration is None:
            duration = config.delete_after
            message = (f"I won't delete the {thing} message." if not duration or duration < 0 else
                       f"I will delete the {thing} message after {time.duration_units(duration)}.")
            await ctx.send(message)
        else:
            auto_delete = duration > 0
            config.delete_after = duration
            await ctx.session.add(config)
            message = (f"Ok, I'm deleting the {thing} message after {time.duration_units(duration)}" if auto_delete else
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
        await self._toggle_config(ctx, do_welcome, thing=ServerMessageType.welcome,
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
        await self._message_config(ctx, message, thing=ServerMessageType.welcome)

    @welcome.command(name='channel', aliases=['chnl'],
                     help=_channel_format.format(thing='greet the user'))
    @welcome_leave_message_check()
    async def welcome_channel(self, ctx, *, channel: discord.TextChannel=None):
        await self._channel_config(ctx, channel, thing=ServerMessageType.welcome)

    @welcome.command(name='delete', aliases=['del'], help=_delete_after_format.format(thing='welcome'))
    @welcome_leave_message_check()
    async def welcome_delete(self, ctx, duration: time.duration = None):
        await self._delete_after_config(ctx, duration, thing=ServerMessageType.welcome)

    @commands.group(aliases=['bye'], invoke_without_command=True)
    @welcome_leave_message_check()
    async def byebye(self, ctx, do_bye: bool = None):
        """Sets whether or not I announce when someone leaves the server.
        Specifying with no arguments will toggle it.
        """
        await self._toggle_config(ctx, do_bye, thing=ServerMessageType.leave,
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

        await self._message_config(ctx, message, thing=ServerMessageType.leave)

    @byebye.command(name='channel', aliases=['chnl'],
                    help=_channel_format.format(thing='mourn for the user'))
    @welcome_leave_message_check()
    async def byebye_channel(self, ctx, *, channel: discord.TextChannel = None):
        await self._channel_config(ctx, channel, thing=ServerMessageType.leave)

    @byebye.command(name='delete', aliases=['del'], help=_delete_after_format.format(thing='leave'))
    @welcome_leave_message_check()
    async def byebye_delete(self, ctx, duration: time.duration = None):
        await self._delete_after_config(ctx, duration, thing=ServerMessageType.leave)

    async def _maybe_do_message(self, member, thing, time):
        guild = member.guild
        async with self.bot.db.get_session() as session:
            config = await self._get_server_message_setting(session, guild.id, thing)
        if not (config and config.enabled):
            return

        channel_id = config.channel_id
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return

        message = config.message_text
        if not message:
            return

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

        delete_after = config.delete_after
        if delete_after <= 0:
            delete_after = None

        # Not using str.format because that will raise KeyError on anything surrounded in {}
        message = multi_replace(message, replacements)
        await channel.send(message, delete_after=delete_after)

    async def on_member_join(self, member):
        await self._maybe_do_message(member, ServerMessageType.welcome, member.joined_at)
        await self._add_auto_role(member)

    # Hm, this needs less repetition
    # XXX: Lower the repetition
    async def on_member_remove(self, member):
        await self._maybe_do_message(member, ServerMessageType.leave, datetime.utcnow())

    # ------------------------- PREFIX RELATED STUFF -------------------

    @commands.group(aliases=['prefixes'], invoke_without_command=True)
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

    @prefix.command(name='add', ignore_extra=False)
    @commands.has_permissions(manage_guild=True)
    async def add_prefix(self, ctx, prefix: Prefix):
        """Adds a custom prefix for this server.

        To have a word prefix, you should quote it and end it with a space, e.g.
        "hello " to set the prefix to "hello ". This is because Discord removes
        spaces when sending messages so the spaces are not preserved.

        (Unless, you want to do hellohelp or something...)

        Multi-word prefixes must be quoted also.
        """
        prefixes = self.bot.custom_prefixes.setdefault(ctx.guild, [])
        if prefix in prefixes:
            await ctx.send(f"\"{prefix}\" was already a custom prefix...")
        else:
            prefixes.append(prefix)
            await ctx.send(f"Successfully added prefix \"{prefix}\"!")

    @add_prefix.error
    async def prefix_add_error(self, ctx, error):
        print('handling', type(error), error)
        if isinstance(error, commands.TooManyArguments):
            await ctx.send("Nya~~! Too many! Go slower or put it in quotes!")

    @prefix.command(name='remove', ignore_extra=False)
    @commands.has_permissions(manage_guild=True)
    async def remove_prefix(self, ctx, prefix: Prefix):
        """Removes a prefix for this server.

        This is effectively the inverse to `{prefix}prefix add`.
        """
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


def setup(bot):
    bot.add_cog(Admin(bot))
