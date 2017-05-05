import contextlib
import discord
import enum
import itertools

from collections import namedtuple
from discord.ext import commands
from operator import attrgetter, contains

from .utils import checks, errors
from .utils.compat import always_iterable, iterate
from .utils.converter import item_converter, BotCommand, BotCogConverter
from .utils.database import Database
from .utils.misc import str_join

def walk_parents(command):
    return itertools.takewhile(bool, iterate(attrgetter('parent'), command))

def walk_parent_names(command):
    return map(attrgetter('qualified_name'), walk_parents(command))

def first_non_none(iterable, default=None):
    return next(filter(lambda x: x is not None, iterable), default)

class Idable(namedtuple('Idable', 'original id')):
    def __new__(cls, original):
        return super().__new__(cls, original, original.id)

permissions_doc = """
    Sets the permissions for a particular {thing}.

    A {thing} can be allowed or blocked on one of 4 levels:
    server     = Affects this particular server
    channel    = Affects the channels specified, or the current channel if not specified
    role       = Affects the roles specified (at least one must be specified)
    user       = Affects the users specified on *this server only*

    {extra}
"""

def make_doc(thing, extra=''):
    def wrapper(func):
        func.__doc__ = permissions_doc.format(extra=extra, thing=thing)
        return func
    return wrapper

class PermLevel(enum.Enum):
    user        = (discord.Member, '({0.guild.id}, {0.author.id})'.format, False, )
    server      = (discord.Guild, attrgetter('guild.id'), True, )
    channel     = (discord.TextChannel, attrgetter('channel.id'), None, )
    # higher roles should be prioritised
    role        = (discord.Role, lambda ctx: reversed([role.id for role in ctx.author.roles]), False, )

    def __init__(self, type_, ctx_key, require_ctx):
        # True: Requires no args
        # False: Requires args
        # None: Falls back to ctx if no args are specified
        self.type = type_
        self.ctx_key = ctx_key
        self.require_ctx = require_ctx

    def __str__(self):
        return self.name.lower()

    async def parse_args(self, ctx, *args):
        if self.require_ctx and args:
            raise errors.InvalidUserArgument(f"{self.name} level requires that no arguments are passed.")
        elif self.require_ctx is False and not args:
            raise errors.InvalidUserArgument(f'Arguments are required for the {self.name} level.')

        if args:
            # This wastes memory, but I don't have much of a choice here
            # because using () produces an async generator, which isn't iterable.
            args = [await ctx.command.do_conversion(ctx, self.type, arg) for arg in args]
            return map(Idable, args)
        # Context objects don't have a "server" attribute, they have a "guild" attribute
        # The only reason why server is used in the enum is because of convenience for the user
        # As they'll be more familiar with the term "server" than "guild"
        attr = 'guild' if self == PermLevel.server else self.name
        # using a 1-elem tuple is faster than making a 1-elem list O.o
        return Idable(getattr(ctx, attr)),

level_getter = item_converter(PermLevel, key=str.lower, error_msg="Unrecognized level: {arg}")

def _emoji_url(emoji):
    return f'https://twemoji.maxcdn.com/2/72x72/{hex(ord(emoji))[2:]}.png'

dc = discord.Colour
class PermAction(namedtuple('PermAction', 'value action emoji colour')):
    def __new__(cls, arg):
        mode = arg.lower()
        if mode in ('allow', 'unlock', 'enable', ):
            return super().__new__(cls, value=True,  action='enabled',  emoji='\U00002705', colour=dc.green() )
        elif mode in ('none', 'reset', 'null', ):
            return super().__new__(cls, value=None,  action='reset',    emoji='\U0001f504', colour=dc.default() )
        elif mode in ('deny', 'lock', 'disable', ):
            return super().__new__(cls, value=False, action='disabled', emoji='\U000026d4', colour=dc.red())
        raise commands.BadArgument(f"Don't know what to do with {arg}.")

class BlockType(enum.Enum):
    blacklist = (dc.red(),   '\U000026d4')
    whitelist = (dc.green(), '\U00002705')

    def __init__(self, colour, emoji):
        self.colour = colour
        self.emoji = emoji

    def embed(self, user):
        return (discord.Embed(colour=self.colour)
               .set_author(name=f'User {self.name}ed', icon_url=_emoji_url(self.emoji))
               .add_field(name='User', value=str(user))
               .add_field(name='ID', value=user.id)
               )
del dc

command_perm_default = {i: {} for i in map(str, PermLevel)}

