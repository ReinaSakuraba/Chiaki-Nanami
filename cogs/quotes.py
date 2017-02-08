import discord
import random

from discord.ext import commands

from .utils import checks, converter
from .utils.compat import user_color
from .utils.database import Database
from .utils.misc import nice_time, parse_int

QUOTE_FILE_NAME = "quotes.json"

def _random_quote(quotes, msg=""):
    if quotes:
        return random.choice(quotes)
    raise commands.BadArgument(msg)

class Quotes:
    def __init__(self, bot):
        self.bot = bot
        self.quotes_db = Database.from_json(QUOTE_FILE_NAME, default_factory=list)

    def _quote_num(self, ctx, num):
        # Allow for python's nice negative indexing
        num -= num > 0
        try:
            return self.quotes_db[ctx.message.server][num]
        except IndexError:
            raise commands.BadArgument(f"{num} is not a valid index, I think.")

    def _quote_user(self, ctx, user):
        quotes_by_user = [quote for quote in self.quotes_db[ctx.message.server] if quote["user"] == user.id]
        return _random_quote(quotes_by_user, f"Couldn't find quote by {user} in this server.")

    async def _quote_embed(self, ctx, quote_dict):
        user_id = quote_dict["user"]
        # could use await self.bot.get_user_info() but that would rate-limit the API
        user = discord.utils.get(bot.get_all_members(), id=user_id)
        colour = await user_color(user)
        time = quote_dict["time"]
        quote = quote_dict["quote"]
        avatar_url = user.avatar_url or user.default_avatar_url
        footer = f"{time} | ID: {user_id}"
        author_text = f"#{quote_dict['index']} | {user}"

        return (discord.Embed(colour=colour)
               .set_author(name=author_text, icon_url=avatar_url)
               .add_field(name=f'"{quote}"', value=quote_kwargs["channel"])
               .set_footer(text=footer)
               )

    async def _quote_dict(self, ctx, number_or_user=None):
        if number_or_user == "private":
            return _random_quote(self.quotes_db["private"], "There are no quotes made in DMs... yet.")
        elif number_or_user is None:
            return _random_quote(self.quotes_db[ctx.message.server], "This server has no quotes.")
        else:
            result = parse_int(number_or_user)
            if result is not None:
                return self._quote_num(ctx, result)
            result = await converter.ApproximateUser(ctx, number_or_user).convert()
            return self._quote_user(ctx, result)

    @commands.command(pass_context=True)
    async def quote(self, ctx, *, number_or_user=None):
        """Fetches a quote.

        If number_or_user is not specified, it will give a random quote.
        If a number is given, it will attempt to find the quote with that number.
        Otherwise it will search for a user.
        """
        quote = await self._quote_dict(ctx, number_or_user)
        quote_embed = await self._quote_embed(ctx, quote)
        await self.bot.say(embed=quote_embed)

    @commands.command(pass_context=True)
    async def addquote(self, ctx, quote: str, *, author: converter.ApproximateUser=None):
        """Adds a quote to the list of the server's quotes.

        Your quote must be in quotation marks.
        If an author is not specified, it defaults to the author of the message.
        Example: ->addquote "This is not a quote" bob#4200
        """
        message = ctx.message
        if author is None:
            author = message.author
        server = message.server or "private"
        quotes = self.quotes_db[server]
        quote_stats = {
                       "index": len(quotes) + 1,
                       "name": author.display_name,
                       "user": author.id,
                       "time": nice_time(message.timestamp),
                       "channel": f"#{message.channel}",
                       "quote": quote,
                       }

        quotes.append(quote_stats)
        await self.bot.say(f'Successfully added quote #{len(quotes)}: **"{quote}"**')

    @commands.command(pass_context=True, no_pm=True)
    async def removequote(self, ctx, index: int):
        """Removes a quote"""
        try:
            del self.quotes_db[ctx.message.server][index]
        except IndexError:
            await self.bot.say(f"Couldn't remove quote #{index} as it's out of range, probably")
        else:
            await self.bot.say(f"Successfully removed quote #{index}")

    @commands.command(pass_context=True, no_pm=True)
    @checks.is_admin()
    async def clearquote(self, ctx):
        """Clears all the quotes

        Only use this if there are too many troll or garbage quotes
        """
        self.quotes_db[ctx.message.server].clear()
        await self.bot.say(f"Successfully cleared all quotes from this server.")

    @commands.command(hidden=True, aliases=['clrpq', 'clrdmpq'])
    @checks.is_owner()
    async def clearprivatequotes(self):
        """Clears all quotes from DMs

        Only use this if there are too many troll or garbage quotes
        """
        self.quotes_db["private"].clear()
        await self.bot.say(f"Successfully cleared all quotes from Private Messages.")

def setup(bot):
    bot.add_cog(Quotes(bot))
