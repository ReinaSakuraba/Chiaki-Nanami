import asyncio
import sys

PY36 = sys.version_info >= (3, 6)

class AIterable:
    def __init__(self, iterable):
        self.aiterable = iter(iterable)

    async def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            result = next(self.aiterable)
        except StopIteration:
            raise StopAsyncIteration
        else:
            await asyncio.sleep(0)
            return result

# Python 3.6 allows async generators
if PY36:
    async def acount(firstval=0, step=1):
        while True:
            yield firstval
            firstval += step

    async def acountdown(firstval):
        for i in range(firstval, 0, -1):
            yield i
            await asyncio.sleep(1)
else:
    class acount:
        def __init__(self, firstval=0, step=1):
            self.x = firstval
            self.dx = step

        async def __aiter__(self):
            return self

        async def __anext__(self):
            self.x += self.dx
            await asyncio.sleep(0)
            return self.x

    class acountdown(acount):
        def __init__(self, limit):
            super().__init__(limit, -1)

        async def __anext__(self):
            if self.x <= 0:
                raise StopAsyncIteration
            await asyncio.sleep(1)
            return await super().__anext__()
