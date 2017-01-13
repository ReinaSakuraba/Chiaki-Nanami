import aiohttp
import asyncio
import discord
import sys

from collections import OrderedDict
from datetime import datetime
from discord.ext import commands
from hashlib import md5
from itertools import chain
from operator import itemgetter

from . import utils

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
async def load_wr_loop(bot):
    await bot.wait_until_ready()
    global wr_records, tank_id_list, gamemode_id_map
    session = bot.http.session
    while not bot.is_closed:
        wr_records = await _load_records(session)
        tank_id_list = await _load_tanks(session)
        gamemode_id_map = await _load_gamemodes(session)
        await asyncio.sleep(WR_RELOAD_TIME_SECS)

_alt_tank_names = {
    'anni': 'annihilator',
    'anokuu': 'necromancer',
    'autogunner': 'auto gunner',
<<<<<<< HEAD
    'autosmasher': 'auto smasher',
=======
    'autosmasher': 'auto smasher', 
>>>>>>> de1fd7396ff92c8c83b52649194be6a22413c2f8
    'auto-smasher': 'auto smasher',
    'autotrapper': 'auto trapper',
    'auto-trapper': 'auto trapper',
    'basic': 'basic tank',
    'buf': 'penta shot',
    'buff': 'penta shot',
    'cancer': 'booster',
    'cancer 2': 'necromancer',
    'junko': 'destroyer',
    'junko enoshima': 'destroyer',
    'master': 'factory',
    'mg': 'booster',
    'necro': 'necromancer',
    'noahth3pandatank': 'predator',
    'octo': 'octo tank',
    'octo-tank' : 'octo tank',
    'penta': 'penta shot',
    'pentashot': 'penta shot',
    'penta-shot': 'penta shot',
    'pandatank': 'predator',
    'spread': 'spread shot',
    'spreadshot': 'spread shot',
    'spread-shot': 'spread shot',
    'tank': 'basic tank',
    'th3pandatank': 'predator',
    'triangle': 'tri-angle',
    'tritrapper': 'tri-trapper',
    'tri trapper': 'tri-trapper',
       }

def _replace_tank(tankname):
    return _alt_tank_names.get(tankname, tankname)

def _get_wiki_image(tank):
    if tank == "Basic Tank":
        tank = "Tank"
    tank = tank.replace(" ", "_")
    tank_pic = tank + ".png"
    tank_md5 = md5(tank_pic.encode('utf-8')).hexdigest()
    return ("https://hydra-media.cursecdn.com/diepio.gamepedia.com/{}/{}/{}"
            ).format(tank_md5[0], tank_md5[:2], tank_pic)

