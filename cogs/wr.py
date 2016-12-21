import aiohttp
import asyncio
import discord

from datetime import datetime
from discord import Colour
from discord.ext import commands

from .utils import patching

WR_RECORD_URL = 'https://dieprecords.moepl.eu/api/records/json'
TANK_ID_URL = 'https://dieprecords.moepl.eu/api/tanks'
GAMEMODE_ID_URL = 'https://dieprecords.moepl.eu/api/gamemodes'

async def _load_json(session, url):
    async with session.get(url) as r:
        return await r.json()
    
async def _load_records(session):
    return await _load_json(session, WR_RECORD_URL)

async def _load_tanks(session):
    tank_list = await _load_json(session, TANK_ID_URL)
    return {d["tankname"] : d["id"] for d in tank_list if d["enabled"]}

async def _load_gamemodes(session):
    gm_id_list = await _load_json(session, GAMEMODE_ID_URL)
    return {"desktop" : {d["name"].lower() : d["id"]
                        for d in gm_id_list if d["mobile"] == "0"},
            "mobile"  : {d["name"].lower() : d["id"]
                        for d in gm_id_list if d["mobile"] == "1"} }

WR_RELOAD_TIME_SECS = 150

# Best compromise between performance and up-to-date-ness I could think of
async def load_wr_loop():
    global wr_records, tank_id_list, gamemode_id_map
    session = aiohttp.ClientSession()
    while True:
        wr_records = await _load_records(session)
        tank_id_list = await _load_tanks(session)
        gamemode_id_map = await _load_gamemodes(session)
        await asyncio.sleep(WR_RELOAD_TIME_SECS)

async def _wr_loop(bot):
    await bot.wait_until_ready()
    return await load_wr_loop()

# hard-coding the colours because there is no color info of each mode from the webpage

MODE_COLOURS = {
    'FFA'   : Colour.from_rgb(113, 204, 200),
    '2-TDM' : Colour.from_rgb(180, 255, 142),
    '4-TDM' : Colour.from_rgb(255, 142, 142),
    'Maze'  : Colour.from_rgb(181, 142, 255),
    }

_alt_tank_names = {
    'anni': 'annihilator',
    'autosmasher': 'auto smasher', 'auto-smasher': 'auto smasher',
    'mg': 'booster',
    'octo': 'octo tank', 'octo-tank' : 'octo tank',
    'pentashot': 'penta shot', 'penta': 'penta shot', 'penta-shot': 'penta shot',
    'spread': 'spread shot', 'spreadshot': 'spread shot',
    'triangle': 'tri-angle',
       }

def _replace_tank(tankname):
    return _alt_tank_names.get(tankname, tankname)

def _wr_embed(records):
    game_mode = records["gamemode"]
    data = discord.Embed(colour=MODE_COLOURS.get(game_mode, Colour.default()))
    for field_name, key in (("Achieved by", "name"), ("Score", "score"),
                            ("Full Score", "scorefull"),):
        data.add_field(name=field_name, value=records[key])
        
    approved_date = datetime.strptime(records["approvedDate"],
                                      '%Y-%m-%d %H:%M:%S').date()
    data.add_field(name="Date", value=str(approved_date))
    submitted_url = records["submittedlink"]
    if "youtube" in submitted_url:
        # No clean way to set the video yet
        rest = submitted_url
    else:
        data.set_image(url=submitted_url)
        rest = ""

    return data, rest

class WR:
    def __init__(self, bot):
        self.bot = bot
        
    async def _wr_mode(self, version, mode, tank):
        _version = version.lower()
        _mode = mode.lower()
        _tank = tank.title()
        try:
            tank_id = tank_id_list[_tank]
        except KeyError:
            await self.bot.say("Tank {} doesn't exist".format(tank))
            return None
        try:
            records = wr_records[_version]
        except KeyError:
            await self.bot.say("Version {} is not valid".format(version))
            return None
        try:
            index = gamemode_id_map[_version][_mode] % 4 - 1
        except KeyError:
            await self.bot.say("Mode {} not recognized for {}".format(mode, version))
            return None
        return records[str(tank_id)][index]

    @commands.command(aliases=['wr'])
    async def worldrecord(self, version, mode, *, tank : str):
        """Retrieves the world record from the WRA site

        version is version of diep.io (mobile or desktop)
        mode is the gamemode (eg FFA)
        And of course, tank is the type of tank

        """
        if mode.lower() in ('2tdm', '4tdm'):
            mode = mode[0] + '-' + mode[1:]
        elif mode.lower() == 'tdm':
            mode = '2-tdm'
        tank = _replace_tank(tank.lower())
        record = await self._wr_mode(version, mode, tank)
        if record is None:
            return
        title = "**__{0} {gamemode} {tankname}__**".format(version.title(), **record)
        embed, extra = _wr_embed(record)
        await self.bot.say(title, embed=embed)
        if extra:
            await self.bot.say(extra)    

    def _submit(self, name: str, tankid: int, gamemodeid: int, score: int, url: str):
        payload = {'inputname': name,
                   'gamemode_id': gamemodeid,
                   'selectclass': tankid,
                   'score': score,
                   'proof': url}

        print(payload)
        r = aiohttp.post('https://dieprecords.moepl.eu/api/submit/recordtest', data=payload)
        print(r)
        return r
    
    @commands.command()
    async def submitwr(self, name: str, tank: str, version : str, mode: str, score: int, url: str):
        """Submits a potential WR to the WR site

        The name and tank should be in quotes if you intend on putting spaces in either parameter
        (eg if you're gonna submit a WR under Junko Enoshima you should enter it as "Junko Enoshima")
        """
        _tank = _replace_tank(tank)
        _vers = version.lower()
        _mode = mode.lower()

        response = self._submit(name,
                                tank_id_list[_tank.title()],
                                gamemode_id_map[_vers][_mode],
                                score,
                                url)
        msg = ""
        print(response.text)
        '''
        if (response.text != 'Too Many Attempts.'):
            pass
        else:
            msg = 'Sorry, there have been too many attempts to submit records from this bot. Please try the website directly.'  
        await self.bot.say(msg, delete_after=60)
        '''

    async def site(self):
        """Site of the WRA"""
        await self.bot.say('https://dieprecords.moepl.eu/')

    @commands.command()
    async def gamemodes(self):
        desktop_gamemodes = sorted(gamemode_id_map["desktop"].keys())
        dt_gm_names = map(str.title, desktop_gamemodes)
        mobile_gamemodes = sorted(gamemode_id_map["mobile"].keys())
        m_gm_names = map(str.title, mobile_gamemodes)
        fmt = "List of desktop gamemodes:\n{}\n\nList of mobile gamemodes:\n{}"
        await self.bot.say(fmt.format(', '.join(dt_gm_names), ', '.join(m_gm_names)))
        
def setup(bot):
    bot.loop.create_task(_wr_loop(bot))
    bot.add_cog(WR(bot))
