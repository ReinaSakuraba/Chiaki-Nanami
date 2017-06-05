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
from core import chiaki_bot
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

def _load_json(filename):
    def remove_comments(string):
        pattern = r"(\".*?\"|\'.*?\')|(/\*.*?\*/|//[^\r\n]*$)"
        regex = re.compile(pattern, re.MULTILINE | re.DOTALL)
        return regex.sub(lambda match: match.group(1) if match.group(2) is None else "", string)
    with open(filename) as f:
        return json.loads(remove_comments(f.read()))
try:
    config = _load_json('config.json')
except FileNotFoundError:
    raise RuntimeError("a config json is required")

bot = chiaki_bot(config)


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
    bot.command_counter['failed'] += 1

    cause =  error.__cause__
    if isinstance(error, errors.ChiakiException):
        await ctx.send(str(error))
    elif isinstance(error, commands.BadArgument):
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
    for ext in config.pop('extensions'):
        try:
            bot.load_extension(ext)
        except Exception as e:
            print(f'Failed to load extension {ext}\n')
            traceback.print_exc()

    with redirect_exception((FileNotFoundError, "A credentials file is required"), cls=RuntimeError):
        credentials = _load_json('credentials.json')

    with redirect_exception((IndexError, "A token is required"), cls=RuntimeError):
        token = credentials.pop('token', None) or sys.argv[1]

    bot.run(token)
    return bot._config['restart_code'] * bot.reset_requested


if __name__ == '__main__':
    sys.exit(main())
