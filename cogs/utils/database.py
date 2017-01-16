import discord
import json
import logging
import os, os.path
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
class Database(IDAbleDict):
    # json sucks.
    # My idea was to put the actual discord objects (such as the actual server)
    # But that's not possible with json.
    # Only other way is to use str or hash, which is just a waste of
    # perfect Python dict capabilities
    # And pickle's out of the question due to security issues.
    # json sucks.
    def __init__(self, name, default_factory=None, mapping=(), **kwargs):
        self.name = name
        super().__init__(default_factory, mapping)
        self.logger = logging.getLogger("nanami_data")
        # Pay no attention to this copyness
        self.object_hook = kwargs.pop('object_hook', None)
        self.encoder = kwargs.pop('encoder', None)
        self.lock = asyncio.Lock()
        
    def __repr__(self):
        return ("Database(name={0.name}, default_factory={0.default_factory},\n"
                "object_hook={0.object_hook}, encoder={0.encoder})").format(self)
    
    def _dump(self, path=DB_PATH):
        name = path + self.name
        tmp_fname = f'{name}-{uuid.uuid4()}.tmp'
        with open(name, encoding='utf-8', mode="w") as f:
            json.dump(data, f, indent=4, sort_keys=True,
                separators=(',', ' : '), object_hook=self.object_hook)
    
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
    
    async def dump(self, path=DB_PATH):
        with await self.lock:
            await self.loop.run_in_executor(None, self._dump, path)

    @discord.utils.deprecated("db.get(id)")
    def get_storage(self, id_ : str):
        return self.get(id_)
        
    @classmethod
    def from_json(cls, filename, path=DB_PATH, default_factory=None):
        data = _load_json(path + filename)
        return cls(filename, default_factory, data)

def check_data_dir(dir_):
    os.makedirs(DATA_PATH + dir_, exist_ok=True)
  
def check_database_dir(dir_):
    os.makedirs(DB_PATH + dir_, exist_ok=True)
    
