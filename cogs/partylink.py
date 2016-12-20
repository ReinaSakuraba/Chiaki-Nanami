import aiohttp
import re
import socket
import struct

from collections import namedtuple
from discord.ext import commands
from itertools import zip_longest

from .utils import checks
from .utils.database import Database


# I would like to tank rjt.rockx (aka Obliterator) for providing me information
# on how the diep.io party links work. Without him, this wouldn't be possible

def _pairwise(t):
    it = iter(t)
    return zip(it, it)

def _swap_pairs(s):
    it = iter(s)
    return "".join([b+a for a, b in zip_longest(it, it, fillvalue='')])

SERVERS_URL = "http://lb.diep.io/v2/find_servers"
async def _load_servers_from_site():
    async with aiohttp.get(SERVERS_URL) as response:
        data = await response.text()
    servers = _pairwise(data[2:].split('\x00'))
    return [DiepioServer(*s) for s in servers]

# Rather clunky, but because await must be used in async coroutines
# I didn't have much of a choice
async def _produce_server_list():
    global SERVER_LIST
    SERVER_LIST = await _load_servers_from_site()

def _search(pattern, string):
    try:
        return re.search(pattern, string).group(1)
    except AttributeError:
        return None
    
class DiepioServer(namedtuple('DiepioServer', 'ip_port name')):
    _translations = {
        'teams'   : '2-TDM',
        '4teams'  : '4-TDM',
        'dom'     : 'Domination',
        'maze'    : 'Maze',
        'sandbox' : 'Sandbox',
        }

    def _comp_loc_pair(self):
        location = re.search(r':(.*):', self.name)
        name = re.sub(r':(.*):', '', self.name)
        company, delim, region = name.partition('-')
        return company, region
    
    @property
    def ip(self):
        return _search(r'(.*):', self.ip_port)

    @property
    def port(self):
        return _search(r':(.*)', self.ip_port)
    
    @property
    def company(self):
        return self._comp_loc_pair()[0]
    
    @property
    def location(self):
        return self._comp_loc_pair()[1].title()
    
    @property
    def mode(self):
        m = re.search(r':(.*):', self.name)
        return self._translations.get(m.group(1), 'FFA')

class LinkServerData(namedtuple('LinkServerData', 'code server')):
    def is_sandbox(self):
        print(self.code, self.server.mode)
        return self.server.mode == 'Sandbox' or len(self.code) == 22

def _find_server_by_ip(ip):
    for server in SERVER_LIST:
        # print(server.ip, ip)
        if ip == server.ip:
            return server
    return None

def _hex_to_int(hexs):
    return int(hexs, 16)

def _ip_from_hex(hexs):
    new_hex = _swap_pairs(hexs)
    addr_long = _hex_to_int(new_hex)
    return socket.inet_ntoa(struct.pack("<L", addr_long)[::-1])

def _ip_to_hex(hexs):
    return socket.inet_ntoa(struct.pack("<L", addr_long)[::-1])
    
def _extract_links(message):
    return re.findall(r'\s?(diep.io/#[1234567890ABCDEF]*)\s?', message)
    
def _extract_code(link):
    m = re.search(r'\s?diep.io/#([1234567890ABCDEF]*)\s?', link)
    if m:
        return m.group(1)
    return None
  
def _is_valid_hex(s):
    try:
        _hex_to_int(s)
    except ValueError:
        return False
    else:
        return True

def _is_valid_party_link(link):
    code = _extract_code(link)
    # print(code, len(code))
    if len(code) not in (20, 22): return False
    return code and _is_valid_hex(code)

def format_data(data):
    return ("Code: {0}\n"
            "IP: {1.ip}\n"
            "Mode: {1.mode}\n"
            "Company: {1.company}\n"
            "Location: {1.location}\n"
            ).format(data.code, data.server)

def read_link(link):
    if not _is_valid_party_link(link):
        return None
    code = _extract_code(link)
    is_sandbox = len(code) == 22
    ip = _ip_from_hex(code[:8])
    server = _find_server_by_ip(ip)
    if server is None:
        return None
    return LinkServerData(code, server)

def _set_mode_bool(d, key, mode):
    mode = mode.lower()
    if mode in ("enable", "true", "1"):
        d[key] = True
        return True
    elif mode in ("disable", "false", "0"):
        d[key] = False
        return False
    return None

class PartyLinks:
    def __init__(self, bot):
        self.bot = bot
        config_default = lambda: {"detect" : True, "delete" : True}
        self.pl_config_db = Database.from_json("plconfig.json",
                                               factory_not_top_tier = config_default)

    async def on_message(self, message):
    #    print(("{0.timestamp} {0.author}: {0.content} ({0.server} in {0.channel.id})"
    #          ).format(message))
        server = message.server
        config = self.pl_config_db[server]
        links = _extract_links(message.content)
    #    print(links)
        if not links:
            return
        link_data = list(filter(None, map(read_link, links)))
    #    print(link_data)
        # Prevent posting sandbox links in public
        # Posting links in public chats never seems to end well so I've created a guard for it
        # TODO: Create a way to re-enable this
        if (config["delete"] and
            any(data.is_sandbox() for data in link_data)):
            await self.bot.delete_message(message)
            notif_fmt = ("{.author.mention} Please DM (direct message) "
                         "your sandbox links, unless you want Arena Closers")
                         
            return await self.bot.send_message(message.channel,
                                               notif_fmt.format(message))
        data_formats = [format_data(data) for data in link_data]
        if config["detect"] and data_formats:
            pld = "**__PARTY LINK{} DETECTED!__**\n".format('s' * (len(links) != 1))
            await self.bot.send_message(message.channel, pld + '\n'.join(data_formats))

    @commands.group(hidden=True, aliases=['plset'])
    @checks.admin_or_permissions()
    async def partylinkset(self):
        pass
            
    @partylinkset.command(pass_context=True)
    # Just in case.
    @checks.admin_or_permissions()
    async def detect(self, ctx, mode : str):
        result = _set_mode_bool(self.pl_config_db[ctx.message.server], "detect", mode)
        if result is None:
            return
        await self.bot.say("Party link detection {}abled, I think".format("deins"[result::2]))

    @partylinkset.command(pass_context=True)
    # Just in case.
    @checks.admin_or_permissions()
    async def delete(self, ctx, mode : str):
        """Configures if sandbox party links should be deleted"""
        result = _set_mode_bool(self.pl_config_db[ctx.message.server], "delete", mode)
        if result is None:
            return
        await self.bot.say("Sandbox link deletion {}abled, I think".format("deins"[result::2]))
    
        
def setup(bot):
    bot.loop.run_until_complete(_produce_server_list())
    pl = PartyLinks(bot)
    bot.add_cog(pl)
