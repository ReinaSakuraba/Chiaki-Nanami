import contextlib

@contextlib.contextmanager
def temp_attr(obj, attr, value):
    """Temporarily sets an object's attribute to a value"""
    already_has_attr = hasattr(obj, attr)
    old_value = getattr(obj, attr, None)
    setattr(obj, attr, value)
    try:
        yield
    finally:
        if already_has_attr:
            setattr(obj, attr, old_value)
        else:
            delattr(obj, attr)

class temp_edit:
    def __init__(self, editable, **fields):
        self.editable = editable
        self._old_fields = {k: getattr(editable, k) for k in fields}
        self._new_fields = fields

    async def __aenter__(self):
        await self.editable.edit(**self._new_fields)

    async def __aexit__(self, exc_type, exc, tb):
        await self.editable.edit(**self._old_fields)