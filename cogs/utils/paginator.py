from discord.ext import commands

class DelimPaginator(commands.Paginator):
    def __init__(self, prefix='```', suffix='```', max_size=2000, join_delim='\n'):
        super().__init__(prefix, suffix, max_size)
        self.join_delim = join_delim

    def __getitem__(self, x):
        return self.pages[x]
        
    def __iter__(self):
        return iter(self.pages)
        
    def close_page(self):
        """Prematurely terminate a page."""
        self._current_page.append(self.suffix)
        prefix, *rest, suffix = self._current_page
        self._pages.append(f"{prefix}{self.join_delim.join(rest)}{suffix}")
        self._current_page = [self.prefix]
        self._count = len(self.prefix) + 1 # prefix + newline
        
    @classmethod
    def from_iterable(cls, iterable, **kwargs):
        paginator = cls(**kwargs)
        for i in iterable:
            paginator.add_line(i)
        return paginator
          
async def iterable_say(delim, iterable, bot, **kwargs):
    paginator = DelimPaginator(join_delim=delim, **kwargs)
    for role in map(str, iterable):
        paginator.add_line(role)
    for page in paginator:
        await bot.say(page)
