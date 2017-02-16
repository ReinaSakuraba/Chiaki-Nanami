import asyncio
import json
import logging
import os
import uuid

from datetime import datetime
from .transformdict import IDAbleDict

DATA_PATH = 'data/'
DB_PATH = DATA_PATH + 'databases/'
TEMP_FILE_NUM_PADDING = 8

def _load_json(name, object_hook=None):
    try:
        with open(name, encoding='utf-8') as f:
            return json.load(f, object_hook=object_hook)
    except (FileNotFoundError, json.decoder.JSONDecodeError) as e:
        return {}
        
log = logging.getLogger(f"chiaki-{__name__}")
try:
    handler = logging.FileHandler(filename='./logs/databases.log', encoding='utf-8', mode='w')
except FileNotFoundError:
    os.makedirs("logs", exist_ok=True)
    handler = logging.FileHandler(filename='./logs/databases.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s/%(levelname)s:%(name)s: %(message)s'))
log.addHandler(handler)

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
        # Pay no attention to this copyness
        self.loop = kwargs.pop('loop', None) or asyncio.get_event_loop()
        self.object_hook = kwargs.pop('object_hook', None)
        self.encoder = kwargs.pop('encoder', None)
        self.lock = asyncio.Lock()

    def __repr__(self):
        return ("Database(name='{0.name}', default_factory={1}, "
                "object_hook={0.object_hook}, encoder={0.encoder})"
                ).format(self, getattr(self.default_factory, "__name__", None))

    def _dump(self, path=DB_PATH):
        name = path + self.name
        check_dir(os.path.dirname(name))
        tmp_fname = f'{name}-{uuid.uuid4()}.tmp'
        with open(tmp_fname, encoding='utf-8', mode="w") as f:
            json.dump(self, f, indent=4, sort_keys=True,
                separators=(',', ' : '), cls=self.encoder)

        try:
            _load_json(tmp_fname)
        except json.decoder.JSONDecodeError:
            self.logger.exception("Attempted to write file {} but JSON "
                                  "integrity check on temp file has failed. "
                                  "The original file is unaltered."
                                  "".format(filename))
            return False
        os.replace(tmp_fname, name + (".json" * (not name.endswith(".json"))))
        return True

    async def dump(self, path=DB_PATH):
        with await self.lock:
            await self.loop.run_in_executor(None, self._dump, path)
        log.info(f"database {self.name} successfully dumped")

    @classmethod
    def from_json(cls, filename, path=DB_PATH, default_factory=None, **kwargs):
        data = _load_json(path + filename, kwargs.get('object_hook'))
        return cls(filename, default_factory, data, **kwargs)

def check_dir(dir_):
    os.makedirs(dir_, exist_ok=True)

def check_data_dir(dir_):
    os.makedirs(DATA_PATH + dir_, exist_ok=True)

def check_database_dir(dir_):
    os.makedirs(DB_PATH + dir_, exist_ok=True)

