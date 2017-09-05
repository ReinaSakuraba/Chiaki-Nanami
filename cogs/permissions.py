import asyncqlio
import discord
import itertools

from collections import defaultdict, namedtuple
from discord.ext import commands
from operator import attrgetter

from .utils import cache, search
from .utils.converter import BotCommand, BotCogConverter
from .utils.dbtypes import AutoIncrementInteger
from .utils.misc import emoji_url, truncate, unique


ALL_MODULES_KEY = '*'


class _PermissionFormattingMixin:
    def _get_header(self):
        if self.command:
            return f'Command **{self.command}** is'
        elif self.cog == ALL_MODULES_KEY:
            return 'All modules are'
        else:
            return f'Cog **{self.cog}** is'


class PermissionDenied(_PermissionFormattingMixin, commands.CheckFailure):
    def __init__(self, message, *args):
        name, obj, *rest = args
        self.object = obj
        self.cog, _, self.command = _extract_from_node(name)

        super().__init__(message, *args)

    def __str__(self):
        return f'{self._get_header()} disabled for the {_get_class_name(self.object).lower()} "{self.object}".'


class InvalidPermission(_PermissionFormattingMixin, commands.CommandError):
    def __init__(self, message, *args):
        name, whitelisted, *rest = args
        self.whitelisted = whitelisted
        self.cog, _, self.command = _extract_from_node(name)

        super().__init__(message, *args)

    def __str__(self):
        message = {
            False: 'disabled',
            True: 'explicitly enabled',
            None: 'reset'
        }[self.whitelisted]

        return f'{self._get_header()} already {message}.'


_command_node = '{0.cog_name}.{0}'.format

def _extract_from_node(node):
    return node.partition('.')


def _get_class_name(obj):
    # Thanks discord.py
    return obj.__class__.__name__.replace('Text', '')


_Table = asyncqlio.table_base()


class CommandPermissions(_Table, table_name='permissions'):
    id = asyncqlio.Column(AutoIncrementInteger, primary_key=True)

    guild_id = asyncqlio.Column(asyncqlio.BigInt, index=True)
    snowflake = asyncqlio.Column(asyncqlio.BigInt, nullable=True)

    name = asyncqlio.Column(asyncqlio.String)
    whitelist = asyncqlio.Column(asyncqlio.Boolean)


# Some converter utilities I guess

class CommandName(BotCommand):
    async def convert(self, ctx, arg):
        command = await super().convert(ctx, arg)

        root = command.root_parent or command
        if root.name in {'enable', 'disable', 'undo'} or root.cog_name == 'Owner':
            raise commands.BadArgument("You can't modify this command.")

        return _command_node(command)


class CogName(BotCogConverter):
    async def convert(self, ctx, arg):
        cog = await super().convert(ctx, arg)
        name = type(cog).__name__

        if name in {'Permissions', 'Owner'}:
            raise commands.BadArgument("You can't modify this cog...")

        return name


PermissionEntity = search.union(discord.Member, discord.Role, discord.TextChannel)

# End of the converters I guess.


class Server(namedtuple('Server', 'server')):
    """This class is here to make sure that we can have an ID of None
    while still having the original server object.
    """
    __slots__ = ()

    @property
    def id(self):
        return None

    def __str__(self):
        return str(self.server)


ENTITY_EXPLANATION = """
        Entities can either be a channel, a role, or a server. More than
        one can be specified, but entities with names that consist of
        more than one word must be wrapped in quotes. If no entities
        are specified, then it will {action} {thing} for the entire
        server.
    """


_value_embed_mappings = {
    True: (0x00FF00, 'enabled', emoji_url('\N{WHITE HEAVY CHECK MARK}')),
    False: (0xFF0000, 'disabled', emoji_url('\N{NO ENTRY SIGN}')),
    None: (0x7289da, 'reset', emoji_url('\U0001f504')),
}


