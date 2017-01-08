from discord.ext import commands

class ApproximateUser(commands.MemberConverter):
    async def convert(self): 
        arg = self.argument
        bot = self.ctx.bot
        channel = self.ctx.message.channel
        server = self.ctx.message.server
        arg_lower = arg.lower()
        
        if server:
        
            def pred(elem):
                return (elem.nick and arg_lower in elem.nick.lower()) or arg_lower in elem.name.lower()
                
            member_filter = list(filter(pred, server.members))
            filter_length = len(member_filter)
            if filter_length > 1:
                await bot.send_message(channel, (f"(I found {filter_length} occurences of '{arg}'. "
                                                  "I'll take the first result, probably.)"))
            if member_filter:   
                return member_filter[0]
        return super().convert()