class Permissions:
    def __init__(self):
        self.permissions = Database('permissions.json', default_factory=command_perm_default.copy)
        self.other_permissions = Database('permissions2.json', default_factory=list)
        # Because checking a command's permissions will most likely be meaningless or unhelpful,
        # (since all it would return is whether or not a user can use a command)
        # a history is probably the best way to see the what has been inputted
        # This approach is taken by nadeko and is probably the best one here...
        self.permissions_history = Database('permissionshistory.json', default_factory=list)

    def __global_check(self, ctx):
        user_id = ctx.author.id
        if user_id in self.blacklisted_users:
            return False

        try:
            self._assert_is_valid_cog(ctx.command)
        except errors.InvalidUserArgument:
            return True

        cmd = ctx.command
        names = itertools.chain(walk_parent_names(cmd), (cmd.cog_name, ))
        results = (self._first_non_none_perm(name, ctx) for name in names)
        return first_non_none(results, True)

    @property
    def blacklisted_users(self):
        return self.other_permissions[BlockType.blacklist.name]

    @staticmethod
    def _context_attribute(level, ctx):
        return map(str, always_iterable(level.ctx_key(ctx)))

    @staticmethod
    def _cog_name(thing):
        return getattr(thing, 'cog_name', type(thing).__name__)

    def _assert_is_valid_cog(self, thing):
        name = self._cog_name(thing)
        if name in {'Owner', 'Help', 'Permissions'}:
            raise errors.InvalidUserArgument(f"I can't modify permissions from the module {name}.")

    def _perm_iterator(self, name, ctx):
        perms = self.permissions[name]
        for level in PermLevel:
            level_perms = perms[str(level)]
            try:
                ctx_attr = self._context_attribute(level, ctx)
            except AttributeError:      # ctx_attr was probably None
                continue
            yield first_non_none(map(level_perms.get, ctx_attr))

    def _first_non_none_perm(self, name, ctx):
        return first_non_none(self._perm_iterator(name, ctx))

    @staticmethod
    def _perm_result_embed(ctx, level, mode, name, *args, thing):
        return (discord.Embed(colour=mode.colour, timestamp=ctx.message.created_at)
               .set_author(name=f'{thing} {mode.action}!', icon_url=_emoji_url(mode.emoji))
               .add_field(name=thing, value=name)
               .add_field(name=level.name.title(), value=str_join(', ', map(attrgetter('original'), args)), inline=False)
               )

    async def _perm_set(self, ctx, level, mode, name, *args, thing):
        self.set_perms(level, mode, name, *args)
        await ctx.send(embed=self._perm_result_embed(ctx, level, mode, name, *args, thing=thing))

    def set_perms(self, level, mode, name, *args):
        level_perms = self.permissions[name][str(level)]
        # members require a special key - a tuple of (server_id, member_id)
        fmt = '({0.original.guild.id}, {0.id})' if level == PermLevel.user else '{0.id}'
        level_perms.update(zip(map(fmt.format, args), itertools.repeat(mode.value)))

    # We could make this function take a union of Commands and cogs.
    # This would greatly reduce the amount of repetition.
    # However, because of the case insensitivity of the cog converter,
    # commands will inevitably clash with cogs of the same name, creating confusion.
    # This is also why the default help command only takes commands, as opposed to either a command or cog.
    @commands.command(name='permsetcommand', aliases=['psc'])
    @checks.is_admin()
    @commands.guild_only()
    @make_doc('command', extra=('This will affect aliases as well. If a command group is blocked, '
                                'its subcommands are blocked as well.'))
    async def perm_set_command(self, ctx, level: level_getter, mode: PermAction,
                               command: BotCommand(recursive=True), *args):
        self._assert_is_valid_cog(command)
        ids = await level.parse_args(ctx, *args)
        await self._perm_set(ctx, level, mode, command.qualified_name, *ids, thing='Command')

    @commands.command(name='permsetmodule', aliases=['psm'])
    @checks.is_admin()
    @commands.guild_only()
    @make_doc('module')
    async def perm_set_module(self, ctx, level: level_getter, mode: PermAction,
                              module: BotCogConverter, *args):
        self._assert_is_valid_cog(module)
        ids = await level.parse_args(ctx, *args)
        await self._perm_set(ctx, level, mode, type(module).__name__, *ids, thing='Module')

    async def modify_command(self, ctx, command, bool_):
        command.enabled = bool_
        await ctx.send(f"**{command}** is now {DEins[bool_::2]}abled!")

    @commands.command()
    @commands.is_owner()
    async def disable(self, ctx, *, command: BotCommand(recursive=True)):
        """Globally disables a command."""
        await self.modify_command(ctx, command, False)

    @commands.command()
    @commands.is_owner()
    async def enable(self, ctx, *, command: BotCommand(recursive=True)):
        """Globally enables a command."""
        await self.modify_command(ctx, command, True)

    async def _modify_blacklist(self, ctx, user, list_attr, *, contains_op, block_type):
        blacklist = self.blacklisted_users
        if contains_op(blacklist, user.id):
            raise errors.InvalidUserArgument(f'**{user}** has already been {block_type.name}ed, I think...')

        getattr(blacklist, list_attr)(user.id)
        await ctx.send(embed=block_type.embed(user))

    @commands.command(aliases=['bl'])
    @commands.is_owner()
    async def blacklist(self, ctx, *, user: discord.User):
        """Blacklists a user. This prevents them from ever using the bot, regardless of other permissions."""
        await self._modify_blacklist(ctx, user, 'append', contains_op=contains, 
                                     block_type=BlockType.blacklist)

    @commands.command(aliases=['wl'])
    @commands.is_owner()
    async def whitelist(self, ctx, *, user: discord.User):
        """Whitelists a user, removing the from the blacklist.

        This doesn't make them immune to any other checks.
        """
        await self._modify_blacklist(ctx, user, 'remove', contains_op=lambda a, b: not b in a, 
                                     block_type=BlockType.whitelist)
def setup(bot):
    bot.add_cog(Permissions())