def _wr_embed(records):
    game_mode = records["gamemode"]
    data = discord.Embed(colour=utils.mode_colour(game_mode))

    url = _get_wiki_image(records["tankname"])
    print(url)
    data.set_thumbnail(url=url)

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
    elif not (submitted_url.endswith('.png') or submitted_url.endswith('.jpg')):
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
            await self.bot.say(f"Tank **{tank}** doesn't exist")
            return None
        try:
            records = wr_records[_version]
        except KeyError:
            await self.bot.say(f"Version **{version}** is not valid")
            return None
        try:
            index = gamemode_id_map[_version][_mode] % 4 - 1
        except KeyError:
            await self.bot.say(f"Mode **{mode}** not recognized for {version}")
            return None
        return records[str(tank_id)][index]

    async def _wr_tank(self, tank):
        _tank = tank.title()
        try:
            tank_id = tank_id_list[_tank]
        except KeyError:
            await self.bot.say("Tank {} doesn't exist".format(tank))
            return None

        desktop_records = sorted(wr_records["desktop"][str(tank_id)], key=itemgetter("gamemode_id"))
        mobile_records = sorted(wr_records["mobile"][str(tank_id)], key=itemgetter("gamemode_id"))

        return desktop_records, mobile_records

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
        tank_alias = _replace_tank(tank.lower())
        record = await self._wr_mode(version, mode, tank_alias)
        if record is None:
            return

        tank_true = f" ({tank.title()})" * (tank_alias.lower() != tank.lower())
        title = "**__{0} {gamemode} {tankname}{1}__**".format(version.title(), tank_true, **record)
        embed, extra = _wr_embed(record)
        await self.bot.say(title, embed=embed)
        if extra:
            await self.bot.say(extra)

    @commands.command()
    async def wrtank(self, *, tank : str):
        """Gives a summary of the WRs for a particular tank

        Use ->wr for the full info of a particular WR (proof, date, and full score)
        """

        tank_alias = _replace_tank(tank.lower())
        record = await self._wr_tank(tank_alias)
        if record is None:
            return
        desktop, mobile = record
        tank_true = f" ({tank.title()})" * (tank_alias.lower() != tank.lower())
        title = f"**__{tank_alias.title()}{tank_true}__**"

        def embed_from_iterable(title, records):
            embed = discord.Embed(title=title.title())
            url = _get_wiki_image(tank_alias.title())
            embed.set_thumbnail(url=url)
            for record in records:
                line = "{name}\n**{score}**".format(**record)
                embed.add_field(name=record["gamemode"], value=line)
            embed.set_footer(text=f'Type "->wr {title} <gamemode> {tank}" for the full WR info')
            return embed

        desktop_embed = embed_from_iterable("desktop", desktop)
        mobile_embed = embed_from_iterable("mobile", mobile)

        await self.bot.say(title, embed=desktop_embed)
        await self.bot.say(embed=mobile_embed)

    async def _submit(self, name: str, tankid: int, gamemodeid: int, score: int, url: str):
        payload = {'inputname': name,
                   'gamemode_id': gamemodeid,
                   'selectclass': tankid,
                   'score': score,
                   'proof': url}

        session = self.bot.http.session
        print(payload)
        r = await session.post('https://dieprecords.moepl.eu/api/submit/recordtest', data=payload)
        print(r)
        return r

    @commands.command()
    async def submitwr(self, name: str, tank: str, version : str, mode: str, score: int, url: str):
        """Submits a potential WR to the WR site

        The name and tank should be in quotes if you intend on putting spaces in either parameter
        (eg if you're gonna submit a WR under Junko Enoshima you should enter it as "Junko Enoshima")
        """
        tank_ = _replace_tank(tank)
        vers_ = version.lower()
        mode_ = mode.lower()
        record = await self._wr_mode(vers_, mode_, tank_)

        if record is None:
            return

        full_score = record["scorefull"]
        if score < full_score:
            await self.bot.say(f"Your score ({score}) is too low. The WR is {full_score}.")
            return

        response = await self._submit(name,
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

    # TODO: Make this look pretty
    @commands.command()
    async def gamemodes(self):
        """All the gamemodes for diep.io"""
        desktop_gamemodes = sorted(gamemode_id_map["desktop"].keys())
        dt_gm_names = map(str.title, desktop_gamemodes)
        mobile_gamemodes = sorted(gamemode_id_map["mobile"].keys())
        m_gm_names = map(str.title, mobile_gamemodes)
        fmt = "List of desktop gamemodes:\n{}\n\nList of mobile gamemodes:\n{}"
        await self.bot.say(fmt.format(', '.join(dt_gm_names), ', '.join(m_gm_names)))

    @commands.command()
    async def tanks(self):
        """All the tanks for diep.io"""
        tanks = sorted(tank_id_list.keys())
        await self.bot.say(', '.join(tanks))

    @commands.command(pass_context=True)
    async def records(self, ctx, *, name: str):
        """Finds all the diep.io WRs for a particular name"""
        records = await _load_json(self.bot.http.session,
                                  'https://dieprecords.moepl.eu/api/recordsByName/' + name)

        # For some reason the recordsByName api uses either
        # a list or a dict for current/former records
        # We must account for both
        def get_records(l_or_d):
            try:
                return l_or_d.values()
            except AttributeError:
                return l_or_d
        current = sorted(get_records(records["current"]), key=itemgetter("tank"))
        former  = sorted(get_records(records["former"]),  key=itemgetter("tank"))

        if not (current or former):
            await self.bot.say("I can't find records for {} :(".format(name))
            return

        def sort_records(records, mobile):
            return [rec for rec in records if mobile == int(rec["mobile"])]

        desktop_current = sort_records(current, False)
        mobile_current  = sort_records(current, True)

        desktop_former = sort_records(former, False)
        mobile_former  = sort_records(former, True)

        def mapper(record):
            return "__{tank} {gamemode}__ | {score} |  <{submittedlink}>".format(**record)

        def lines(header, records):
            return [header.format(len(records))] + list(map(mapper, records))

        headers = [f"**__{name}__**", f"**Current World Records**: {len(current)}"]
        desktop_current_str = lines("**Desktop**: {}", desktop_current)
        mobile_current_str  = lines("**Mobile**: {}",  mobile_current)
        former_header = ["-" * 20, f"**Former World Records**: {len(former)}"]
        desktop_former_str  = lines("**Desktop**: {}", desktop_former)
        mobile_former_str   = lines("**Mobile**: {}",  mobile_former)

        paginator = commands.Paginator(prefix='', suffix='')
        for line in chain(headers, desktop_current_str, mobile_current_str,
                          former_header, desktop_former_str, mobile_former_str):
            paginator.add_line(line)

        author = ctx.message.author
        channel = ctx.message.channel
        pages = paginator.pages
        destination = author if len(pages) >= 2 else channel

        if destination == channel:
            await self.bot.say("The records has been sent to your private messages due to the length")
        for page in pages:
            await self.bot.send_message(destination, page)

def setup(bot):
    bot.loop.create_task(load_wr_loop(bot))
    bot.add_cog(WR(bot))
