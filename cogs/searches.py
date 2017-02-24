import aiohttp
import discord
import enum
import random

from bs4 import BeautifulSoup
from discord.ext import commands

from .utils.misc import truncate

_fmts = {
    'txt':  aiohttp.ClientResponse.text,
    'text': aiohttp.ClientResponse.text,
    'json': aiohttp.ClientResponse.json,
    }

class TagSearch(enum.Enum):
    YOUTUBE = ("https://www.youtube.com/results?search_query={search}", '+')
    ZEROCHAN = ("http://www.zerochan.net/{search}", '+')
    DICTIONARY = ("http://www.dictionary.com/browse/{search}", '-')
    URBAN = ("http://www.urbandictionary.com/define.php?term={search}", '+')
    OEIS = ('http://oeis.org/search', '')

    def __init__(self, url, delim=' '):
        self.url_format = url
        # Some URLs parse spaces differently
        self.delim = delim

    def url(self, search):
        return self.url_format.format(search=search.replace(' ', self.delim))

    async def search(self, search, session, *, fmt='txt', params=None):
        if params is None:
            params = {}
        coro = _fmts.get(fmt)
        if coro is None:
            raise ValueError(f"Invalid format for output specified: {fmt}")
        async with session.get(self.url(search), params=params) as response:
            return await coro(response)

# Someone make this more beautiful
class Searching:
    def __init__(self, bot):
        self.bot = bot
        self.session = self.bot.http.session

    @commands.cooldown(rate=10, per=5, type=commands.BucketType.server)
    @commands.command(aliases=['yt'], hidden=True)
    async def youtube(self, *, search):
        """Searches through youtube and stuff"""
        html = await TagSearch.YOUTUBE.search(search, self.session)
        soup = BeautifulSoup(html, "html.parser")
        vid = soup.findAll(attrs={'class':'yt-uix-tile-link'})[0]
        first_url = 'https://www.youtube.com' + vid['href']
        await self.bot.say(f"First result for **{search}**\n{first_url}")

    @commands.cooldown(rate=10, per=5, type=commands.BucketType.server)
    @commands.command(aliases=['0chan', '0c'], hidden=True)
    async def zerochan(self, *, tag):
        html = await TagSearch.ZEROCHAN.search(tag, self.session)
        soup = BeautifulSoup(html, "html.parser")
        ul = soup.findAll('ul', attrs={'id':'thumbs2'})[0]
        result = random.choice(ul.findAll('li'))
        result = result.find('a')['href']

        print(result, dir(result), len(result))

        image_html = await TagSearch.ZEROCHAN.search(result, self.session)
        image_soup = BeautifulSoup(image_html, "html.parser")
        image_result = image_soup.find('div', attrs={'id':'large'}).find('a')
        image_url = image_result['href']
        embed = (discord.Embed(title=image_soup.title.string, url=image_url)
                .set_image(url=image_url))
        await self.bot.say(embed=embed)

    @commands.command(aliases=['dict'])
    async def dictionary(self, *, word):
        await self.bot.say(TagSearch.DICTIONARY.url(word))

    @commands.command(aliases=['urban'])
    async def urbandictionary(self, *, word):
        #TODO
        await self.bot.say(TagSearch.URBAN.url(word))

    @commands.command()
    async def oeis(self, *search):
        """Retrieves a sequence from the On-Line Encyclopedia of Integer Sequences (OEIS)"""
        payload = {
            'q': ','.join(search),
            'n': '1',
            'fmt': 'json',
        }
        result_json = await TagSearch.OEIS.search('', self.session, fmt='json', params=payload)
        result = result_json['results'][0]
        id = f"A{result['number']:07d}"
        oeis_embed = (discord.Embed(title=id, description=result['name'], url=f'http://oeis.org/{id}', colour=0x00FF00)
                     .add_field(name='Sequence', value=result['data'].replace(',', ', '))
                     .add_field(name='Formula', value='\n'.join(result['formula'][:2]), inline=False)
                     )
        await self.bot.say(embed=oeis_embed)

class NSFW:
    def __init__(self, bot):
        self.bot = bot
        self.session = self.bot.http.session

def setup(bot):
    bot.add_cog(Searching(bot))