class Permissions:
    def __init__(self, bot):
        self.bot = bot
        self._md = self.bot.db.bind_tables(_Table)
        self.bot.loop.create_task(self._create_permissions())

    async def _create_permissions(self):
        async with self.bot.db.get_ddl_session() as session:
            for name, table in self._md.tables.items():
                await session.create_table(name, *table.columns)

    async def on_command_error(self, ctx, error):
        if isinstance(error, (PermissionDenied, InvalidPermission)):
            await ctx.send(error)

    async def _set_one_permission(self, session, guild_id, name, entity, whitelist):
        id = entity.id
        query = (session.select.from_(CommandPermissions)
                               .where((CommandPermissions.guild_id == guild_id)
                                      & (CommandPermissions.name == name)
                                      & (CommandPermissions.snowflake == id))
                 )

        row = await query.first()

        if row is None:
            if whitelist is None:
                raise InvalidPermission(f'{name} was neither disabled nor enabled...', name, whitelist)

            row = CommandPermissions(
                guild_id=guild_id,
                snowflake=id,
                name=name,
            )
        elif row.whitelist == whitelist:
            # something
            raise InvalidPermission(f"Already {whitelist}", name, whitelist)

        if whitelist is None:
            await session.remove(row)
            return

        row.whitelist = whitelist
        await session.add(row)

    async def _bulk_set_permissions(self, session, guild_id, name, *entities, whitelist):
        ids = unique(e.id for e in entities)
        await (session.delete.table(CommandPermissions)
                             .where((CommandPermissions.guild_id == guild_id)
                                    & (CommandPermissions.name == name)
                                    & (CommandPermissions.snowflake.in_(*ids)))
               )

        if whitelist is None:
            # We don't want it to recreate the permissions when reset.
            return

        columns = ('guild_id', 'snowflake', 'name', 'whitelist'),
        to_insert = [(guild_id, id, name, whitelist) for id in ids]
        conn = session.transaction.acquired_connection

        await conn.copy_records_to_table('permissions', columns=columns, records=to_insert)

    async def _set_permissions(self, session, guild_id, name, *entities, whitelist):
        if len(entities) == 1:
            await self._set_one_permission(session, guild_id, name, entities[0], whitelist=whitelist)
        else:
            await self._bulk_set_permissions(session, guild_id, name, *entities, whitelist=whitelist)

    @cache.cache(maxsize=None, make_key=lambda a, kw: a[-1])
    async def _get_permissions(self, session, guild_id):
        query = (session.select.from_(CommandPermissions)
                        .where(CommandPermissions.guild_id == guild_id)
                 )

        lookup = defaultdict(lambda: (set(), set()))
        async for row in await query.all():
            lookup[row.snowflake][row.whitelist].add(row.name)

        return dict(lookup)

    async def __global_check(self, ctx):
        if not ctx.guild:
            return True

        lookup = await self._get_permissions(ctx.session, ctx.guild.id)
        if not lookup:
            # "Fast" path
            return True

        dummy_server = Server(ctx.guild)

        objects = itertools.chain(
            [('user', ctx.author)],
            zip(itertools.repeat('role'), sorted(ctx.author.roles, reverse=True)),
            [('channel', ctx.channel),
             ('server', dummy_server)],
        )

        names = itertools.chain(
            map(_command_node, ctx.command.walk_parents()),
            (ctx.command.cog_name, ALL_MODULES_KEY)
        )

        for (typename, obj), name in itertools.product(objects, names):
            if obj.id not in lookup:
                continue

            if name in lookup[obj.id][True]:
                return True

            elif name in lookup[obj.id][False]:
                raise PermissionDenied(f'{name} is denied on the {typename} level', name, obj)

        return True

    async def _set_permissions_command(self, ctx, name, *entities, whitelist, type_):
        entities = entities or (Server(ctx.guild), )

        async with ctx.db.get_session() as session:
            # To avoid accidentally doing a query while the __global_check
            # is being processed, we have to do create another session.
            # I'm not sure if there is anything inherently wrong with this code
            # though, so if anyone is looking at this code and finds anything
            # wrong with it, please DM me ASAP.
            await self._set_permissions(session, ctx.guild.id, name, *entities, whitelist=whitelist)

            # If an exception was raised in the code above, the code below won't
            # run. We need to make sure that we actually commit the change before
            # invalidating the cache.
            assert self._get_permissions.invalidate(None, None, ctx.guild.id), \
                  "Something bad happened while invalidating the cache"

        colour, action, icon = _value_embed_mappings[whitelist]

        embed = (discord.Embed(colour=colour)
                 .set_author(name=f'{type_} {action}!', icon_url=icon)
                 )

        if name != ALL_MODULES_KEY:
            cog, _, name = _extract_from_node(name)
            embed.add_field(name=type_, value=name or cog)

        sorted_entities = sorted(entities, key=_get_class_name)

        for k, group in itertools.groupby(sorted_entities, _get_class_name):
            group = list(group)
            name = f'{k}{"s" * (len(group) != 1)}'
            value = truncate(', '.join(map(str, group)), 1024, '...')

            embed.add_field(name=name, value=value, inline=False)

        await ctx.send(embed=embed)

    def _make_command(value, name, *, desc=None):
        desc = desc or name
        cmd_doc_string = f"{desc} a given command."
        cog_doc_string = f"{desc} a given cog."
        all_doc_string = f"{desc} all cogs, and subsequently all commands."

        @commands.group(name=name)
        async def group(self, ctx):
            pass

        @group.command(name='command', help=cmd_doc_string)
        async def group_command(self, ctx, command: CommandName, *entities: PermissionEntity):
            await self._set_permissions_command(ctx, command, *entities,
                                                whitelist=value, type_='Command')

        # Providing these helper commands to allow users to "bulk"-disable certain
        # certain commands. Theoretically I COULD allow for ->enable command_or_module
        # but that would force me to make the commands case sensitive.
        @group.command(name='cog', help=cog_doc_string)
        async def group_cog(self, ctx, cog: CogName, *entities: PermissionEntity):
            await self._set_permissions_command(ctx, cog, *entities,
                                                whitelist=value, type_='Cog')

        @group.command(name='all', help=all_doc_string)
        async def group_all(self, ctx, *entities: PermissionEntity):
            await self._set_permissions_command(ctx, ALL_MODULES_KEY, *entities,
                                                whitelist=value, type_='All Modules')

        # Must return all of these otherwise the subcommands won't get added properly --
        # they will end up having no instance.
        return group, group_command, group_cog, group_all

    # The actual commands... yes it's really short.
    enable, enable_command, enable_cog, enable_all = _make_command(True, 'enable', desc='Enables')
    disable, disable_command, disable_cog, disable_all = _make_command(False, 'disable', desc='Disables')
    undo, undo_command, undo_cog, undo_all = _make_command(None, 'undo', desc='Resets the permissions for')

    del _make_command


def setup(bot):
    bot.add_cog(Permissions(bot))
