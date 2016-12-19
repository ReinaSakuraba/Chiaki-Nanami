import cleverbot

class Cleverbot:
    def __init__(self, bot):
        self.bot = bot
        self.cb_session = cleverbot.Cleverbot()

    async def on_message(self, message):
        bot_user = self.bot.user
        if message.author == bot_user:
            return
        content = message.content
        author = message.author
        bot_member = message.server.get_member(bot_user.id)
        csw = content.startswith
        if not csw(bot_member.mention) or csw(bot_user.mention):
            return
        response = self.cb_session.ask(message.content)
        fmt = "{0.mention} {1}".format(author, response)
        await self.bot.send_message(message.channel, fmt)

def setup(bot):
    cb = Cleverbot(bot)
    bot.add_listener(cb.on_message, "on_message")
