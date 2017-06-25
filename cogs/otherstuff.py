import discord
import json
import operator
import functools
import itertools
import os
import random
import sys
import time

from collections import namedtuple
from datetime import datetime
from discord.ext import commands

from .utils import errors
from .utils.compat import user_colour
from .utils.misc import emoji_url


# ---------------- Ship-related utilities -------------------

def _lerp_color(c1, c2, interp):
    return tuple(round((v2 - v1) * interp + v1) for v1, v2 in zip(c1, c2))

_lerp_red = functools.partial(_lerp_color, (0, 0, 0), (255, 0, 0))

class UserInfo(namedtuple('UserInfo', 'name id avatar')):
    __slots__ = ()

    @classmethod
    def from_user(cls, user):
        avatar = user.avatar or user.default_avatar.value
        return cls(str(user), user.id, avatar)

_default_rating_comments = (
    'There is no chance for this to happen.',
    'Why...',
    'No way, not happening.',
    'Nope.',
    'Maybe.',
    'Woah this actually might happen.',
    'owo what\'s this',
    'You\'ve got a chance!',
    'Definitely.',
    'What are you waiting for?!',
)

def _scale(old_min, old_max, new_min, new_max, number):
    return ((number - old_min) / (old_max - old_min)) * (new_max - new_min) + new_min

_value_to_index = functools.partial(_scale, 0, 100, 0, len(_default_rating_comments) - 1)

class ShipRating(namedtuple('ShipRating', 'value comment')):
    __slots__ = ()

    def __new__(cls, value, comment=None):
        if comment is None:
            index = round(_value_to_index(value))
            comment = _default_rating_comments[index]
        return super().__new__(cls, value, comment) 

_special_pairs = {
    # frozenset((239110748180054017, 192060404501839872)) : ShipRating(100, 'testing special pairs')
}

@functools.lru_cache(maxsize=2 ** 20)
def _calculate_compatibilty(info_pair):
    # This has to be stored as a frozenset pair to make sure that
    # switching the two users doesn't affect the result

    try:
        info1, info2 = info_pair
    except ValueError:
        # User inputted themself as the second argument
        if len(info_pair) == 1:
            info1, = info_pair
            return ShipRating(0, f"RIP {info1.name}. They're forever alone.")
        raise

    id_pair = frozenset((info1.id, info2.id))
    if id_pair in _special_pairs:
        return _special_pairs[id_pair]

    return ShipRating(random.randrange(101))

#--------------- End ship stuffs ---------------------

TEN_SEC_REACTION = '\N{BLACK SQUARE FOR STOP}'

