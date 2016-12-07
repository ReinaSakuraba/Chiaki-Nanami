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
def _servers_list():
    async with aiohttp.get(SERVERS_URL) as response:
        return _pairwise(response.text().split('\x00'))

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
        m = re.search(r'(.*):', self.ip_port)
        return m.group(1)

    @property
    def port(self):
        m = re.search(r':(.*)', self.ip_port)
        return m.group(1)

    @property
    def location(self):
        m = re.search(r':(.*):', self.name)
        return self.name.replace(m.group(1), '')
    
    @property
    def mode(self):
        m = re.search(r':(.*):', self.name)
        return self._translations.get(m.group(1), 'FFA')

SERVER_LIST = [DiepioServer(*s) for s in _servers_list()]
del _servers_list

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
    print(server)
    return ("Code: {0}\n"
            "IP: {1.ip}\n"
            "Location: {1.location}\n"
            "Mode: {1.mode}\n"
            ).format(code, server)
