import discord
import random

from bs4 import BeautifulSoup 
from discord.ext import commands
from enum import Enum

class TagSearch(Enum):
    YOUTUBE = ("https://www.youtube.com/results?search_query={search}", '+')
    ZEROCHAN = ("http://www.zerochan.net/{search}", '+')
    DICTIONARY = ("http://www.dictionary.com/browse/{search}", '-')
    URBAN = ("http://www.urbandictionary.com/define.php?term={search}", '+')
    
    def __init__(self, url, delim=' '):
        self.url_format = url
        # Some URLs parse spaces differently
        self.delim = delim
  
    def url(self, search):
        return self.url_format.format(search=search.replace(' ', self.delim))
        
    async def search(self, search, session):
        async with session.get(self.url(search)) as response:
            return await response.text()
    
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
        
        
def setup(bot):
    bot.add_cog(Searching(bot))