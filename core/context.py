from discord.ext import commands


class Context(commands.Context):
    @property
    def clean_prefix(self):
        """The cleaned up invoke prefix. (mentions are @name instead of <@id>)."""
        user = self.bot.user
        return self.prefix.replace(user.mention, f'@{user.name}')

    @property
    def db(self):
        """The bot's database connection interface, if applicable."""
        return getattr(self.bot, 'db', None)
