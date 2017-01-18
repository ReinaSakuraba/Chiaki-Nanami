import asyncio
import discord
import inspect
import json
import logging
import os
import random
import re
import sys
import traceback

from chiakibot import chiaki_bot
from cogs.utils import converter
from cogs.utils.aitertools import AIterable, ACount
from cogs.utils.misc import image_from_url
from discord.ext import commands


##logger = logging.getLogger('discord')
##logger.setLevel(logging.INFO)
##handler = logging.FileHandler(filename='./logs/discord.log', encoding='utf-8', mode='w')
##handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
##logger.addHandler(handler)

# Chiaki Nanami has a tendency to append her sentences
# with either "I think" or "Probably"
# This is why I made this function
def negative(speech):
    return speech + '...' + random.choice(['I think', 'Probably'])

bot = chiaki_bot()

initial_extensions = (
#    'cogs.games.guess',
    'cogs.admin',
    'cogs.afk',
#    'cogs.cleverbot',
    'cogs.customcommands',
    'cogs.halp',
    'cogs.math',
    'cogs.meta',
    'cogs.moderator',     # TODO: Check for perms
    'cogs.musictest',     # TODO: Check for perms
#    'cogs.newpoints',
    'cogs.owner',
    'cogs.rng',
    'cogs.timer',
    'cogs.diepio.partylink',
    'cogs.diepio.wr',
#    'cogs.games.eventhost',
#    'cogs.games.fizzbuzz',
    'cogs.games.hangman',
    'cogs.games.rps',
    'cogs.games.tictactoe',
    'cogs.games.trivia',
)

logging.basicConfig(level=logging.INFO)

async def log(logstr):
    if not config["log"]: return
    async for log_channel in AIterable(config["logging_channels"]):
        await bot.send_message(bot.get_channel(log_channel), logstr)

def to_colour_long(r, g, b):
    return r << 16 | g << 8 | b

def find_chiaki_nanamis():
    for server in bot.servers:
        if server.id == '252525368865456130':
            continue
        maybe_role = discord.utils.get(server.roles, name='Chiaki Nanami')
        print(server, maybe_role)
        if maybe_role is not None and maybe_role.permissions.manage_roles:
            yield server, maybe_role

async def change_role_color():
    from math import sin
    await bot.wait_until_ready()
    async for i in ACount(1):
        sine = sin(i / 10) + 1
        val = int(sine * 64 + 128)  
        colour = discord.Colour(to_colour_long(255, val, val))
        # print(val, colour)
        async for server, role in AIterable(find_chiaki_nanamis()):
            await bot.edit_role(server, role, colour=colour)
        # await asyncio.sleep(0.01)


        
@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')

@bot.event
async def on_command(cmd, ctx):
    if cmd.hidden:
        return
    message = ctx.message
    if message.channel.is_private:
        return
    fmt = "{0.author} from {0.server} input `{0.content}` in {0.channel}"
    await log(fmt.format(message))

@bot.event
async def on_command_error(error, ctx):
    if isinstance(error, commands.NoPrivateMessage):
        await bot.send_message(ctx.message.author, 'This command cannot be used in private messages.')
    elif isinstance(error, commands.CommandInvokeError):
        print('In {0.command.qualified_name}:'.format(ctx), file=sys.stderr)
        traceback.print_tb(error.__traceback__)
        print('{0.__class__.__name__}: {0}'.format(error), file=sys.stderr)
    elif isinstance(error, commands.MissingRequiredArgument):
        await bot.send_message(ctx.message.channel,
                                    'This command (' + ctx.command.name + ') needs another Parameter\n')
    elif isinstance(error, commands.BadArgument):
        await bot.send_message(ctx.message.channel, error)
        traceback.print_tb(error.__cause__.__traceback__)
        print(error.__cause__, "\n--------------")
    
    traceback.print_tb(error.__traceback__)

@bot.event
async def on_message(message):
    from discord.ext.commands.view import StringView
    view = StringView(message.content)
    if bot._skip_check(message.author, bot.user):
        return

    prefix = await bot._get_prefix(message)
    invoked_prefix = prefix

    if not isinstance(prefix, (tuple, list)):
        if not view.skip_string(prefix):
            return
    else:
        invoked_prefix = discord.utils.find(view.skip_string, prefix)
        if invoked_prefix is None:
            return

        
##    if (not message.channel.is_private and
##        message.server.id == config["official_server"] and
##        message.channel.id not in config["official_server_allowed_channels"]):
##        if bot.user != message.author:
##           return await bot.send_message(message.channel, (
##               "Hello {.author.mention}. "
##               "Please use {} to use your commands please."
##               ).format(message,
##                        'or'.join(bot.get_channel(i).mention
##                                  for i in config["official_server_allowed_channels"][:-1])))

    await bot.process_commands(message)

@bot.command(pass_context=True, aliases=['cid'])
async def channelid(ctx):
    id = ctx.message.channel.id
    await bot.say("This channel's id is {}".format(id))
    
@bot.command()
async def invite():
    """...it's an invite"""
    official_server = bot.get_server(config["official_server"])
    invite_url = await bot.create_invite(official_server)
    await bot.say(f"""
I am not a not a public bot yet... but here's the invite link just in case:
https://discordapp.com/oauth2/authorize?client_id={bot.user.id}&scope=bot&permissions=2146823295

But in the meantime, here's a link to the offical Chiaki Nanami server:
{invite_url}

And here's the source code if you want it:
https://github.com/Ikusaba-san/Chiaki-Nanami
    """)

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

def load_config():
    with open('data/config.json') as f:
        return json.load(f)
        
def main():
    global config
    for ext in initial_extensions:
        try:
            bot.load_extension(ext)
        except Exception as e:
            print('Failed to load extension {}\n'.format(ext))
            traceback.print_exc()

    config = load_config()
    token = config.get("token", sys.argv[1])
    bot.run(token)
        

if __name__ == '__main__':
    main()
