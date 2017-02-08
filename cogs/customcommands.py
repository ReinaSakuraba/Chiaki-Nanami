import discord
import itertools
import random

from collections import defaultdict
from discord.ext import commands
from operator import itemgetter

from .utils import checks
from .utils.database import Database
from .utils.errors import ResultsNotFound, private_message_only
from .utils.paginator import DelimPaginator

_cc_default = {"triggers": {}, "reactions": {}, "current_pow": 6}

def _smart_truncate(content, length=100, suffix='...'):
    if len(content) <= length:
        return content
    else:
        return ' '.join(content[:length+1].split(' ')[0:-1]) + suffix

class CustomReactions:
    def __init__(self, bot):
        self.bot = bot
        self.db = Database.from_json("customcommands.json")

    def _get_all_trigger_ids(self, server):
        if server not in self.db:
            return []
        return list(itertools.chain.from_iterable(self.db[server]["triggers"].values()))

    def _random_trigger(self, server):
        db = self.db[server]
        ids = self._get_all_trigger_ids(server)
        available_ids = set(range(1, 10 ** db["current_pow"])) - set(ids)
        if not available_ids:
            db_pow = db["current_pow"]
            available_ids |= set(range(10 ** db_pow, 10 ** (db_pow + 1)))
            db["current_pow"] = db_pow + 1
        return random.sample(available_ids, 1)[0]

    @commands.group(aliases=["customreact", "cc", "cr"])
    async def customcommand(self):
        """Namespace for the custom commands"""
        pass

    @customcommand.command(pass_context=True)
    @checks.is_admin()
    async def add(self, ctx, trigger, *, reaction : str):
        """Adds a new custom reaction/trigger (depending on what bot you use)

        The trigger must be put in quotes if you want spaces in your trigger.
        """
        server = ctx.message.server
        if server not in self.db:
            self.db[server] = _cc_default.copy()

        trigger_id = self._random_trigger(server)

        triggers = self.db[server]["triggers"]
        triggers.setdefault(trigger.lower(), []).append(trigger_id)

        self.db[server]["reactions"][str(trigger_id)] = reaction
        await self.bot.say("Custom command added")

    def _cc_iterator(self, server):
        database = self.db[server]
        for trigger, ids in sorted(database['triggers'].items(), key=itemgetter(0)):
            for id_ in sorted(ids):
                reaction = database['reactions'][str(id_)]
                truncated_reaction = _smart_truncate(reaction, 80)
                yield f"`{id_:<6}`: {trigger} => {truncated_reaction}"

    @customcommand.command(pass_context=True)
    async def list(self, ctx, page=0):
        server = ctx.message.server or "global"
        paginator = DelimPaginator.from_iterable(self._cc_iterator(server), prefix='', suffix='')
        try:
            msg = paginator[page]
        except IndexError:
            msg = f"Page {page} doesn't exist, or is out of bounds, I think."
        await self.bot.say(msg)

    @customcommand.command(pass_context=True, aliases=['delete', 'del', 'rem',])
    @checks.is_admin()
    async def remove(self, ctx, *, ccid: int):
        """Removes a new custom reaction/trigger (depending on what bot you use)

        Keep in mind the ccid is an integer.
        """
        storage = self.db.get(ctx.message.server, None)
        if storage is None:
            raise ResultsNotFound("There are no commands for this server")
        try:
            storage["reactions"].pop(str(ccid))
        except KeyError:
            await self.bot.say("{} was never a custom command".format(ccid))
        else:
            triggers = storage["triggers"]
            key = discord.utils.find((lambda k: ccid in triggers[k]), triggers)
            triggers[key].remove(ccid)
            if not triggers[key]:
                triggers.pop(key)
            await self.bot.say(f"#{ccid} successfully removed.")

    @customcommand.command(pass_context=True)
    @checks.is_admin()
    async def edit(self, ctx, ccid: int, *, new_react: str):
        server = ctx.message.server
        storage = self.db.get(server, None)
        if storage is None:
            raise ResultsNotFound("There are no commands for this server")
        reactions = storage["reactions"]
        ccid = str(ccid)
        if ccid not in reactions:
            raise ResultsNotFound("Command {} doesn't ~~edit~~ exits".format(ccid))

        reactions[ccid] = new_react
        await self.bot.say("{} command edited".format(ccid))

    @customcommand.command(pass_context=True, hidden=True)
    @checks.is_owner()
    @private_message_only()
    async def addg(self, ctx, trigger, *, msg : str):
        self.db["global"][trigger] = msg

    @customcommand.command(pass_context=True, hidden=True)
    @checks.is_owner()
    @private_message_only()
    async def remg(self, ctx, trigger):
        try:
            self.db["global"].pop(ccid.lower())
        except KeyError:
            raise ResultsNotFound(f"{ccid} was never a custom command")

    async def on_message(self, msg):
        storage = self.db.get(msg.server) or self.db.get("global")
        if storage is None:
            return

        triggers = storage["triggers"].get(msg.content.lower())
        if triggers is None:
            return

        trigger_id = str(random.choice(triggers))
        reaction = storage["reactions"].get(trigger_id)
        if reaction is not None:
            await self.bot.send_message(msg.channel, reaction)

def setup(bot):
    bot.add_cog(CustomReactions(bot))
