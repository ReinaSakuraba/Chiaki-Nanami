import aiohttp
import asyncio
import discord
import functools

from io import BytesIO

from . import cache


try:
    from colorthief import ColorThief
except ImportError:
    ColorThief = None

@cache.cache(maxsize=16384)
async def read_image_from_url(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.read()

@cache.cache(maxsize=16384)
async def _dominant_color_from_url(url):
    """Returns an rgb tuple consisting the dominant color given a image url."""
    with BytesIO(await read_image_from_url(url)) as f:
        # TODO: Make my own color-grabber module. This is ugly as hell.
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, functools.partial(ColorThief(f).get_color, quality=1))

async def url_color(url):
    return discord.Colour.from_rgb(*(await _dominant_color_from_url(url)))
url_colour = url_color

async def user_color(user):
    if ColorThief:
        avatar = user.avatar_url_as(format=None)
        return await url_color(avatar)
    return getattr(user, 'colour', discord.Colour.default())
user_colour = user_color

