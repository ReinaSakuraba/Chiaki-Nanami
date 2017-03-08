"""Compatibility incase some libraries weren't imported"""
import aiohttp
import os
import uuid

from discord.ext import commands
# someone make this standard plz
try:
    from aiocache import cached as async_cache
except ImportError:
    # http://stackoverflow.com/a/37627076
    import asyncio
    from collections import OrderedDict
    from functools import _make_key, wraps

    def async_cache(maxsize=128):
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
            cache[_make_key(args, kwargs, False)] = result
            if not boundless and len(cache) > real_max_size:
                cache.popitem(False)
            return result

        def wrapper(func):
            @wraps(func)
            def decorator(*args, **kwargs):
                key = _make_key(args, kwargs, False)
                if key in cache:
                    # Some protection against duplicating calls already in
                    # progress: when starting the call cache the future, and if
                    # the same thing is requested again return that future.
                    if isinstance(cache[key], asyncio.Future):
                        return cache[key]
                    else:
                        f = asyncio.Future()
                        f.set_result(cache[key])
                        return f
                else:
                    task = asyncio.Task(run_and_cache(func, args, kwargs))
                    cache[key] = task
                    return task
            return decorator

        if callable(maxsize):
            return wrapper(maxsize)
        else:
            return wrapper

try:
    from colorthief import ColorThief
except ImportError:
    ColorThief = None

_chunk_size = 1024
async def _write_from_url(url, filename):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            with open(filename, 'wb') as fd:
                # TODO: Is there a way to make an async functools.partial?
                while True:
                    chunk = await resp.content.read(_chunk_size)
                    if not chunk:
                        break
                    fd.write(chunk)

@async_cache(maxsize=_chunk_size * 8)
async def _dominant_color_from_url(url, tmp_file='tmp.jpg'):
    '''Downloads ths image file and analyzes the dominant color'''
    tmp_file = f'{uuid.uuid4()}{tmp_file}'
    await _write_from_url(url, tmp_file)
    color_thief = ColorThief(tmp_file)
    dominant_color = color_thief.get_color(quality=1)
    os.remove(tmp_file)
    return dominant_color

# Let's hope Danny makes an extension for this
def _color_from_rgb(r, g, b):
    rgb = f"#{r:02x}{g:02x}{b:02x}"
    return commands.ColourConverter(None, rgb).convert()

async def url_color(url):
    return _color_from_rgb(*(await _dominant_color_from_url(url)))

async def user_color(user):
    if ColorThief:
        avatar = user.avatar_url or user.default_avatar_url
        return _color_from_rgb(*(await _dominant_color_from_url(avatar)))
    return user.colour
user_colour = user_color
