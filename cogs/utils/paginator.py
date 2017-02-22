from discord.ext import commands

class DelimPaginator(commands.Paginator):
    def __init__(self, prefix='```', suffix='```', max_size=2000, join_delim='\n', **kwargs):
        super().__init__(prefix, suffix, max_size)
        self.escape_code = kwargs.get('escape_code', False)
        self.join_delim = join_delim

    def __len__(self):
        return len(self.pages)

    def __getitem__(self, x):
        return self.pages[x]

    def add_line(self, line, escape_code=False):
        line = line.replace('`', '\u200b`') if self.escape_code else line
        super().add_line(line)

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

    @property
    def total_size(self):
        return sum(map(len, self))

async def iterable_say(delim, iterable, bot, **kwargs):
    for page in DelimPaginator.from_iterable(map(str, iterable), join_delim=delim, **kwargs):
        await bot.say(page)

async def iterable_limit_say(iterable, delim='\n', *, bot, ctx, limit=1000, **kwargs):
    paginator = DelimPaginator.from_iterable(map(str, iterable), join_delim=delim, **kwargs)
    destination = ctx.message.channel
    if paginator.total_size >= limit:
        await bot.reply("The message has been DMed to you because of the length")
        destination = ctx.message.author
    for page in paginator:
        await bot.send_message(destination, page)
