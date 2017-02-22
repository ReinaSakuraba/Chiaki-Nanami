from discord import Colour

# hard-coding the colours because there is no color info of each mode from the webpage
MODE_COLOURS = {
    'FFA'     : Colour(0x71CCC8), # Colour.from_rgb(113, 204, 200),
    '2-TDM'   : Colour(0xB4FF8E), # Colour.from_rgb(180, 255, 142),
    '4-TDM'   : Colour(0xFF8E8E), # Colour.from_rgb(255, 142, 142),
    'Maze'    : Colour(0xB58EFF), # Colour.from_rgb(181, 142, 255),
    'Sandbox' : Colour(0xFB8EFF), # Colour.from_rgb(251, 142, 255),
    }

DIEPIO_WIKI_URL = "https://hydra-media.cursecdn.com/diepio.gamepedia.com/"

def mode_colour(mode):
    return MODE_COLOURS.get(mode, Colour.default())

def get_tank_icon(tank):
    tank_title = tank.title()
    if tank_title == "Basic Tank":
        tank_title = "Tank"
    tank_title = tank.replace(" ", "_")
    tank_pic = tank_title + ".png"
    tank_md5 = hashlib.md5(tank_pic.encode('utf-8')).hexdigest()
    return ("{0}{1[0]}/{1[:2]}/{2}"
            ).format(DIEPIO_WIKI_URL, tank_md5, tank_pic)
