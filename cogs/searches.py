import aiohttp
import contextlib
import difflib
import discord
import enum
import itertools
import pickle
import random

from discord.ext import commands

from .utils import errors
from .utils.compat import async_cache
from .utils.misc import truncate

try:
    from bs4 import BeautifulSoup
except ModuleNotFoundError:
    BeautifulSoup = None

_fmts = {
    'txt':  aiohttp.ClientResponse.text,
    'text': aiohttp.ClientResponse.text,
    'json': aiohttp.ClientResponse.json,
    }

_static_session = aiohttp.ClientSession()
class TagSearch(enum.Enum):
    YOUTUBE = ("https://www.youtube.com/results?search_query={search}", '+')
    ZEROCHAN = ("http://www.zerochan.net/{search}", '+')
    DICTIONARY = ("http://www.dictionary.com/browse/{search}", '-')
    URBAN = ("http://www.urbandictionary.com/define.php?term={search}", '+')
    OEIS = ('http://oeis.org/search', '')
    XKCD = ('https://xkcd.com/{search}/info.0.json', '')
    WIKIPEDIA = ('http://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles={search}&rvprop=timestamp|user|comment|content&format=json', '_')

    def __init__(self, url, delim=' '):
        self.url_format = url
        # Some URLs parse spaces differently
        self.delim = delim

    def url(self, search):
        return self.url_format.format(search=search.replace(' ', self.delim))

    # TODO: caching.
    @async_cache(maxsize=2 ** 20, key=lambda args, kwargs, typed: pickle.dumps(args, 1) + pickle.dumps(kwargs, 1))
    async def search(self, search, *, fmt='txt', params=None):
        if params is None:
            params = {}
        coro = _fmts.get(fmt)
        if coro is None:
            raise ValueError(f"Invalid format for output specified: {fmt}")
        async with _static_session.get(self.url(search), params=params) as response:
            if response.status == 200:
                return await coro(response)
            raise LookupError(f"Received a status {response.status} for the following parameters:\n"
                              f"{self.url(search)}, {params}")

# Someone make this more beautiful
class Searching:
    def __init__(self, bot):
        self.bot = bot
        self._xkcd_task = self.bot.loop.create_task(self._refresh_xkcd_cache())

    def __unload(self):
        with contextlib.suppress(BaseException):
            self._xkcd_task.cancel()

    if BeautifulSoup:
        @commands.cooldown(rate=10, per=5, type=commands.BucketType.guild)
        @commands.command(aliases=['yt'], hidden=True)
        async def youtube(self, ctx, *, search):
            """Searches through youtube and stuff"""
            html = await TagSearch.YOUTUBE.search(search)
            soup = BeautifulSoup(html, "html.parser")
            vid = soup.findAll(attrs={'class':'yt-uix-tile-link'})[0]
            first_url = 'https://www.youtube.com' + vid['href']
            await ctx.send(f"First result for **{search}**\n{first_url}")

        @commands.cooldown(rate=10, per=5, type=commands.BucketType.guild)
        @commands.command(aliases=['0chan', '0c'], hidden=True)
        async def zerochan(self, ctx, *, tag):
            html = await TagSearch.ZEROCHAN.search(tag)
            soup = BeautifulSoup(html, "html.parser")
            ul = soup.findAll('ul', attrs={'id':'thumbs2'})[0]
            result = random.choice(ul.findAll('li'))
            result = result.find('a')['href']

            print(result, dir(result), len(result))

            image_html = await TagSearch.ZEROCHAN.search(result)
            image_soup = BeautifulSoup(image_html, "html.parser")
            image_result = image_soup.find('div', attrs={'id':'large'}).find('a')
            image_url = image_result['href']
            embed = (discord.Embed(title=image_soup.title.string, url=image_url)
                    .set_image(url=image_url))
            await ctx.send(embed=embed)

    @commands.command(aliases=['dict'])
    async def dictionary(self, ctx, *, word):
        # TODO
        await ctx.send(TagSearch.DICTIONARY.url(word))

    @commands.command(aliases=['urban'])
    async def urbandictionary(self, ctx, *, word):
        #TODO
        await ctx.send(TagSearch.URBAN.url(word))

    @commands.command()
    async def oeis(self, ctx, *search):
        """Retrieves a sequence from the On-Line Encyclopedia of Integer Sequences (OEIS)"""
        payload = {
            'q': ','.join(search),
            'n': '1',
            'fmt': 'json',
        }
        result_json = await TagSearch.OEIS.search('', fmt='json', params=payload)
        result = result_json['results'][0]
        id = f"A{result['number']:07d}"
        oeis_embed = (discord.Embed(title=id, description=result['name'], url=f'http://oeis.org/{id}', colour=0x00FF00)
                     .add_field(name='Sequence', value=result['data'].replace(',', ', '))
                     .add_field(name='Formula', value='\n'.join(result['formula'][:2]), inline=False)
                     )
        await ctx.send(embed=oeis_embed)

    async def _refresh_xkcd_cache(self):
        self.xkcds = {}
        for i in itertools.count(1):
            try:
                self.xkcds[str(i)] = await TagSearch.XKCD.search(str(i), fmt='json')
            except LookupError:
                if i == 404:
                    continue
                self.latest_xkcd = str(i - 1)
                break

    async def display_xkcd(self, ctx, result):
        num = result['num']
        xkcd_embed = (discord.Embed(title=f"{num}: {result['title']}", url=f'https://xkcd.com/{num}/')
                     .set_image(url=result['img'])
                     .set_footer(text=result['alt'])
                     )

        await ctx.send(embed=xkcd_embed)

    @commands.group(invoke_without_command=True)
    async def xkcd(self, ctx, *, query=None):
        """Retrieves the XKCD comic that corresponds with the keyword."""
        if query is None:
            pass
        if query == '404':
            raise errors.InvalidUserArgument('XKCD comic not found.')

        result = self.xkcds.get(query)
        if result is None:
            query = query.lower()
            seq = difflib.SequenceMatcher(lambda x: x == ' ', a=None, b=query)

            def key(s):
                o = s['title'].lower()
                seq.set_seq1(o)
                m = seq.find_longest_match(0, len(o), 0, len(query))
                return m.size

            result = max(self.xkcds.values(), key=key)
            if result is None:
                raise errors.InvalidUserArgument(f"Couldn't find an XKCD comic \"{num}\"")

        await self.display_xkcd(ctx, result)

    @xkcd.command(name='latest')
    async def xkcd_latest(self, ctx):
        """Retrieves the latest XKCD comic."""
        await self.display_xkcd(ctx, self.xkcds[self.latest_xkcd])

    @xkcd.command(name='random')
    async def xkcd_random(self, ctx):
        """Retrieves a random XKCD comic."""
        await self.display_xkcd(ctx, random.choice(list(self.xkcds.values())))

    async def wikipedia(self, ctx, *, title):
        pass

def setup(bot):
    bot.add_cog(Searching(bot))

def teardown(bot):
    self.bot.loop.create_task(_static_session.close())