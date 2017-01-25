import discord
import itertools
import random

from collections import defaultdict
from discord.ext import commands
from operator import itemgetter

from .utils import checks
from .utils.database import Database
from .utils.paginator import DelimPaginator

CC_FILE_NAME = "customcommands.json"
def _cc_default():
    return {"triggers": {}, "reactions": {}, "current_pow": 6}


def _smart_truncate(content, length=100, suffix='...'):
    if len(content) <= length:
        return content
    else:
        return ' '.join(content[:length+1].split(' ')[0:-1]) + suffix

class CustomReactions:
    def __init__(self, bot):
        self.bot = bot
        self.db = Database.from_json(CC_FILE_NAME)

    def _get_all_trigger_ids(self, server):
        if server not in self.db:
            return []
        return list(itertools.chain.from_iterable(self.db[server]["triggers"].values()))

    def _random_trigger(self, server):
        db = self.db[server]
        ids = self._get_all_trigger_ids(server)
        available_ids = set(range(1, 10 ** db["current_pow"])) - set(ids)
        if not available_ids:
            db["current_pow"] += 1
            available_ids = set(range(1, 10 ** db["current_pow"])) - set(ids)
        return random.sample(available_ids, 1)[0]

    @commands.group(aliases=["customcomm", "cc", "cr", "custreact"])
    async def customcommand(self):
        """Namespace for the custom commands"""
        pass

    @customcommand.command(pass_context=True)
    @checks.admin_or_permissions()
    async def add(self, ctx, trigger, *, reaction : str):
        """Adds a new custom reaction/trigger (depending on what bot you use)

        The trigger must be put in quotes if you want spaces in your trigger.
        """
        server = ctx.message.server
        if server not in self.db:
            self.db[server] = _cc_default()

        triggers = self.db[server]["triggers"]
        lower_trigger = trigger.lower()
        if lower_trigger not in triggers:
            triggers[lower_trigger] = []

        trigger_id = self._random_trigger(server)
        triggers[trigger].append(trigger_id)
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
    @checks.admin_or_permissions()
    async def remove(self, ctx, *, ccid: int):
        """Removes a new custom reaction/trigger (depending on what bot you use)

        Keep in mind the ccid is an integer.
        """
        storage = self.db.get(ctx.message.server, None)
        if storage is None:
            await self.bot.say("There are no commands for this server")
            return
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
            await self.bot.say("{} command removed".format(ccid))

    @customcommand.command(pass_context=True)
    @checks.admin_or_permissions()
    async def edit(self, ctx, ccid: int, *, new_react: str):
        ccid = ccid.lower()
        server = ctx.message.server
        storage = self.db.get(server, None)
        if storage is None:
            await self.bot.say("There are no commands for this server")
            return
        reactions = storage["reactions"]
        if ccid not in reactions:
            return await self.bot.say("Command {} doesn't ~~edit~~ exits".format(ccid))

        reactions[ccid] = new_react
        await self.bot.say("{} command edited".format(ccid))

    @customcommand.command(pass_context=True, hidden=True)
    @checks.is_owner()
    async def addg(self, ctx, trigger, *, msg : str):
        if not ctx.message.channel.is_private:
            return
        self.db["global"][trigger] = msg

    @customcommand.command(pass_context=True, hidden=True)
    @checks.is_owner()
    async def remg(self, ctx, trigger):
        if not ctx.message.channel.is_private:
            return
        try:
            self.db["global"].pop(ccid.lower())
        except KeyError:
            return await self.bot.say("{} was never a custom command".format(ccid))

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
