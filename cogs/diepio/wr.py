import aiohttp
import asyncio
import discord
import hashlib

from collections import OrderedDict
from datetime import datetime
from discord.ext import commands
from itertools import chain
from operator import itemgetter

from . import utils
from ..utils.errors import InvalidUserArgument, ResultsNotFound
from ..utils.misc import usage
from ..utils.paginator import DelimPaginator

WR_RECORD_URL = 'https://dieprecords.moepl.eu/api/records/json'
TANK_ID_URL = 'https://dieprecords.moepl.eu/api/tanks'
GAMEMODE_ID_URL = 'https://dieprecords.moepl.eu/api/gamemodes'

async def _load_json(session, url):
    async with session.get(url) as r:
        return await r.json()

WR_RELOAD_TIME_SECS = 60

_alt_tank_names = OrderedDict([
    ('Adasba', 'Overlord'),
    ('Anni', 'Annihilator'),
    ('Anokuu', 'Necromancer'),
    ('Auto-Smasher', 'Auto Smasher'),
    ('Auto-Trapper', 'Auto Trapper'),
    ('Autogunner', 'Auto Gunner'),
    ('Autosmasher', 'Auto Smasher'),
    ('Autotrapper', 'Auto Trapper'),
    ('Basic', 'Basic Tank'),
    ('Bela', 'Penta Shot'),
    ('Buf', 'Penta Shot'),
    ('Buf Penta', 'Penta Shot'),
    ('Buff', 'Penta Shot'),
    ('Buff Penta', 'Penta Shot'),
    ('Cancer', 'Booster'),
    ('Cancer 2', 'Necromancer'),
    ('Junko', 'Destroyer'),
    ('Junko Enoshima', 'Destroyer'),
    ('Master', 'Factory'),
    ('Mg', 'Booster'),
    ('Necro', 'Necromancer'),
    ('Noahth3Pandatank', 'Predator'),
    ('Octo', 'Octo Tank'),
    ('Octo-Tank', 'Octo Tank'),
    ('Pandatank', 'Predator'),
    ('Penta', 'Penta Shot'),
    ('Penta-Shot', 'Penta Shot'),
    ('Pentashot', 'Penta Shot'),
    ('Spread', 'Spread Shot'),
    ('Spread-Shot', 'Spread Shot'),
    ('Spreadshot', 'Spread Shot'),
    ('Tank', 'Basic Tank'),
    ('Th3Pandatank', 'Predator'),
    ('Tri Trapper', 'Tri-Trapper'),
    ('Triangle', 'Tri-Angle'),
    ('Tritrapper', 'Tri-Trapper')
    ])

def _replace_tank(tankname):
    t = tankname.title()
    return _alt_tank_names.get(t, t)

def _get_wiki_image(tank):
    if tank == "Basic Tank":
        tank = "Tank"
    tank = tank.replace(" ", "_")
    tank_pic = tank + ".png"
    tank_md5 = hashlib.md5(tank_pic.encode('utf-8')).hexdigest()
    return ("https://hydra-media.cursecdn.com/diepio.gamepedia.com/{}/{}/{}"
            ).format(tank_md5[0], tank_md5[:2], tank_pic)

def _wr_embed(records):
    game_mode = records["gamemode"]
    url = _get_wiki_image(records["tankname"])
    approved_date = datetime.strptime(records["approvedDate"], '%Y-%m-%d %H:%M:%S').date()

    data = (discord.Embed(colour=utils.mode_colour(game_mode))
            .set_thumbnail(url=url)
            .add_field(name="Achieved by", value=records["name"])
            .add_field(name="Score", value=records["score"])
            .add_field(name="Full Score", value=records["scorefull"])
            .add_field(name="Date", value=str(approved_date))
            )

    submitted_url = records["submittedlink"]
    if "youtube" in submitted_url:
        # No clean way to set the video yet
        rest = submitted_url
    elif not (submitted_url.endswith('.png') or submitted_url.endswith('.jpg')):
        rest = submitted_url
    else:
        data.set_image(url=submitted_url)
        rest = ''

    return data, rest

