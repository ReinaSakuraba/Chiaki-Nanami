# Once again json sucks
# This can't be used because of weird namedtuple serialization issues
# So a dict is required
#from collections import namedtuple
from discord.ext import commands
from .utils import checks
from .utils.database import Database, DB_FILE_PATH

CC_FILE_NAME = "customcommands.json"
class CustomReactions:
    def __init__(self, bot):
        self.bot = bot
        self.db = Database.from_json(DB_FILE_PATH + CC_FILE_NAME, factory_not_top_tier=dict)

    @commands.group(aliases=["customcomm", "cc", "cr", "custreact"])
    async def customcommand(self):
        """Namespace for the custom commands"""
        pass

    @customcommand.command(pass_context=True)
    async def add(self, ctx, trigger, *, reaction : str):
        """Adds a new custom reaction/trigger (depending on what bot you use)
        """
        server = ctx.message.server
        print(server)
        if trigger in self.db[server]:
            # TODO: Add multiple custom commands for the same trigger
            # (similar to Nadeko)
            return await self.bot.say("{} already has a reaction".format(trigger))
        self.db[server][trigger.lower()] = reaction
        await self.bot.say("Custom command added")
        
                
    @customcommand.command(pass_context=True)
    async def list(self, ctx, page=0):
        pass
    
    @customcommand.command(pass_context=True, aliases=['delete', 'del', 'rem',])
    async def remove(self, ctx, *, ccid : str):
        if self.db[ctx.message.server]:
            return await self.bot.say("There are no commands for this server")
        try:
            storage.pop(ccid.lower())
        except KeyError:
            await self.bot.say("{} was never a custom command".format(ccid))
        else:
            await self.bot.say("{} command removed".format(ccid))

    @customcommand.command(pass_context=True)
    async def edit(self, ctx, ccid, *, new_react : str):
        storage = self.db.get_storage(ctx.message.server)
        if storage is None:
            return await self.bot.say("There are no commands for this server")
        if ccid not in storage:
            return await self.bot.say("Command {} doesn't ~~edit~~ exits".format(ccid))
        self.db[server][ccid.lower()] = new_react
        await self.bot.say("{} command edited".format(ccid))

    @customcommand.command(pass_context=True)
    @checks.is_owner()
    async def addg(self, ctx, trigger, *, msg : str):
        if not ctx.message.channel.is_private:
            return
        self.db["global"][trigger] = msg

    @customcommand.command(pass_context=True)
    @checks.is_owner()
    async def remg(self, ctx, trigger):
        if not ctx.message.channel.is_private:
            return
        try:
            self.db["global"].pop(ccid.lower())
        except KeyError:
            return await self.bot.say("{} was never a custom command".format(ccid))
            
    async def on_message(self, msg):
        storage = self.db[msg.server]
        if not storage:
            return
        reaction = storage.get(msg.content.lower())
        if reaction is not None:
            print("passed")
            await self.bot.send_message(msg.channel, reaction)
        
def setup(bot):
    cc = CustomReactions(bot)
    bot.add_cog(cc)
