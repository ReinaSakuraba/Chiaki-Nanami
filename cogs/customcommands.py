import discord
import random

from collections import defaultdict
from discord.ext import commands
from itertools import chain, islice, starmap
from operator import itemgetter

from .utils import checks, errors
from .utils.context_managers import temp_attr
from .utils.database import Database
from .utils.paginator import DelimPaginator, iterable_limit_say

_cc_default = {"triggers": {}, "reactions": {}, "current_pow": 6}

def _smart_truncate(content, length=100, suffix='...'):
    if len(content) <= length:
        return content
    else:
        return ' '.join(content[:length+1].split(' ')[0:-1]) + suffix

def firstn(iterable, n, *, reverse=False):
    """Returns an iterator containing the first element, then the first two elements,
    all the way up to the first n elements.

    If reverse is True, it yields the first n elements, then the first n-1 elements,
    all the way up to the first element.
    """
    range_iterator = range(1, n + 1)
    if reverse:
        range_iterator = reversed(range_iterator)

    return (tuple(islice(iter(iterable), i)) for i in range_iterator)

MAX_ALIAS_WORDS = 5
class CustomReactions:
    def __init__(self, bot):
        self.bot = bot
        self.custom_reactions = Database("customcommands.json")
        self.aliases = Database("commandaliases.json", default_factory=dict)

    def _get_all_trigger_ids(self, server):
        if server not in self.custom_reactions:
            return set()
        return set(chain.from_iterable(self.custom_reactions[server]["triggers"].values()))

    def _random_trigger(self, server):
        db = self.custom_reactions[server]
        ids = self._get_all_trigger_ids(server)
        available_ids = set(range(1, 10 ** db["current_pow"])) - ids
        if not available_ids:
            db_pow = db["current_pow"]
            available_ids |= set(range(10 ** db_pow, 10 ** (db_pow + 1)))
            db["current_pow"] = db_pow + 1
        return random.sample(available_ids, 1)[0]

    @commands.group(aliases=["customreact", "cc", "cr"])
    async def customcommand(self):
        """Namespace for the custom commands"""
        pass

    @customcommand.command()
    @checks.is_admin()
    async def add(self, ctx, trigger, *, reaction : str):
        """Adds a new custom reaction/trigger (depending on what bot you use)

        The trigger must be put in quotes if you want spaces in your trigger.
        """
        server = ctx.guild
        if server not in self.custom_reactions:
            self.custom_reactions[server] = _cc_default.copy()

        trigger_id = str(self._random_trigger(server))

        triggers = self.custom_reactions[server]["triggers"]
        triggers.setdefault(trigger.lower(), []).append(trigger_id)

        self.custom_reactions[server]["reactions"][trigger_id] = reaction
        await ctx.send("Custom command added")

    def _cc_iterator(self, server):
        database = self.custom_reactions[server]
        for trigger, ids in sorted(database['triggers'].items(), key=itemgetter(0)):
            for id_ in sorted(ids):
                reaction = database['reactions'][id_]
                truncated_reaction = _smart_truncate(reaction, 80)
                yield f"`{id_:<6}`: {trigger} => {truncated_reaction}"

    @customcommand.command()
    async def list(self, ctx, page=0):
        server = ctx.guild or "global"
        paginator = DelimPaginator.from_iterable(self._cc_iterator(server), prefix='', suffix='')
        try:
            msg = paginator[page]
        except IndexError:
            msg = f"Page {page} doesn't exist, or is out of bounds, I think."
        await ctx.send(msg)

    @customcommand.command(aliases=['delete', 'del', 'rem',])
    @checks.is_admin()
    async def remove(self, ctx, *, ccid):
        """Removes a new custom reaction/trigger (depending on what bot you use)

        Keep in mind the ccid is an integer.
        """
        storage = self.custom_reactions.get(ctx.guild, None)
        if storage is None:
            raise errors.ResultsNotFound("There are no commands for this server")
        try:
            storage["reactions"].pop(ccid)
        except KeyError:
            await ctx.send("{} was never a custom command".format(ccid))
        else:
            triggers = storage["triggers"]
            key = discord.utils.find((lambda k: ccid in triggers[k]), triggers)
            triggers[key].remove(ccid)
            if not triggers[key]:
                triggers.pop(key)
            await ctx.send(f"#{ccid} successfully removed.")

    @customcommand.command()
    @checks.is_admin()
    async def edit(self, ctx, ccid, *, new_react: str):
        server = ctx.guild
        storage = self.custom_reactions.get(server, None)
        if storage is None:
            raise errors.ResultsNotFound("There are no commands for this server")

        reactions = storage["reactions"]
        if ccid not in reactions:
            raise errors.ResultsNotFound("Command {} doesn't ~~edit~~ exits".format(ccid))

        reactions[ccid] = new_react
        await ctx.send("{} command edited".format(ccid))

    @customcommand.command(hidden=True)
    @checks.is_owner()
    @errors.private_message_only()
    async def addg(self, ctx, trigger, *, msg : str):
        self.custom_reactions["global"][trigger] = msg

    @customcommand.command(hidden=True)
    @checks.is_owner()
    @errors.private_message_only()
    async def remg(self, ctx, trigger):
        try:
            self.custom_reactions["global"].pop(ccid.lower())
        except KeyError:
            raise ResultsNotFound(f"{ccid} was never a custom command")

    @commands.group()
    async def alias(self, ctx):
        pass

    @alias.command(name='add')
    async def add_alias(self, ctx, alias, *, real):
        if len(alias.split()) > MAX_ALIAS_WORDS:
            raise errors.InvalidUserArgument(f"Your alias is too long to be practical. "
                                              "The limit is {MAX_ALIAS_WORDS}.")
        if any(alias in cmd.all_recursive_names for cmd in self.bot.walk_commands()):
            raise errors.InvalidUserArgument(f'\"{alias}\" is already an existing command')

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
        prefix = self.bot.prefix_function(message)
        if not any(map(content.startswith, prefix)):
            return

        content_no_prefix = content[len(prefix):]
        words = content_no_prefix.split()
        for alias in filter(content_no_prefix.startswith, map(' '.join, firstn(words, MAX_ALIAS_WORDS, reverse=True))):
            real = self.aliases[message.guild].get(alias)
            if real:
                with temp_attr(message, 'content', message.content.replace(alias, real, 1)):
                    await self.bot.process_commands(message)
                break

    async def check_custom_command(self, message):
        storage = self.custom_reactions.get(message.guild) or self.custom_reactions.get("global")
        if storage is None:
            return

        triggers = storage["triggers"].get(message.content.lower())
        if triggers is None:
            return

        trigger_id = str(random.choice(triggers))
        reaction = storage["reactions"].get(trigger_id)
        if reaction is not None:
            await msg.channel.send(reaction)

    async def on_message(self, message):
        await self.check_custom_command(message)
        await self.check_alias(message)

def setup(bot):
    bot.add_cog(CustomReactions(bot), "CustomCommands")
