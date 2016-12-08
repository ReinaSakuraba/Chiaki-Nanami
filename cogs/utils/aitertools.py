import asyncio

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

class ACount:
    def __init__(self, firstval=0, step=1):
        self.x = firstval
        self.dx = step

    async def __aiter__(self):
        return self

    async def __anext__(self):
        self.x += self.dx
        await asyncio.sleep(0)
        return self.x
    
class ACountdown(ACount):
    def __init__(self, limit):
        super().__init__(limit, -1)

    async def __anext__(self):
        if self.x <= 0:
            raise StopAsyncIteration
        await asyncio.sleep(1)
        return await super().__anext__()
