import inspect
import logging
import os
import random
import re

from collections import namedtuple
from datetime import datetime, timezone
from discord.ext import commands

def code_say(bot, msg):
    return bot.say(code_msg(msg))

def code_msg(msg, style=''):
    return f'```{style}\n{msg}```'

def cycle_shuffle(iterable):
    saved = [elem for elem in iterable]
    while True:
        random.shuffle(saved)
        for element in saved:
              yield element

def multi_replace(string, replacements):
    substrs = sorted(replacements, key=len, reverse=True)
    pattern = re.compile("|".join(map(re.escape, substrs)))
    return pattern.sub(lambda m: replacements[m.group(0)], string)

def truncate(s, length, placeholder):
    return (s[:length] + placeholder) if len(s) > length + len(placeholder) else s

def str_join(delim, iterable):
    return delim.join(map(str, iterable))

def pairwise(t):
    it = iter(t)
    return zip(it, it)

def nice_time(time):
    # Hopefully I can get a timezone-specific version.
    # I don't think that's possible though.
    new_time = time.replace(tzinfo=timezone.utc)
    return new_time.strftime("%Y/%m/%d %r (%Z)")

def parse_int(maybe_int, base=10):
    try:
        return int(maybe_int, base)
    except ValueError:
        return None

def duration_units(secs):
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    w, d = divmod(d, 7)
    unit_list = [(w, 'weeks'), (d, 'days'), (h, 'hours'), (m, 'mins'), (s, 'seconds')]
    return ', '.join([f"{round(n)} {u}" for n, u in unit_list if n])

def ordinal(num):
    # pay no attention to this ugliness
    return "%d%s" % (num,"tsnrhtdd"[(num//10%10!=1)*(num%10<4)*num%10::4])

def usage(*usages):
    def wrapper(cmd):
        # @usage could've been put above or below @commands.command
        func = cmd.callback if isinstance(cmd, commands.Command) else cmd
        func.__usage__ = usages
        return cmd
    return wrapper

def file_handler(name, path='./logs', *, format='%(asctime)s/%(levelname)s: %(name)s: %(message)s'):
    now = datetime.now()
    os.makedirs(path, exist_ok=True)
    handler = logging.FileHandler(filename=f'{path}/{name}{now : %Y-%m-%d %H.%M.%S.%f.txt}.log', encoding='utf-8', mode='w')
    handler.setFormatter(logging.Formatter(format))
    return handler

AlternateException = namedtuple('AlternateException', ['type', 'message', 'successful', 'original'])
def try_call(func, on_success=None, exception_alts=()):
    """Attempts an action.

    The original return value of a function can be accessed by the attribute "result".
    """
    exception_alts = dict(exception_alts)
    try:
        result = func()
    except BaseException as e:
        try:
            msg = exception_alts[type(e)]
        except KeyError:
            raise
        return AlternateException(type(e), msg.format(exc=e), False, e)
    else:
        return AlternateException(None, on_success, True, result)

async def try_async_call(func, *args, on_success=None, exception_alts=(), **kwargs):
    result = try_call(func, *args, on_success=on_success, exception_alts=exception_alts, **kwargs)
    return (result._replace(type=result.type, message=result.message, successful=result.successful,
            original=await result.original) if inspect.isawaitable(result.original) else result)
