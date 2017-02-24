import asyncio

async def aiterable(iterable):
    for i in iterable:
        yield i
        await asyncio.sleep(1)
        
async def acount(firstval=0, step=1):
    while True:
        yield firstval
        firstval += step

async def acountdown(firstval):
    for i in range(firstval, 0, -1):
        yield i
        await asyncio.sleep(1)