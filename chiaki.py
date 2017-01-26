import asyncio
import discord
import json
import logging
import os
import random
import sys
import traceback

from chiakibot import chiaki_bot
from cogs.utils import converter
from cogs.utils.aitertools import AIterable, ACount
from cogs.utils.misc import nice_time
from discord.ext import commands

logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)
try:
    handler = logging.FileHandler(filename='./logs/discord.log', encoding='utf-8', mode='w')
except FileNotFoundError:
    os.makedirs("logs", exist_ok=True)
    handler = logging.FileHandler(filename='./logs/discord.log', encoding='utf-8', mode='w')


handler.setFormatter(logging.Formatter('%(asctime)s/%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)
logging.basicConfig(level=logging.INFO)


bot = chiaki_bot()

initial_extensions = (
#    'cogs.games.guess',
    'cogs.admin',
    'cogs.afk',
    'cogs.cleverbot',
    'cogs.customcommands',
    'cogs.halp',
    'cogs.math',
    'cogs.meta',
    'cogs.moderator',
    'cogs.musictest',
#    'cogs.newpoints',
    'cogs.owner',
    'cogs.rng',
    'cogs.searches',
    'cogs.timer',
    'cogs.diepio.partylink',
    'cogs.diepio.wr',
#    'cogs.games.eventhost',
    'cogs.games.fizzbuzz',
    'cogs.games.hangman',
    'cogs.games.math',
    'cogs.games.rps',
    'cogs.games.tictactoe',
    'cogs.games.trivia',
    'cogs.games.unscramble',
)
def log_embed(msg):
    author = msg.author
    user_name = "{0.name}#{0.discriminator} | {0.id}".format(author)
    avatar = author.avatar_url or avatar.default_avatar_url
    location = f"from #{msg.channel} in {msg.server}"
    return (discord.Embed(description=location)
            .set_author(name=user_name, icon_url=avatar)
            .set_thumbnail(url=avatar)
            .add_field(name="Input", value=msg.content)
            .set_footer(text=nice_time(msg.timestamp))
            )

async def log(msg):
    if not config["log"]: return
    embed = log_embed(msg)
    async for log_channel in AIterable(config["logging_channels"]):
        await bot.send_message(bot.get_channel(log_channel), embed=embed)

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

#------------------EVENTS----------------
@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')

@bot.event
async def on_command(cmd, ctx):
    bot.commands_counter["Commands Executed"] += 1
    if cmd.hidden:
        bot.commands_counter["Private Commands"] += 1
        return
    message = ctx.message
    if message.channel.is_private:
        return
    owner = (await bot.application_info()).owner
    if message.author == owner:
        return
    fmt = "{0.author} from {0.server} input `{0.content}` in {0.channel}"
    await log(ctx.message)

@bot.event
async def on_command_completion(cmd, ctx):
    bot.commands_counter["Commands Successful"] += 1

@bot.event
async def on_command_error(error, ctx):
    bot.commands_counter["Commands Failed"] += 1
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
    bot.commands_counter["Messages seen"] += 1
    await bot.process_commands(message)

#-----------------MISC COMMANDS--------------

@bot.command()
async def invite():
    """...it's an invite"""
    official_server = bot.get_server(config["official_server"])
    invite_url = await bot.create_invite(official_server)
    await bot.say(f"""
I am not a not a public bot yet... but here's the invite link just in case:
{bot.invite_url}

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
    token = config.get("token") or sys.argv[1]
    bot.run(token)

if __name__ == '__main__':
    main()
