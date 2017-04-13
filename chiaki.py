import asyncio
import datetime
import discord
import json
import logging
import os
import random
import sys
import traceback

from chiakibot import chiaki_bot
from cogs.utils import checks, converter, errors
from cogs.utils.aitertools import aiterable, acount
from cogs.utils.compat import user_colour
from cogs.utils.misc import file_handler, nice_time
from discord.ext import commands

logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)
logger.addHandler(file_handler('discord'))
logging.basicConfig(level=logging.INFO)

bot = chiaki_bot()

initial_extensions = (
    'cogs.admin',
    'cogs.afk',
#    'cogs.cleverbot',
    'cogs.customcommands',
    'cogs.halp',
    'cogs.math',
    'cogs.meta',
    'cogs.moderator',
    'cogs.music',
#   'cogs.newpoints',
#    'cogs.otherstuff',
    'cogs.owner',
    'cogs.permissions',
    'cogs.quotes',
    'cogs.rng',
    'cogs.searches',
    'cogs.diepio.partylink',
    'cogs.diepio.wr',
#   'cogs.games.eventhost',
#   'cogs.games.fizzbuzz',
#   'cogs.games.hangman',
    'cogs.games.math',
    'cogs.games.rps',
    'cogs.games.tictactoe',
    'cogs.games.trivia',
#    'cogs.games.unscramble',
)
def log_embed(msg):
    author, channel, server = msg.author, msg.channel, msg.server
    user_name = "{0} | {0.id}".format(author)
    avatar = author.avatar_url or author.default_avatar_url
    id_fmt = '{0}\n({0.id})'
    return (discord.Embed(timestamp=msg.timestamp)
            .set_author(name=user_name, icon_url=avatar)
            .set_thumbnail(url=avatar)
            .add_field(name="Channel", value=id_fmt.format(channel))
            .add_field(name="Server", value=id_fmt.format(server))
            .add_field(name="Input", value=msg.content, inline=False)
            )

async def log(msg):
    if not config["log"]: return
    embed = log_embed(msg)
    embed.colour = await user_colour(msg.author)
    async for log_channel in aiterable(config["logging_channels"]):
        await bot.send_message(bot.get_channel(log_channel), embed=embed)

#------------------EVENTS----------------
@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')
    bot.loop.create_task(bot.change_game())
    bot.loop.create_task(bot.dump_db_cycle())
    bot.loop.create_task(bot.update_official_invite(config['official_server']))
    if not hasattr(bot, 'start_time'):
        bot.start_time = datetime.datetime.utcnow()

@bot.event
async def on_command(cmd, ctx):
    message = ctx.message
    owner = (await bot.application_info()).owner
    if message.author == owner:
        return
    bot.counter["Commands Executed"] += 1
    if cmd.hidden:
        return
    if message.channel.is_private:
        bot.counter["Private Commands"] += 1
        return
    await log(message)

@bot.event
async def on_command_completion(cmd, ctx):
    bot.counter["Commands Successful"] += 1

@bot.event
async def on_command_error(error, ctx):
    bot.counter["Commands Failed"] += 1
    if isinstance(error, commands.NoPrivateMessage):
        await bot.send_message(ctx.message.author, 'This command cannot be used in private messages.')
    elif isinstance(error, commands.CommandInvokeError):
        print(f'In {ctx.command.qualified_name}:', file=sys.stderr)
        traceback.print_tb(error.original.__traceback__)
        print('{0.__class__.__name__}: {0}'.format(error), file=sys.stderr)
    elif isinstance(error, commands.MissingRequiredArgument):
        await bot.send_message(ctx.message.channel,
                                    f'This command ({ctx.command.name}) needs another Parameter\n')
    elif isinstance(error, (commands.UserInputError, errors.PrivateMessagesOnly)):
        await bot.send_message(ctx.message.channel, error)
        if error.__cause__:
            traceback.print_tb(error.__cause__.__traceback__)
        print(error.__cause__, "\n--------------")

    traceback.print_tb(error.__traceback__)

@bot.event
async def on_message(message):
    bot.counter["Messages seen"] += 1
    await bot.process_commands(message)

#-----------------MISC COMMANDS--------------

@bot.command(aliases=['longurl'])
async def urlex(*, url: str):
    """Expands a shortened url into it's final form"""
    async with bot.http.session.head(url, allow_redirects=True) as resp:
        await bot.say(resp.url)

@bot.command(pass_context=True)
async def slap(ctx, target: converter.ApproximateUser=None):
    """Slaps a user"""
    # This can be refactored somehow...
    slapper = ctx.message.author
    if target is None:
        msg1 = f"{slapper.mention} is just flailing their arms around, I think."
        slaps = ["http://media.tumblr.com/tumblr_lw6rfoOq481qln7el.gif",
                 "http://i46.photobucket.com/albums/f104/Anime_Is_My_Anti-Drug/KururuFlail.gif",
                 ]
        msg2 = "(Hint: specify a user.)"
    elif target == slapper:
        msg1 = f"{slapper.mention} is slapping themself, I think."
        slaps = ["https://media.giphy.com/media/rCftUAVPLExZC/giphy.gif"]
        msg2 = f"I wonder why they would do that..."
    elif target == bot.user:
        msg1 = f"{slapper.mention} is trying to slap me, I think."
        slaps = ["http://i.imgur.com/K420Qey.gif"]
        msg2 =  "(Please don't do that.)"
    else:
        target = target.mention
        slaps = ["https://media.giphy.com/media/jLeyZWgtwgr2U/giphy.gif",
                 "http://i.imgur.com/dzefPFL.gif",
                 "https://s-media-cache-ak0.pinimg.com/originals/fc/e1/2d/fce12d3716f05d56549cc5e05eed5a50.gif",
                 ]
        msg1 = f"{target} was slapped by {slapper.mention}."
        msg2 = f"I wonder what {target} did to deserve such violence..."

    slap_image = random.choice(slaps)
    await bot.say(msg1 + f"\n{slap_image}")
    await asyncio.sleep(random.uniform(0.5, 2.3))
    await bot.say(msg2)

#--------------MAIN---------------

def load_config():
    with open('data/config.json') as f:
        return json.load(f)

def main():
    global config
    for ext in initial_extensions:
        try:
            bot.load_extension(ext)
        except Exception as e:
            print(f'Failed to load extension {ext}\n')
            traceback.print_exc()

    config = load_config()
    token = config.get("token") or sys.argv[1]
    bot.run(token)


if __name__ == '__main__':
    main()
