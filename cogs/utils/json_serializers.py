import discord
import json

from collections import deque
from datetime import datetime

class DequeEncoder(json.JSONEncoder):
    def default(self, o):
        if type(o) is deque:
            return {
                '__type__': type(o).__name__,
                'deque': list(o)
            }
        return super().default(o)

class DatetimeEncoder(json.JSONEncoder):
    def default(self, o):
        if type(o) is datetime:
            return {
                '__type__': type(o).__name__,
                'timestamp': o.timestamp()
            }
        return super().default(o)

class SnowflakeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, discord.abc.Snowflake):
            return o.id
        return super().default(o)

def decode_datetime(d):
    if d.get('__type__') == 'datetime':
        return datetime.fromtimestamp(d['timestamp'])
    return d

def union_decoder(*decoders):
    def actual_decoder(d):
        for decoder in decoders:
            result = decoder(d)
            if result is not d:
                return result
        return d
    return actual_decoder
