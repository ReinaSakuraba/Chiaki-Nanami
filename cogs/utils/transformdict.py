from collections import defaultdict as _defaultdict
from itertools import chain as _chain

class TransformedDict(_defaultdict):
    __slots__ = ()

    def __init__(self, default_factory=None, mapping=(), **kwargs):
        super().__init__(default_factory, self._process_args(mapping, **kwargs))

    def __getitem__(self, k):
        return super().__getitem__(self.__keytransform__(k))

    def __setitem__(self, k, v):
        return super().__setitem__(self.__keytransform__(k), v)

    def __delitem__(self, k):
        return super().__delitem__(self.__keytransform__(k))

    def __contains__(self, k):
        return super().__contains__(self.__keytransform__(k))

    def _process_args(self, mapping=(), **kwargs):
        if hasattr(mapping, "items"):
            mapping = getattr(mapping, "items")()
        return ((self.__keytransform__(k), v)
                for k, v in _chain(mapping, getattr(kwargs, "items")()))

    def get(self, k, default=None):
        return super().get(self.__keytransform__(k), default)

    def setdefault(self, k, default=None):
        return super().setdefault(self.__keytransform__(k), default)

    __marker = object()

    def pop(self, k, d=__marker):
        try:
            return super().pop(self.__keytransform__(k))
        except KeyError:
            if d is self.__marker:
                raise
            return d

    def update(self, mapping=(), **kwargs):
        super().update(self._process_args(mapping, **kwargs))

    @classmethod
    def fromkeys(cls, keys):
        return super(TransformedDict, cls).fromkeys(cls.__keytransform__(k) for k in keys)

    def __keytransform__(self, k):
        raise NotImplementedError("__keytransform__ not implemented... for some reason")

# Best used for JSONs
# Only work around as far as I know
# Because JSONs only take string keys
class StrDict(TransformedDict):
    def __keytransform__(self, k):
        return str(k)

class LowerDict(TransformedDict):
    def __keytransform__(self, k):
        return str(k).lower()

# For discord
class IDAbleDict(TransformedDict):
    def __keytransform__(self, k):
        return str(getattr(k, "id", k))
