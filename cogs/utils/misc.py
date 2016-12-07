import random

from discord import utils

def code_say(bot,  msg):
    return bot.say('```\n{}```'.format(msg))

def cycle_shuffle(iterable):
    saved = [elem for elem in iterable]
    while True:
        random.shuffle(saved)
        for element in saved:
              yield element
              
def filter_attr(iterable, **attrs):
    def predicate(elem):
        for attr, val in attrs.items():
            nested = attr.split('__')
            obj = elem
            for attribute in nested:
                obj = getattr(obj, attribute)

            if obj != val:
                return False
        return True

    return filter(predicate, iterable)

def str_swap(string, swap1, swap2):
    return string.replace(swap1, '%temp%').replace(swap2, swap1).replace('%temp%', swap2)
