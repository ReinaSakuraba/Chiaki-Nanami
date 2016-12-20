import aiohttp
import re
import socket
import struct

from collections import namedtuple
from itertools import zip_longest

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

    @property
    def ip(self):
        return _search(r'(.*):', self.ip_port)

    @property
    def port(self):
        return _search(r':(.*)', self.ip_port)

    @property
    def location(self):
        return re.sub(r':(.*):', '', self.name)
    
    @property
    def mode(self):
        return re.sub(r':(.*):', lambda s: self._translations.get(s, 'FFA'),  self.name)

class LinkServerData(namedtuple('LinkServerData', 'code server')):
    def is_sandbox(self):
        print(self.code, self.server.mode)
        return self.server.mode == 'Sandbox' or len(self.code) == 22

def _find_server_by_ip(ip):
    for server in SERVER_LIST:
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

def _extract_code(link):
    m = re.search(r'diep.io/#(.*)', link)
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
    if len(code) not in (20, 22): return False
    return code and _is_valid_hex(code)

def read_link(link):
    if not _is_valid_party_link(link):
        return None
    code = _extract_code(link)
    is_sandbox = False
    ip = _ip_from_hex(code[:8])
    server = _find_server_by_ip(ip)
    if server is None:
        return None
    return LinkServerData(code, server)

def on_message_bot(bot):
    async def on_message(message):
        links = _extract_links(message.content)
        if not links:
            return
        link_data = list(filter(None, map(read_link, links)))
        # Prevent posting sandbox links in public chats
        # Posting links in public chats never seems to end well so I've created a guard for it
        # TODO: Create a way to re-enable this
        if any(data.is_sandbox() for data in link_data):
            await bot.delete_message(message)
            return await bot.send_message(message.channel,
                                          "Please DM your sandbox links (unless you want AC)")
        
        data_formats = [format_data(data) for data in link_data]
        if data_formats:
            pld = "**__PARTY LINK{} DETECTED!__**\n".format('s' * (len(links) != 1))
            await bot.send_message(message.channel, pld + '\n'.join(data_formats))
        
    return on_message

def setup(bot):
    bot.loop.run_until_complete(_produce_server_list())
    bot.add_listener(on_message_bot(bot), "on_message")
