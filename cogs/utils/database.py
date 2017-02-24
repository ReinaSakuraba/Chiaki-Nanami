import asyncio
import contextlib
import gzip
import json
import logging
import os
import uuid

from datetime import datetime
from .transformdict import IDAbleDict

DATA_PATH = 'data/'
DB_PATH = DATA_PATH + 'databases/'

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

@contextlib.contextmanager
def atomic_temp_file(name, path=DB_PATH, file_type=open, **kwargs):
    # For Pythonic-ness
    path += name
    check_dir(os.path.dirname(path))
    tmp_fname = f'{path}-{uuid.uuid4()}.tmp'
    with file_type(tmp_fname, **kwargs) as f:
        yield f
    os.replace(tmp_fname, path)

class Database(IDAbleDict):
    """Database for any persistent data.

    This is basically a wrapper for the defaultdict object.
    """

    # json sucks.
    # My idea was to put the actual discord objects (such as the actual server)
    # But that's not possible with json.
    # Only other way is to use str or hash, which is just a waste of
    # perfect Python dict capabilities
    # And pickle's out of the question due to security issues.
    # json sucks.
    def __init__(self, name, default_factory=None, mapping=(), **kwargs):
        super().__init__(default_factory, mapping)

        self.name = name
        # Pay no attention to this copyness
        self.loop = kwargs.pop('loop', None) or asyncio.get_event_loop()
        self.object_hook = kwargs.pop('object_hook', None)
        self.encoder = kwargs.pop('encoder', None)
        self.lock = asyncio.Lock()

        self._dumper = self._gzip_dump if kwargs.get('use_gzip', False) else self._json_dump

    def __repr__(self):
        return ("Database(name='{0.name}', default_factory={1}, "
                "object_hook={0.object_hook}, encoder={0.encoder})"
                ).format(self, getattr(self.default_factory, "__name__", None))

    def _json_dump(self):
        with atomic_temp_file(self.json_name, encoding='utf-8', mode='w') as f:
            json.dump(self, f, indent=4, sort_keys=True, separators=(',', ' : '), cls=self.encoder)

    def _gzip_dump(self):
        with atomic_temp_file(self.json_name, gzip.GzipFile, mode='w') as out:
            out.write(json.dumps(self) + '\n')

    async def dump(self):
        with await self.lock:
            await self.loop.run_in_executor(None, self._dumper)
        log.info(f"database {self.name} successfully dumped")

    @property
    def json_name(self):
        return self.name + (".json" * (not self.name.endswith(".json")))

    @classmethod
    def from_json(cls, filename, path=DB_PATH, default_factory=None, **kwargs):
        data = _load_json(path + filename, kwargs.get('object_hook'))
        return cls(filename, default_factory, mapping=data, **kwargs)

    @classmethod
    def from_gzip(cls, filename, path=DB_PATH, default_factory=None, **kwargs):
        with gzip.GzipFile(path + filename, 'r') as infile:
            data = json.load(infile)
        return cls(filename, default_factory, mapping=data, use_gzip=True, **kwargs)

def check_dir(dir_):
    os.makedirs(dir_, exist_ok=True)

def check_data_dir(dir_):
    os.makedirs(DATA_PATH + dir_, exist_ok=True)

def check_database_dir(dir_):
    os.makedirs(DB_PATH + dir_, exist_ok=True)

