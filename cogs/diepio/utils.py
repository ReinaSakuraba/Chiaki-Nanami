from discord import Colour

from ..utils import patching

MODE_COLOURS = {
    'FFA'     : Colour.from_rgb(113, 204, 200),
    '2-TDM'   : Colour.from_rgb(180, 255, 142),
    '4-TDM'   : Colour.from_rgb(255, 142, 142),
    'Maze'    : Colour.from_rgb(181, 142, 255),
    'Sandbox' : Colour.from_rgb(251, 142, 255),
    }

def mode_colour(mode):
    return MODE_COLOURS.get(mode, Colour.default())
