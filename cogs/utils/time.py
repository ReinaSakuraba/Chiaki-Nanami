import datetime
import re

from dateutil.relativedelta import relativedelta
from discord.ext import commands
from functools import partial
from more_itertools import grouper

from .formats import human_join, pluralize

_pairwise = partial(grouper, 2)

DURATION_MULTIPLIERS = {
    'y': 60 * 60 * 24 * 365, 'yr' : 60 * 60 * 24 * 365,
    'w': 60 * 60 * 24 * 7,   'wk' : 60 * 60 * 24 * 7,
    'd': 60 * 60 * 24,       'day': 60 * 60 * 24,
    'h': 60 * 60,            'hr' : 60 * 60,
    'm': 60,                 'min': 60,
    's': 1,                  'sec': 1,
}


_time_pattern = ''.join(f'(?:([0-9]{{1,5}})({u1}|{u2}))?'
                        for u1, u2 in _pairwise(DURATION_MULTIPLIERS))
_time_compiled = re.compile(f'{_time_pattern}$')


def duration(string):
    try:
        return float(string)
    except ValueError as e:
        match = _time_compiled.match(string)
        if match is None:
            raise commands.BadArgument(f'{string} is not a valid time.') from None
        no_nones = filter(None, match.groups())
        return sum(float(amount) * DURATION_MULTIPLIERS[unit]
                   for amount, unit in _pairwise(no_nones))


TIME_UNITS = ('week', 'day', 'hour', 'minute')


def duration_units(secs):
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    w, d = divmod(d, 7)
    # Weeks, days, hours, and minutes are guaranteed to be integral due to being
    # the quotient rather than the remainder, so these can be safely made to ints.
    # The reason for the int cast is because if the seconds is a float,
    # the other units will be floats too.
    unit_list = [*zip(TIME_UNITS, map(int, (w, d, h, m))),
                 ('second', round(s, 2) if s % 1 else int(s))]
    joined = ', '.join(pluralize(**{u: n}) for u, n in unit_list if n)
    return joined


def human_timedelta(dt, *, source=None):
    now = source or datetime.datetime.utcnow()

    if dt > now:
        delta = relativedelta(dt, now)
        suffix = ''
    else:
        delta = relativedelta(now, dt)
        suffix = ' ago'

    if delta.microseconds and delta.seconds:
        delta = delta + relativedelta(seconds=+1)

    attrs = ['year', 'month', 'day', 'hour', 'minute', 'second']
    elems = (getattr(delta, attr + 's') for attr in attrs)
    output = [pluralize(**{attr: elem}) for attr, elem in zip(attrs, elems) if elem]

    if not output:
        return 'now'
    return human_join(output) + suffix
