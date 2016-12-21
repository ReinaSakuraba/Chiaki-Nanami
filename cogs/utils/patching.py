# Monkey-patching things.

import discord

def from_rgb(cls, r, g, b):
    return cls(r << 16 | g << 8 | b)

discord.Colour.from_rgb = classmethod(from_rgb)
del from_rgb