class OtherStuffs:
    def __init__(self, bot):
        self.bot = bot
        self.last_messages = {}
        self.default_time = datetime.utcnow()
        self.bot.loop.create_task(self._load_pastas())

    def __unload(self):
        # unload the cache if necessary...
        _calculate_compatibilty.cache_clear()
        pass

    async def _load_pastas(self):
        def nobody_kanna_cross_it():
            with open(os.path.join('data', 'copypastas.json'), encoding='utf-8') as f:
                return json.load(f)
        self.copypastas = await self.bot.loop.run_in_executor(None, nobody_kanna_cross_it)

    @commands.group(invoke_without_command=True, aliases=['c+v'])
    async def copypasta(self, ctx, index: int, *, name=None):
        """Returns a copypasta from an index and name"""
        copy_pasta = self.copypastas[index]
        category, copypastas = copy_pasta['category'], copy_pasta['copypastas']
        pasta = random.choice(list(copypastas.values())) if name is None else copypastas[name.title()]

        embed = discord.Embed(title=f"{category} {name}", description=pasta, colour=0x00FF00)
        await ctx.send(embed=embed)

    @copypasta.command(name="groups")
    async def copypasta_groups(self, ctx):
        padding = len(self.copypastas) // 10
        pastas = itertools.starmap('`{0}.` {1}'.format, enumerate(c['category'] for c in self.copypastas))
        embed = discord.Embed(title="All the categories (and their indices)", description='\n'.join(pastas))
        await ctx.send(embed=embed)

    @copypasta.command(name="pastas")
    async def copypasta_pastas(self, ctx, index: int):
        pastas = self.copypastas[index]
        category, copypastas = pastas['category'], pastas['copypastas']
        description = '\n'.join([f'\N{BULLET} {c}' for c in copypastas])
        embed = discord.Embed(title=category, description=description)
        await ctx.send(embed=embed)

    @copypasta.error
    @copypasta_pastas.error
    async def copypasta_error(self, ctx, error):
        cause = error.__cause__
        if isinstance(cause, IndexError):
            await ctx.send(f'Index {ctx.args[2]} is out of range.')
        elif isinstance(cause, KeyError):
            await ctx.send(f"Category \"{self.copypastas[ctx.args[2]]['category']}\" "
                           f"doesn't have pasta called \"{ctx.kwargs['name']}\"")

    @commands.command(usage=['rjt#2336 Nelyn#7808', 'Danny#0007 Jake#0001'])
    async def ship(self, ctx, user1: discord.Member, user2: discord.Member=None):
        """Determines if two users are compatible with one another.

        If only one user is specified, it determines *your* compatibility with that user.
        """
        if user2 is None:
            user1, user2 = ctx.author, user1

        # In order to keep the modification that comes with changing avatar / name
        # we have to use a tuple of these stats.
        # Using the actual User object won't work if we're gonna take advantage of functools.lru_cache
        # Because a change in avatar or username won't create a new result
        #
        # Also make sure ->ship user1 user2 and ->ship user2 user1 return the same result
        pair = frozenset(map(UserInfo.from_user, (user1, user2)))
        rating = _calculate_compatibilty(pair)

        # TODO: Use pillow to make an image out of the two users' thumbnails.
        field_name = 'I give it a...'       # In case I decide to have it choose between mulitiple field_names 
        description =  f'{user1.mention} x {user2.mention}?'
        colour = discord.Colour.from_rgb(*_lerp_red(rating.value / 100))
        ship_embed = (discord.Embed(description=description, colour=colour)
                     .set_author(name='Ship')
                     .add_field(name=field_name, value=f'{rating.value} / 100')
                     .set_footer(text=rating.comment)
                     )

        await ctx.send(embed=ship_embed)

    @commands.command()
    async def ping(self, ctx):
        """Your average ping command."""
        start = time.perf_counter()     # fuck time.monotonic()
        message = await ctx.send('Poing...')
        end = time.perf_counter()       # fuck time.monotonic()
        ms = (end - start) * 1000
        await message.edit(content=f'Poing! ({ms :.3f} ms)')

    @commands.command()
    async def slap(self, ctx, target: discord.Member=None):
        """Slaps a user"""
        # This can be refactored somehow...
        slapper = ctx.author
        if target is None:
            msg1 = f"{slapper} is just flailing their arms around, I think."
            slaps = ["http://media.tumblr.com/tumblr_lw6rfoOq481qln7el.gif",
                     "http://i46.photobucket.com/albums/f104/Anime_Is_My_Anti-Drug/KururuFlail.gif",
                     ]
            msg2 = "(Hint: specify a user.)"
        elif target.id == slapper.id:
            msg1 = f"{slapper} is slapping themself, I think."
            slaps = ["https://media.giphy.com/media/rCftUAVPLExZC/giphy.gif",
                     "https://media.giphy.com/media/EQ85WxyAAwEaQ/giphy.gif",
                     ]
            msg2 = f"I wonder why they would do that..."
        elif target.id == self.bot.user.id:
            msg1 = f"{slapper} is trying to slap me, I think."
            slaps = ["http://i.imgur.com/K420Qey.gif",
                     "https://media.giphy.com/media/iUgoB9zOO0QkU/giphy.gif",
                     "https://media.giphy.com/media/Kp4c6lf3oR7lm/giphy.gif",
                     ]
            msg2 =  "(Please don't do that.)"
        else:
            slaps = ["https://media.giphy.com/media/jLeyZWgtwgr2U/giphy.gif",
                     "https://media.giphy.com/media/RXGNsyRb1hDJm/giphy.gif",
                     "https://media.giphy.com/media/zRlGxKCCkatIQ/giphy.gif",
                     "https://media.giphy.com/media/MelHtIx2kmZz2/giphy.gif",
                     "https://media.giphy.com/media/147iq4Fk1IGvba/giphy.gif",
                     "http://i.imgur.com/dzefPFL.gif",
                     "https://s-media-cache-ak0.pinimg.com/originals/fc/e1/2d/fce12d3716f05d56549cc5e05eed5a50.gif",
                     ]
            msg1 = f"{target} was slapped by {slapper}."
            msg2 = f"I wonder what {target} did to deserve such violence..."

        slap_embed = (discord.Embed(colour=self.bot.colour)
                     .set_author(name=msg1)
                     .set_image(url=random.choice(slaps))
                     .set_footer(text=msg2)
                     )
        await ctx.send(embed=slap_embed)

    @commands.command(name='lastseen', enabled=False)
    async def last_seen(self, ctx, user: discord.User):
        """Shows the last words of a user"""

        # TODO: Save these (will probably require a DB).
        message = self.last_messages.get(user.id)
        colour = await user_colour(user)
        if message is None:
            embed = (discord.Embed(colour=colour, timestamp=self.default_time)
                    .set_author(name=f'{user} has not been alive...')
                    .set_thumbnail(url=user.avatar_url)
                    .set_footer(text='Last seen ')
                    )
        else:
            embed = (discord.Embed(colour=colour, description=message.content, timestamp=message.created_at)
                    .set_author(name=f"{user}'s last words...")
                    .set_thumbnail(url=user.avatar_url)
                    .add_field(name='\u200b', value=f'From #{message.channel} in {message.guild}')
                    .set_footer(text='Last seen ')
                    )
        await ctx.send(embed=embed)

    @commands.command(name='10s')
    async def ten_seconds(self, ctx):
        """Starts a 10s test. How well can you judge 10 seconds?"""

        description = f'Click the {TEN_SEC_REACTION} when you think 10 second have passed'
        embed = (discord.Embed(colour=0xFFFF00, description=description)
                .set_author(name=f'10 Seconds Test - {ctx.author}', icon_url=emoji_url('\N{ALARM CLOCK}'))
                )

        message = await ctx.send(embed=embed)
        await message.add_reaction(TEN_SEC_REACTION)

        def check(reaction, user):
            return (reaction.message.id == message.id 
                    and user.id == ctx.author.id
                    and reaction.emoji == TEN_SEC_REACTION
                   )

        reaction, user = await ctx.bot.wait_for('reaction_add', check=check)
        now = datetime.utcnow()
        duration = (now - message.created_at).total_seconds()

        embed.colour = 0x00FF00
        embed.description = (f'When you clicked the {TEN_SEC_REACTION} button, \n'
                             f'**{duration: .2f} seconds** have passed.')
        embed.set_author(name=f'Test completed', icon_url=embed.author.icon_url)
        embed.set_thumbnail(url=ctx.author.avatar_url)
        await message.edit(embed=embed)

    async def on_message(self, message):
        self.last_messages[message.author.id] = message


def setup(bot):
    bot.add_cog(OtherStuffs(bot))
