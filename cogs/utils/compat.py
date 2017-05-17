"""Compatibility incase some libraries weren't imported"""
import aiohttp
import asyncio
import discord
import functools

from collections import deque, OrderedDict
from discord.ext import commands
from io import BytesIO

# someone make this standard plz
try:
    from aiocache import cached as async_cache
except ImportError:
    # http://stackoverflow.com/a/37627076
    def async_cache(maxsize=128, key=functools._make_key):
        # support use as decorator without calling, for this case maxsize will
        # not be an int
        try:
            real_max_size = int(maxsize)
        except ValueError:
            real_max_size = 128

        boundless = maxsize is None
        cache = OrderedDict()

        async def run_and_cache(func, args, kwargs):
            """Run func with the specified arguments and store the result
            in cache."""
            result = await func(*args, **kwargs)
            cache[key(args, kwargs, False)] = result
            if not boundless and len(cache) > real_max_size:
                cache.popitem(last=False)
            return result

        def wrapper(func):
            @functools.wraps(func)
            def decorator(*args, **kwargs):
                key_ = key(args, kwargs, False)
                if key_ in cache:
                    # Some protection against duplicating calls already in
                    # progress: when starting the call cache the future, and if
                    # the same thing is requested again return that future.
                    if isinstance(cache[key_], asyncio.Future):
                        return cache[key_]
                    else:
                        f = asyncio.Future()
                        f.set_result(cache[key_])
                        return f
                else:
                    task = asyncio.Task(run_and_cache(func, args, kwargs))
                    cache[key_] = task
                    return task
            return decorator

        return wrapper(maxsize) if callable(maxsize) else wrapper

try:
    from colorthief import ColorThief
except ImportError:
    ColorThief = None

@async_cache(maxsize=16384)
async def read_image_from_url(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.read()

async def chunk_image_from_url(url, chunk_size=1024):
    while True:
        chunk = await resp.content.read(chunk_size)
        if not chunk:
            break
        yield chunk

@async_cache(maxsize=16384)
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

# itertools related stuff

try:
    from more_itertools import always_iterable, ilen, iterate
except ImportError:
    def ilen(iterable):
        d = deque(enumerate(iterable, 1), maxlen=1)
        return d[0][0] if d else 0

    def iterate(func, start):
        while True:
            yield start
            start = func(start)

    def always_iterable(obj):
        if obj is None:
            return ()

        if isinstance(obj, (str, bytes)) or not hasattr(obj, '__iter__'):
            return obj,

        return obj