class WRA:
    wr_records, tank_ids, gamemode_ids = {}, {}, {}
    _mode_translations = {
        'tdm': '2-TDM', '2tdm': '2-TDM', '2teams': '2-TDM',
        '4tdm': '4-TDM', '4teams': '4-TDM',
        }
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.bot.loop.create_task(self._load_wr_loop())

    def __unload(self):
        # pray it closes
        self.bot.loop.create_task(self.session.close())

    async def _load_records(self):
        return await _load_json(self.session, WR_RECORD_URL)

    async def _load_tanks(self):
        tank_list = await _load_json(self.session, TANK_ID_URL)
        return {d["tankname"] : d["id"] for d in tank_list if d["enabled"]}

    async def _load_gamemodes(self):
        gm_id_list = await _load_json(self.session, GAMEMODE_ID_URL)
        return {"desktop" : {d["name"] : d["id"]
                            for d in gm_id_list if d["mobile"] == "0"},
                "mobile"  : {d["name"] : d["id"]
                            for d in gm_id_list if d["mobile"] == "1"} }

    # Best compromise between performance and up-to-date-ness I could think of
    async def _load_wr_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed:
            self.wr_records.update(await self._load_records())
            self.tank_ids.update(await self._load_tanks())
            self.gamemode_ids.update(await self._load_gamemodes())
            await asyncio.sleep(WR_RELOAD_TIME_SECS)

    @classmethod
    def _find_mode(cls, mode, version):
        lowered = mode.lower()
        if lowered in cls._mode_translations:
            return cls._mode_translations[lowered]
        result = discord.utils.find(lambda e: e.lower() == lowered, cls.gamemode_ids[version])
        if result is not None:
            return result
        raise commands.BadArgument(f"Mode **{mode}** not recognized for WRs")

    def all_tanks(self):
        return sorted(self.tank_ids)

    def _tank_id(self, tank):
        try:
            return str(self.tank_ids[tank])
        except KeyError:
            raise commands.BadArgument(f"Tank **{tank}** doesn't exist")

    def _wr_mode(self, version, mode, tank):
        tank_id = self._tank_id(tank)
        try:
            records = self.wr_records[version]
        except KeyError:
            raise commands.BadArgument(f"Version **{version}** is not valid")
        index = self.gamemode_ids[version][mode] % 4 - 1
        return records[tank_id][index]

    def _wr_tank(self, tank):
        tank_id = self._tank_id(tank)
        def get_records(version):
            try:
                return sorted(self.wr_records[version][tank_id], key=itemgetter("gamemode_id"))
            except KeyError:
                return []

        return get_records("desktop"), get_records("mobile")

    @commands.command(aliases=['wr'])
    @usage('wr desktop ffa sniper')
    async def worldrecord(self, version: str, mode, *, tank : _replace_tank):
        """Retrieves the world record from the WRA site

        version is version of diep.io (mobile or desktop)
        mode is the gamemode (eg FFA)
        And of course, tank is the type of tank

        """
        version = version.lower()
        mode = WRA._find_mode(mode, version)
        record = self._wr_mode(version, mode, tank)

        title = "**__{0} {gamemode} {tankname}__**".format(version.title(), **record)
        embed, extra = _wr_embed(record)
        await self.bot.say(title, embed=embed)
        if extra:
            await self.bot.say(extra)

    @commands.command(pass_context=True)
    @usage('wr sniper')
    async def wrtank(self, ctx, *, tank: _replace_tank):
        """Gives a summary of the WRs for a particular tank

        Use "wr" for the full info of a particular WR (proof, date, and full score)
        """
        desktop, mobile = self._wr_tank(tank)
        title = f"**__{tank}__**"
        prefix = self.bot.str_prefix(self, ctx.message.server)

        def embed_from_iterable(title, records):
            embed = discord.Embed(title=title.title())
            url = _get_wiki_image(tank)
            embed.set_thumbnail(url=url)
            for record in records:
                line = "{name}\n**{score}**".format(**record)
                embed.add_field(name=record["gamemode"], value=line)
            embed.set_footer(text=f'Type "{prefix}wr {title} <gamemode> {tank}" for the full WR info')
            return embed

        desktop_embed = embed_from_iterable("desktop", desktop)
        mobile_embed = embed_from_iterable("mobile", mobile) if mobile else None

        await self.bot.say(title, embed=desktop_embed)
        if mobile_embed is not None:
            await self.bot.say(embed=mobile_embed)

    async def _submit(self, name, tankid, gamemodeid, score, url):
        payload = {'inputname': name,
                   'gamemode_id': gamemodeid,
                   'selectclass': tankid,
                   'score': score,
                   'proof': url}
        return await self.session.post('https://dieprecords.moepl.eu/api/submit/record', data=payload)

    @commands.command()
    @usage('submitwr "Junko Enoshima" destroyer desktop ffa 1666714 http://i.imgur.com/tIHCj5K.png')
    async def submitwr(self, name: str, tank: _replace_tank, version : str, mode: _find_mode,
                       score: int, url: str):
        """Submits a potential WR to the WR site

        The name and tank should be in quotes if you intend on putting spaces in either parameter
        (eg if you're gonna submit a WR under Junko Enoshima you should enter it as "Junko Enoshima")
        """
        vers_ = version.lower()
        record = await self._wr_mode(vers_, mode, tank)

        full_score = record["scorefull"]
        if score < 50000:
            raise InvalidUserArgument(f"Your score ({score}) is too low. It must be at least 50000.")
        if score < int(full_score):
            raise InvalidUserArgument(f"Your score ({score}) doesn't break the current WR ({full_score}).")

        submission = f'("{name}" "{tank}" {version} {score} <{url}>)'

        async with await self._submit(name, tank_ids[tank_], gamemode_ids[vers_][mode_],
                                      score, url) as response:
            result = await response.json()

        msg = f"**{result['status'].title()}!** {result['content']}\n{submission}"
        await self.bot.say(msg, delete_after=60)

    # TODO: Make this look pretty
    @commands.command()
    async def gamemodes(self):
        """All the gamemodes for diep.io"""
        def names(version):
            modes = sorted(self.gamemode_ids[version])
            str_modes = ', '.join(modes)
            return f"List of {version} gamemodes:\n{str_modes}\n"
        await self.bot.say(names('desktop') + names('mobile'))

    @commands.command()
    async def tanks(self):
        """All the tanks for diep.io"""
        await self.bot.say(', '.join(self.all_tanks()))

    @commands.command()
    async def tankaliases(self):
        """All the tanks for diep.io"""
        tank_aliases = '\n'.join([f"{k:<18} == {v}" for k, v in _alt_tank_names.items()])
        await self.bot.say(f"```\n{tank_aliases}```")

    @commands.command(pass_context=True)
    @usage('records Anokuu')
    async def records(self, ctx, *, name: str):
        """Finds all the diep.io WRs for a particular name"""
        records = await _load_json(self.session, f'https://dieprecords.moepl.eu/api/recordsByName/{name}')

        # For some reason the recordsByName api uses either
        # a list or a dict for current/former records
        # We must account for both
        def get_records(l_or_d):
            records = getattr(l_or_d, "values", lambda: l_or_d)()
            return sorted(records, key=itemgetter("tank"))
        current = get_records(records["current"])
        former  = get_records(records["former"])

        if not (current or former):
            raise ResultsNotFound(f"I can't find records for {name} :(")

        def records_by_type(records):
            return ([rec for rec in records if not int(rec["mobile"])],
                    [rec for rec in records if int(rec["mobile"])])

        desktop_current, mobile_current = records_by_type(current)
        desktop_former, mobile_former = records_by_type(former)

        def lines(header, records):
            def mapper(record):
                return "__{tank}__ __{gamemode}__ | {score} |  <{submittedlink}>".format(**record)
            return [header.format(len(records)), *list(map(mapper, records))]

        current_header = [f"**__{name}__**", f"**Current World Records**: {len(current)}"]
        desktop_current_str = lines("**Desktop**: {}", desktop_current)
        mobile_current_str  = lines("**Mobile**: {}",  mobile_current)
        former_header = ["-" * 20, f"**Former World Records**: {len(former)}"]
        desktop_former_str  = lines("**Desktop**: {}", desktop_former)
        mobile_former_str   = lines("**Mobile**: {}",  mobile_former)

        all_iterables = chain(headers, desktop_current_str, mobile_current_str,
                              former_header, desktop_former_str, mobile_former_str)

        paginator = DelimPaginator.from_iterable(all_iterables, prefix='', suffix='')
        pages = paginator.pages
        destination = ctx.message.channel

        if sum(map(len, pages)) >= 1000:
            await self.bot.reply("The records has been sent to your private messages due to the length")
            destination = ctx.message.author
        for page in pages:
            await self.bot.send_message(destination, page)

def setup(bot):
    bot.add_cog(WRA(bot))
