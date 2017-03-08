import contextlib

_sentinel = object()

@contextlib.contextmanager
def temp_attr(obj, attr, value):
    """Temporarily sets an object's attribute to a value"""
    old_value = getattr(obj, attr, _sentinel)
    setattr(obj, attr, value)
    try:
        yield
    finally:
        if old_value is _sentinel:
            delattr(obj, attr)
        else:
            setattr(obj, attr, old_value)

class temp_edit:
    def __init__(self, editable, **fields):
        self.editable = editable
        self._old_fields = {k: getattr(editable, k) for k in fields}
        self._new_fields = fields

    async def __aenter__(self):
        await self.editable.edit(**self._new_fields)

    async def __aexit__(self, exc_type, exc, tb):
        await self.editable.edit(**self._old_fields)