import random
import re

from datetime import timezone

def code_say(bot, msg):
    return bot.say(code_msg(msg))

def code_msg(msg, style=''):
    return '```{style}\n{}```'.format(msg)

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
	return ', '.join(f"{round(n)} {u}" for n, u in unit_list if n)

def ordinal(num):
    # pay no attention to this ugliness
    return "%d%s" % (num,"tsnrhtdd"[(num//10%10!=1)*(num%10<4)*num%10::4])

def usage(*usages):
    def wrapper(cmd):
        cmd.__usage__ = usages
        return cmd
    return wrapper