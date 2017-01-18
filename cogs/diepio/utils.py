from discord import Colour

# hard-coding the colours because there is no color info of each mode from the webpage
MODE_COLOURS = {
    'FFA'     : Colour(0x71CCC8), # Colour.from_rgb(113, 204, 200),
    '2-TDM'   : Colour(0xB4FF8E), # Colour.from_rgb(180, 255, 142),
    '4-TDM'   : Colour(0xFF8E8E), # Colour.from_rgb(255, 142, 142),
    'Maze'    : Colour(0xB58EFF), # Colour.from_rgb(181, 142, 255),
    'Sandbox' : Colour(0xFB8EFF), # Colour.from_rgb(251, 142, 255),
    }

def mode_colour(mode):
    return MODE_COLOURS.get(mode, Colour.default())
