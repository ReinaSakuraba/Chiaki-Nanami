import asyncio
import collections
import discord
import json
import logging
import os
import random
import re
import sys
import traceback
import warnings

from cogs.utils import errors
from cogs.utils.context_managers import redirect_exception
from cogs.utils.misc import file_handler
from core import Chiaki
from datetime import datetime
from discord.ext import commands

# use faster event loop, but fall back to default if on Windows or not installed
try:
    import uvloop
except ImportError:
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)
logging.basicConfig(level=logging.INFO)
logger.addHandler(file_handler('discord'))


bot = Chiaki()


#------------------EVENTS----------------
@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')

    if bot.official_guild is None:
        warnings.warn("Your bot is not in the server you've set for 'official_guild' in config.json. "
                      "Either your ID is isn't an integer, or you haven't invited your bot to that server. "
                     f"Use this link to invite it: {bot.oauth_url}")

    if not hasattr(bot, 'appinfo'):
        bot.appinfo = (await bot.application_info())

    if bot.owner_id is None:
        bot.owner = bot.appinfo.owner
        bot.owner_id = bot.owner.id
    else:
        bot.owner = bot.get_user(bot.owner_id)

    if not hasattr(bot, 'start_time'):
        bot.start_time = datetime.utcnow()

    bot.loop.create_task(bot.change_game())
    if not config.get('official_server_invite'):
        bot.loop.create_task(bot.update_official_invite())

    if not hasattr(bot, 'command_counter'):
        bot.command_counter = collections.Counter()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure) and await bot.is_owner(ctx.author):
        await ctx.reinvoke()
        return

    bot.command_counter['failed'] += 1

    cause =  error.__cause__
    if isinstance(error, errors.ChiakiException):
        await ctx.send(str(error))
    elif type(error) is commands.BadArgument:
        await ctx.send(str(cause or error))
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send('This command cannot be used in private messages.')
    elif isinstance(error, commands.CommandInvokeError):
        print(f'In {ctx.command.qualified_name}:', file=sys.stderr)
        traceback.print_tb(error.original.__traceback__)
        print('{0.__class__.__name__}: {0}'.format(error), file=sys.stderr)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f'This command ({ctx.command}) needs another parameter ({error.param})')

    traceback.print_tb(error.__traceback__)
    print(f'{type(error).__name__}: {error}')
    if cause:
        traceback.print_tb(cause.__traceback__)


command_log = logging.getLogger('commands')
command_log.addHandler(file_handler('commands'))

@bot.event
async def on_message(message):
    bot.message_counter += 1

    # prevent other bots from triggering commands
    if not message.author.bot:
        await bot.process_commands(message)

@bot.event
async def on_command(ctx):
    bot.command_counter['commands'] += 1
    bot.command_counter['executed in DMs'] += isinstance(ctx.channel, discord.abc.PrivateChannel)
    fmt = ('Command executed in {0.channel} ({0.channel.id}) from {0.guild} ({0.guild.id}) '
           'by {0.author} ({0.author.id}) Message: "{0.message.content}"')
    command_log.info(fmt.format(ctx))

@bot.event
async def on_command_completion(ctx):
    bot.command_counter['succeeded'] += 1

#--------------MAIN---------------

def main():
    bot.run()
    return 69 * bot.reset_requested


if __name__ == '__main__':
    sys.exit(main())
