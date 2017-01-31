import discord
import random

from discord.ext import commands

from .utils import checks, converter
from .utils.database import Database
from .utils.misc import nice_time, parse_int

QUOTE_FILE_NAME = "quotes.json"

class Quotes:
    def __init__(self, bot):
        self.bot = bot
        self.quotes_db = Database.from_json(QUOTE_FILE_NAME, default_factory=list)

    def _quote_num(self, ctx, num):
        try:
            return self.quotes_db[ctx.message.server][num]
        except IndexError:
            return None

    def _quote_user(self, ctx, user):
        quotes_by_user = [quote for quote in self.quotes_db[ctx.message.server]
                          if quote["user"] == user.id]
        return random.choice(quotes_by_user) if quotes_by_user else None

    async def _quote_embed(self, ctx, **quote_kwargs):
        user_id = quote_kwargs["user"]
        user = await self.bot.get_user_info(user_id)
        username = f"{user.name}#{user.discriminator }"
        colour = commands.ColourConverter(ctx, quote_kwargs["colour"]).convert()
        time = quote_kwargs["time"]
        quote = quote_kwargs["quote"]
        avatar_url = user.avatar_url or user.default_avatar_url
        footer = f"{time} | ID: {user_id}"
        index = f'#{quote_kwargs["index"]}'
        author_text = f"{index} | {username}"

        quote_embed = (discord.Embed(colour=colour)
                       .set_author(name=author_text, icon_url=avatar_url)
                       .add_field(name=f'"{quote}"', value=quote_kwargs["channel"])
                       .set_footer(text=footer)
                       )
        return quote_embed

    async def _quote_dict(self, ctx, number_or_user=None):
        if number_or_user == "private":
            try:
                return random.choice(self.quotes_db["private"])
            except IndexError:
                await self.bot.say(f"There are no quotes made in DMs... yet.")
                return None
        if number_or_user is not None:
            result = parse_int(number_or_user)
            if result is not None:
                quote = self._quote_num(ctx, result)
                if quote is None:
                    await self.bot.say(f"{result} is not a valid index, I think.")
                    return None
                return quote
            else:
                try:
                    result = converter.ApproximateUser(ctx, number_or_user).convert()
                except commands.BadArgument:
                    await self.bot.say(f"{number_or_user} is neither a number nor user, I think.")
                    return None
                else:
                    quote = self._quote_user(ctx, result)
                    if quote is None:
                        await self.bot.say(f"Couldn't find quote by {result} in this server.")
                        return None
                    return quote
        else:
            try:
                return random.choice(self.quotes_db[ctx.message.server])
            except IndexError:
                await self.bot.say(f"This server has no quotes.")
                return None

    @commands.command(pass_context=True)
    async def quote(self, ctx, *, number_or_user: str=None):
        """Fetches a quote.

        If a number is given, it will attempt to find the quote with that number.
        If a user is given, it will attempt to give a random quote from the user.
        Otherwise it will just give a random quote.
        """
        quote = await self._quote_dict(ctx, number_or_user)
        if quote is None:
            return
        quote_embed = await self._quote_embed(ctx, **quote)
        await self.bot.say(embed=quote_embed)

    @commands.command(pass_context=True)
    async def addquote(self, ctx, quote: str, *,
                       author: converter.ApproximateUser=None):
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
                       "user": author.id,
                       "colour": str(getattr(author, "colour", discord.Colour.default())),
                       "time": nice_time(message.timestamp),
                       "channel": f"#{message.channel}",
                       "quote": quote,
                       }

        if author.nick is not None:
            quote_stats["name"] = author.nick
        quotes.append(quote_stats)
        await self.bot.say(f'Successfully added quote #{len(quotes)}: **"{quote}"**')

    @commands.command(pass_context=True)
    async def removequote(self, ctx, index: int):
        """Removes a quote

        """
        server = ctx.message.server or "private"
        try:
            del self.quotes_db[ctx.message.server][index]
        except IndexError:
            await self.bot.say(f"Couldn't remove quote #{index} as it's out of range, probably")
        else:
            await self.bot.say(f"Successfully removed quote #{index}")

    @commands.command(pass_context=True)
    @checks.admin_or_permissions()
    async def clearquote(self, ctx, index: int):
        """Clears all the quotes

        Only use this if there are too many troll or garbage quotes
        """
        server = ctx.message.server or "private"
        self.quotes_db[server].clear()
        await self.bot.say(f"Successfully cleared all quotes from this server.")

def setup(bot):
    bot.add_cog(Quotes(bot))