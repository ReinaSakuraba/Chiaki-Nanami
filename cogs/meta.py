import discord
from discord.ext import commands

class Meta:
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(pass_context=True, aliases=['uinfo'])
    async def userinfo(self, ctx, user : discord.Member=None):
        """Gets some useful info because why not"""
        if user is None:
            user = ctx.message.author
        print(type(user))
        fmt = ("    Name: {0.name}\n"
               "      ID: {0.id}\n"
               " Hashtag: {0.discriminator}\n"
               "Nickname: {0.display_name}\n"
               " Created: {0.created_at}\n"
               "  Joined: {0.joined_at}\n"
               "   Roles: {1}\n"
               "  Status: {0.status}\n"
               )
        roles = list(map(str, user.roles[1:]))[::-1]
        roles = ', '.join(roles)
        await self.bot.say("```\n{}\n```".format(fmt.format(user, roles)))

def setup(bot):
    bot.add_cog(Meta(bot))
