import asyncio
import discord
import functools
import itertools

from datetime import datetime
from discord.ext import commands

from .compat import always_iterable
from .context_managers import temp_message

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

async def iterable_say(iterable, delim='\n', *, ctx, **kwargs):
    for page in DelimPaginator.from_iterable(map(str, iterable), join_delim=delim, **kwargs):
        await ctx.send(page)

async def iterable_limit_say(iterable, delim='\n', *, ctx, limit=1000, limit_pages=3, **kwargs):
    paginator = DelimPaginator.from_iterable(map(str, iterable), join_delim=delim, **kwargs)
    destination = ctx.channel
    if paginator.total_size >= limit:
        await destination.send(f"{ctx.author.mention}, the message has been DMed to you because of the length")
        destination = ctx.author
    for _, page in itertools.takewhile(lambda pair: pair[0] != limit_pages, enumerate(paginator)):
        await destination.send(page)


class StopPagination(Exception):
    pass


class EmbedPages:
    _reaction_maps = {
            '\N{BLACK LEFT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}': 'first',
            '\N{BLACK LEFT-POINTING TRIANGLE}': 'previous',
            '\N{BLACK RIGHT-POINTING TRIANGLE}': 'next',
            '\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}': 'last',
            '\N{INPUT SYMBOL FOR NUMBERS}': 'numbered',
            '\N{BLACK SQUARE FOR STOP}': 'stop',
            '\N{INFORMATION SOURCE}': 'help_page'
    }

    def __init__(self, context, entries, *, title=discord.Embed.Empty, 
                 color=0, colour=0, lines_per_page=15):
        self.context = context
        self.entries = tuple(entries)
        self.per_page = lines_per_page
        self.colour = colour or color
        self.title = title
        self._index = 0

    def _create_embed(self, idx, page):
        # Override this if you want paginated embeds 
        # but you want to handle the pagination differently

        # XXX: Should this respect the embed description limit (2048 chars)?
        return (discord.Embed(title=self.title, colour=self.colour, description='\n'.join(page))
               .set_footer(text=f'Page: {idx + 1} / {len(self)} ({len(self.entries)} entries)')
               )

    def __getitem__(self, idx):
        if idx < 0:
            idx += len(self)

        self._index = idx
        base = idx * self.per_page
        page = self.entries[base:base + self.per_page]
        return self._create_embed(idx, page)

    def __len__(self):
        return len(self.entries) // self.per_page + 1

    @property
    def color(self):
        return self.colour

    @color.setter
    def color(self, color):
        self.colour = color

    def help_page(self):
        """Shows this message"""
        initial_message = "This is the interactive help thing!",
        funcs = (f'{em} => {getattr(self, f).__doc__}' for em, f in self._reaction_maps.items())
        joined = '\n'.join(itertools.chain(initial_message, funcs))

        return (discord.Embed(title=self.title, colour=self.colour, description=joined)
               .set_footer(text=f"From page {self._index}")
               )

    def first(self):
        """Returns the first page"""
        return self[0]

    def last(self):
        """Returns the last page"""
        return self[-1]

    def page_at(self, index):
        """Returns a page given an index.

        Unlike __getitem__, this function does bounds checking and raises
        IndexError if the index is out of bounds.
        """
        if not 0 <= index < len(self):
            raise IndexError("page index out of range")
        return self[index]

    def previous(self):
        """Returns the previous page"""
        return self.page_at(self._index - 1)

    def next(self):
        """Returns the next page"""
        return self.page_at(self._index + 1)

    def stop(self):
        """Stops the interactive pagination"""
        raise StopPagination

    async def numbered(self):
        """Takes a number from the user and goes to that page"""
        ctx = self.context
        def check(m):
            return (m.channel.id == ctx.channel.id and
                    m.author.id == ctx.author.id)
        
        async with temp_message(self.context, f'Please enter a number from 1 to {len(self)}'):
            while True:
                try:
                    result = await ctx.bot.wait_for('message', check=check, timeout=60)
                except asyncio.TimeoutError:
                    return self[self._index]

                try:
                    result = int(result.content)
                except ValueError:
                    continue
                
                try:
                    return self.page_at(result - 1)
                except IndexError:
                    continue

    async def interact(self, destination=None, *, start=0):
        """Creates an interactive session"""
        ctx = self.context
        if destination is None:
            destination = ctx

        def react_check(reaction, user):    
            return user.id == ctx.author.id and reaction.emoji in self._reaction_maps

        message = await destination.send(embed=self[start])
        # No need to put reactions if there's only one page.
        if len(self) != 1:
            for emoji in self._reaction_maps:
                await asyncio.sleep(0.25)
                await message.add_reaction(emoji)

        while True:
            try:
                react, user = await ctx.bot.wait_for('reaction_add', check=react_check, timeout=120.0)
            except asyncio.TimeoutError:
                break
            else:
                attr = self._reaction_maps[react.emoji]
                try:
                    next_embed = await discord.utils.maybe_coroutine(getattr(self, attr))
                except StopPagination:
                    break
                except IndexError:
                    continue

                await message.remove_reaction(react.emoji, user)
                await message.edit(embed=next_embed)

        await message.clear_reactions()

class EmbedFieldPages(EmbedPages):
    """Similat to EmbedPages, but uses the fields instead of the description"""
    def __init__(self, context, entries, *, 
                description=discord.Embed.Empty, inline=True, **kwargs):
        super().__init__(context, entries, **kwargs)

        self.description = description
        self.inline = inline
        if self.per_page > 25:
            raise ValueError("too many fields per page (maximum 25)")

    def _create_embed(self, idx, page):
        embed = (discord.Embed(title=self.title, colour=self.colour, description=self.description)
                .set_footer(text=f'Page: {idx + 1} / {len(self)} ({len(self.entries)} entries)')
                )

        add_field = functools.partial(embed.add_field, inline=self.inline)
        for name, value in page:
            add_field(name=name, value=value)
        return embed