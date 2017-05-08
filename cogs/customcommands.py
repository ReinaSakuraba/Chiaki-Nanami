import discord
import random

from collections import ChainMap
from discord.ext import commands
from itertools import chain, starmap

from .utils import checks, errors
from .utils.context_managers import temp_attr
from .utils.database import Database
from .utils.paginator import DelimPaginator, iterable_limit_say

def word_count(s):
    return len(s.split()), len(s)

# Only the owner can add commands in the global scope.
def global_cc_check():
    async def predicate(ctx):
        if ctx.guild:
            return True
        return await checks.is_owner_predicate(ctx)
    return commands.check(predicate)

MAX_ALIAS_WORDS = 20
class CustomCommands:
    __aliases__ = "CustomReactions",

    def __init__(self, bot):
        self.bot = bot
        self.custom_reactions = Database("customcommands.json", default_factory=dict)
        self.custom_reaction_pows = Database('custom-command-current-pow.json', default_factory=int)
        self.aliases = Database('commandaliases.json', default_factory=dict)

    def _all_reactions(self, server):
        return ChainMap(*self.custom_reactions[server].values())

    def _get_used_ids(self, server):
        return set(self._all_reactions(server).keys())

    def _random_trigger(self, server):
        ids = self._get_used_ids(server)
        current_pow = self.custom_reaction_pows[server]
        available_ids = set(map(str, range(1, 10 ** current_pow))) - ids
        if not available_ids:
            available_ids = set(map(str, range(10 ** current_pow, 10 ** (current_pow + 1))))
            self.custom_reaction_pows[server] += 1
        return random.sample(available_ids, 1)[0]

    def _cc_iterator(self, server):
        # Someone come up with some itertools magic plz...
        for trigger, reactions in self.custom_reactions[server].items():
            for id_ in reactions:
                yield f'`{id_}` => {trigger}'

    @commands.group(name='customcommand', aliases=["customreact", "cc", "cr"])
    async def custom_command(self, ctx):
        """Namespace for the custom commands"""
        pass

    @custom_command.command(name='add')
    @global_cc_check()
    async def add_custom_command(self, ctx, trigger, reaction):
        server = ctx.guild or 'global'
        server_reactions = self.custom_reactions[server]
        new_trigger_id = self._random_trigger(server)

        server_reactions.setdefault(trigger.lower(), {})[new_trigger_id] = reaction
        await ctx.send(f'Custom command added: "**{trigger}** = **{reaction}**"')

    @custom_command.command(name='remove')
    @global_cc_check()
    async def remove_custom_command(self, ctx, trigger_id):
        """Removes a custom trigger by id."""
        server_reactions = self._all_reactions(ctx.guild or 'global')
        if any(reaction.pop(trigger_id, None) for reaction in server_reactions):
            await ctx.send(f'Successfully removed **"{trigger_id}"**.')
        else:
            await ctx.send(f'{trigger_id} was never a trigger, I think.')

    @custom_command.command(name='delete', aliases=['del'])
    @checks.mod_or_permissions(manage_server=True)
    @global_cc_check()
    async def delete_custom_command(self, ctx, trigger):
        """Deletes an entire trigger from the server."""
        if self.custom_reactions[ctx.guild or 'global'].pop(trigger.lower(), None):
            await ctx.send(f'Successfully removed *all* custom commands relating to **"{trigger}"**.')
        else:
            await ctx.send(f'"{trigger}" was never a custom command.')

    @custom_command.command(name='list')
    async def list_custom_commands(self, ctx, page: int=0):
        """Lists the custom commands for the server."""
        server = ctx.guild or 'global'
        paginator = DelimPaginator.from_iterable(self._cc_iterator(server), prefix='', suffix='')
        try:
            msg = paginator[page]
        except IndexError:
            msg = (f"Page {page} doesn't exist, or is out of bounds, I think." if page else
                    "This server doesn't have any custom commands... I think.")
        await ctx.send(msg)

    def get_prefix(self, message):
        prefix = self.bot.prefix_function(message)
        return discord.utils.find(message.content.startswith, prefix)

    @staticmethod
    def is_part_of_existing_command(ctx, arg):
        return ctx.bot.get_command(arg) is not None

    @commands.group()
    async def alias(self, ctx):
        pass

    @alias.command(name='add')
    async def add_alias(self, ctx, alias, *, real):
        if len(alias.split()) > MAX_ALIAS_WORDS:
            raise errors.InvalidUserArgument(f"Your alias is too long to be practical. "
                                              "The limit is {MAX_ALIAS_WORDS}.")
        if self.is_part_of_existing_command(ctx, alias):
            raise errors.InvalidUserArgument(f'"{alias}" is already an existing command...')

        self.aliases[ctx.guild][alias] = real
        await ctx.send(f"Successfully added a new alias: **{alias} => {real}**!")

    @alias.command(name='remove')
    async def delete_alias(self, ctx, *, alias):
        if self.aliases[ctx.guild].pop(alias, None):
            await ctx.send(f'Successfully removed the alias: **{alias}**!')
        else:
            await ctx.send(f'"{alias}" was never an alias for a command')

    @alias.command(name='show')
    async def show_alias(self, ctx, *, alias):
        real = self.aliases[ctx.guild].get(alias)
        if real:
            await ctx.send(f'Alias "{alias}" is actually **{real}**, I think')
        else:
            await ctx.send(f'"{alias}" is not an alias, I think.')

    @alias.command(name='list')
    async def list_aliases(self, ctx):
        await iterable_limit_say(starmap('{0} => {1}'.format, self.aliases[ctx.guild].items()), ctx=ctx)

    async def check_alias(self, message):
        if isinstance(message.channel, (discord.DMChannel, discord.GroupChannel)):
            return

        content = message.content
        prefix = self.get_prefix(message)
        if prefix is None:
            return

        aliases = self.aliases[message.guild]
        content_no_prefix = content[len(prefix):]
        possible_aliases = filter(content_no_prefix.startswith, aliases)
        try:
            alias = max(possible_aliases, key=word_count)
        except ValueError:
            return
        else:
            with temp_attr(message, 'content', content.replace(alias, aliases[alias], 1)):
                await self.bot.process_commands(message)

    async def check_custom_command(self, message):
        storage = self.custom_reactions.get(message.guild) or self.custom_reactions.get('global')
        if not storage:
            return

        reactions = storage.get(message.content.lower())
        if reactions is None:
            return

        await message.channel.send(random.choice(list(reactions.values())))

    async def on_message(self, message):
        await self.check_custom_command(message)
        await self.check_alias(message)

def setup(bot):
    bot.add_cog(CustomCommands(bot))
