import asyncio
import contextlib
import gzip
import json
import logging
import os
import uuid

from .misc import file_handler
from .transformdict import IDAbleDict

DATA_PATH = 'data/'
DB_PATH = DATA_PATH + 'databases/'

log = logging.getLogger(f"chiaki-{__name__}")
log.addHandler(file_handler('databases'))

def _load_data_func(file_type, **kwargs):
    def load_data(name, object_hook=None):
        try:
            with file_type(name, **kwargs) as f:
                return json.load(f, object_hook=object_hook)
        except (FileNotFoundError, json.decoder.JSONDecodeError) as e:
            return {}
    return load_data

_load_json = _load_data_func(open, encoding='utf-8')
_load_gzip = _load_data_func(gzip.GzipFile)
del _load_data_func

@contextlib.contextmanager
def atomic_temp_file(name, file_type=open, **kwargs):
    # For Pythonic-ness
    check_dir(os.path.dirname(name))
    tmp_name = f'{name}-{uuid.uuid4()}.tmp'
    with file_type(tmp_name, **kwargs) as f:
        yield f
    os.replace(tmp_name, name)

class Database(IDAbleDict):
    """Database for any persistent data.

    This is basically a wrapper for the defaultdict object, that transforms any key
    with an 'id' attribute with the actual id casted as a string.
    """

    # json sucks.
    # My idea was to put the actual discord objects (such as the actual server)
    # But that's not possible with json.
    # Only other way is to use str or hash, which is just a waste of
    # perfect Python dict capabilities
    # And pickle's out of the question due to security issues.
    # json sucks.
    def __init__(self, name, default_factory=None, *, path=DB_PATH, mapping=(), **kwargs):
        super().__init__(default_factory, mapping)

        self.name = os.path.join(path, name)
        self.loop = kwargs.pop('loop', None) or asyncio.get_event_loop()
        self._dumper, self._ext, self._loader = ((self._gzip_dump, '.gz', _load_gzip)
                                                 if kwargs.get('use_gzip', False) else
                                                 (self._json_dump, '.json', _load_json))

        # Pay no attention to this copyness
        self.object_hook = kwargs.pop('object_hook', None)
        self.encoder = kwargs.pop('encoder', None)
        self.lock = asyncio.Lock()

        if kwargs.get('load_later', False):
            self.loop.create_task(self.load_later())
        else:
            self.update(self._loader(self.file_name, self.object_hook))

    def __repr__(self):
        return ("Database(name='{0.name}', default_factory={1}, "
                "object_hook={0.object_hook}, encoder={0.encoder})"
                ).format(self, getattr(self.default_factory, "__name__", None))

    def _json_dump(self):
        with atomic_temp_file(self.file_name, encoding='utf-8', mode='w') as f:
            json.dump(self, f, indent=4, sort_keys=True, separators=(',', ' : '), cls=self.encoder)

    def _gzip_dump(self):
        with atomic_temp_file(self.file_name, gzip.GzipFile, mode='wb') as out:
            out.write(json.dumps(self).encode('utf-8') + b'\n')

    async def dump(self):
        with await self.lock:
            await self.loop.run_in_executor(None, self._dumper)
        log.info(f"database {self.name} successfully dumped")

    async def load_later(self):
        with await self.lock:
            await self.loop.run_in_executor(None, self._loader, self.file_name, self.object_hook)
            log.info(f"database {self.name} successfully loaded later")

    @property
    def file_name(self):
        return self.name + (self._ext * (not self.name.endswith(self._ext)))

def check_dir(dir_):
    os.makedirs(dir_, exist_ok=True)

def check_data_dir(dir_):
    os.makedirs(DATA_PATH + dir_, exist_ok=True)

def check_database_dir(dir_):
    os.makedirs(DB_PATH + dir_, exist_ok=True)
