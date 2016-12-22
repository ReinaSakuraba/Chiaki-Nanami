import discord
import json
import logging
import os, os.path
import random
import re
import traceback

from .transformdict import IDAbleDict

DATA_PATH = 'data/'
DB_PATH = DATA_PATH + 'databases/'
TEMP_FILE_NUM_PADDING = 8

def _load_json(name):
    try:
        with open(name, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.decoder.JSONDecodeError) as e:
        return {}

def _dump_json(name, data):
    with open(name, encoding='utf-8', mode="w") as f:
        json.dump(data, f, indent=4, sort_keys=True,
            separators=(',', ' : '))
    
class Database(IDAbleDict):
    # json sucks.
    # My idea was to put the actual discord objects (such as the actual server)
    # But that's not possible with json.
    # Only other way is to use str or hash, which is just a waste of
    # perfect Python dict capabilities
    # And pickle's out of the question due to security issues.
    # json sucks.
    def __init__(self, name, factory_not_top_tier=None, mapping=()):
        self.name = name
        super().__init__(factory_not_top_tier, mapping)
        self.logger = logging.getLogger("nanami_data")
    
    def dump(self, name=None, path=DB_PATH):
        if name is None:
            name = self.name
        name = path + name
        rnd = str(random.randrange(10 ** TEMP_FILE_NUM_PADDING))
        tmp_fname = "{}-{}.tmp".format(name, rnd.zfill(TEMP_FILE_NUM_PADDING))
        _dump_json(tmp_fname, self)
        try:
            _load_json(tmp_fname)
        except json.decoder.JSONDecodeError:
            self.logger.exception("Attempted to write file {} but JSON "
                                  "integrity check on temp file has failed. "
                                  "The original file is unaltered."
                                  "".format(filename))
            return False
        os.replace(tmp_fname, name + ".json")
        return True

    @discord.utils.deprecated("db.get(id)")
    def get_storage(self, id_ : str):
        return self.get(id_)
        
    @classmethod
    def from_json(cls, filename, path=DB_PATH, factory_not_top_tier=None):
        data = _load_json(path + filename)
        name = os.path.splitext(filename)[0]
        return cls(name, factory_not_top_tier, data)

def check_data_dir(dir_):
    os.makedirs(DATA_PATH + dir_, exist_ok=True)
  
def check_database_dir(dir_):
    os.makedirs(DB_PATH + dir_, exist_ok=True)
    
