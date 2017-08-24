import asyncio
import contextlib
import discord
import functools
import inspect
import itertools
import random

from collections import OrderedDict
from discord.ext import commands

from .context_managers import temp_message
from .misc import maybe_awaitable


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


#--------------------- Embed-related things ---------------------

class StopPagination(Exception):
    pass


def page(emoji):
    def decorator(func):
        func.__reaction_emoji__ = emoji
        return func
    return decorator

_extra_remarks = [
    'Does nothing', 
    'Does absolutely nothing', 
    'Still does nothing', 
    'Really does nothing', 
    'What did you expect',
    'Make Chiaki do a hula hoop',
    'Get slapped by Chiaki', 
    'Hug Chiaki',
    ]

class BaseReactionPaginator:
    def __init__(self, context):
        self.context = context
        self.message = None
        self.reactions_done = asyncio.Event()
        self._current = None
        self._extra = set()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._reaction_map = OrderedDict()
        for name, member in itertools.chain.from_iterable(b.__dict__.items() for b in cls.__mro__):
            if name.startswith('_'):
                continue
            # When looking at the member through the class-dict, any partialmethods 
            # are not considered callable by default. They only reveal themselves when you actually
            # get the attribute of the member through the class (eg Foo.bar),
            # or using inspect.getmembers(Foo)
            # 
            # The reason why we can't use inspect.getmembers is because it 
            # returns the members out of order, regardless of how it's defined in the class.
            # Metaclasses with __prepare__ returning an OrderedDict is not a solution,
            # because somehow inspect.getmembers disregards that as well.
            if not (callable(member) or isinstance(member, functools.partialmethod)):
                continue
            # Let sub-classes override the current methods.
            if name in cls._reaction_map.values():
                continue

            emoji = getattr(member, '__reaction_emoji__', None)
            if emoji:
                print(name)
                cls._reaction_map[emoji] = name

        # We need to move stop to the end (assuming it exists). 
        # Otherwise it will show up somewhere in the middle
        with contextlib.suppress(StopIteration):
            key = next(k for k, v in cls._reaction_map.items() if v == 'stop')
            cls._reaction_map.move_to_end(key)

    def __len__(self):
        return len(self._reaction_map)

    def default(self):
        raise NotImplementedError    

    @page('\N{BLACK SQUARE FOR STOP}')
    def stop(self):
        """Stops the interactive pagination"""
        raise StopPagination

    def _check_reaction(self, reaction, user):
        return (reaction.message.id == self.message.id 
                and user.id == self.context.author.id 
                and reaction.emoji in self._reaction_map
               )

    async def _set_message(self, destination, message):
        self._current = starting_embed = await maybe_awaitable(self.default)
        if message is None:
            self.message = await destination.send(embed=starting_embed)
        else:
            self.message = message
            await self.message.edit(embed=starting_embed)
            await message.clear_reactions()

    async def add_buttons(self):
        for emoji in self._reaction_map:
            await self.message.add_reaction(emoji)

    async def on_only_one_page(self):
        # Override this if you need custom behaviour if there's only one page
        # If you would like stop pagination, simply raise StopPagination
        await self.message.add_reaction(self.stop.__reaction_emoji__)

    async def interact(self, destination=None, *, message=None, timeout=120, delete_after=True):
        """Creates an interactive session"""
        ctx = self.context
        if destination is None:
            destination = ctx

        await self._set_message(destination, message)
        print(self.message)
        message = self.message

        try:
            # We need at least the stop button for killing the pagination
            # Otherwise it would kill the page immediately.
            if len(self) <= 1:
                await self.on_only_one_page()
            else:
                await self.add_buttons()

            self.reactions_done.set()
            while True:
                try:
                    react, user = await ctx.bot.wait_for('reaction_add', check=self._check_reaction, timeout=timeout)
                except asyncio.TimeoutError:
                    break
                else:
                    attr = self._reaction_map[react.emoji]
                    try:
                        next_ = await maybe_awaitable(getattr(self, attr))
                    except StopPagination:
                        break
                    except IndexError:
                        continue

                    if isinstance(next_, BaseReactionPaginator):
                        with contextlib.suppress(StopPagination):
                            await next_.interact(destination, message=self.message, timeout=timeout, delete_after=False)
                        # restore the old embed before we delegated
                        await self.message.edit(embed=self._current)
                        # since upon stopping, the reactions would be cleared.
                        await self.add_buttons()
                    else:
                        self._current = next_
                        await message.remove_reaction(react.emoji, user)
                        await message.edit(embed=next_)
        finally:
            if delete_after:
                await message.delete()
            else:
                await message.clear_reactions()

    async def wait_until_ready(self):
        await self.reactions_done.wait()

    @property
    def reaction_help(self):
        return '\n'.join(f'{em} => {getattr(self, f).__doc__}' for em, f in self._reaction_map.items())


class ListPaginator(BaseReactionPaginator):
    def __init__(self, context, entries, *, title=discord.Embed.Empty, 
                 color=0, colour=0, lines_per_page=15):
        super().__init__(context)
        self.entries = tuple(entries)
        self.per_page = lines_per_page
        self.colour = colour or color
        self.title = title
        self._index = 0
        self._extra = set()

    def _check_reaction(self, reaction, user):
        return (super()._check_reaction(reaction, user) 
                or (not self._extra.difference_update(self._reaction_map)
                and self._extra.add(reaction.emoji)))

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
        return -(-len(self.entries) // self.per_page)

    @property
    def color(self):
        return self.colour

    @color.setter
    def color(self, color):
        self.colour = color

    @page('\N{BLACK LEFT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}')
    def default(self):
        """Returns the first page"""
        return self[0]

    @page('\N{BLACK LEFT-POINTING TRIANGLE}')
    def previous(self):
        """Returns the previous page"""
        return self.page_at(self._index - 1)

    @page('\N{BLACK RIGHT-POINTING TRIANGLE}')
    def next(self):
        """Returns the next page"""
        return self.page_at(self._index + 1)

    @page('\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}')
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

    @page('\N{INPUT SYMBOL FOR NUMBERS}')
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

    @page('\N{INFORMATION SOURCE}')
    def help_page(self):
        """Shows this message"""
        initial_message = "This is the interactive help thing!",
        funcs = (f'{em} => {getattr(self, f).__doc__}' for em, f in self._reaction_map.items())
        extras = zip(self._extra, (random.choice(_extra_remarks) for _ in itertools.count()))
        remarks = itertools.starmap('{0} => {1}'.format, extras)

        joined = '\n'.join(itertools.chain(initial_message, funcs, remarks))

        return (discord.Embed(title=self.title, colour=self.colour, description=joined)
               .set_footer(text=f"From page {self._index + 1}")
               )

    async def add_buttons(self):
        fast_forwards = {'\U000023ed', '\U000023ee'}
        small = len(self) <= 3

        for emoji in self._reaction_map:
            # Gotta do this inefficient branch because of stop not being moved to
            # the end, so I can't just subract the two fast arrow emojis
            if not (small and emoji in fast_forwards):
                await self.message.add_reaction(emoji)

    async def interact(self, destination=None, *, message=None, timeout=120, delete_after=True):
        bot = self.context.bot
        with bot.temp_listener(self.on_reaction_remove):
            await super().interact(destination, message=message, timeout=timeout, delete_after=delete_after)

    async def on_reaction_remove(self, reaction, user):
        self._extra.discard(reaction.emoji)



class TitleBasedPages(ListPaginator):
    """Similar to EmbedPages, but takes a dict of title-content pages

    As a result, the content can easily exceed the limit of 2000 chars.
    Please use responsibly.
    """
    def __init__(self, context, entries, **kwargs):
        super().__init__(context, entries, **kwargs)
        self.entry_map = entries

    def _create_embed(self, idx, page):
        entry_title = self.entries[idx]
        return  (discord.Embed(title=entry_title, colour=self.colour, description='\n'.join(page))
                .set_author(name=self.title)
                .set_footer(text=f'Page: {idx + 1} / {len(self)} ({len(self.entries)} entries)')
                )

    def __getitem__(self, idx):
        if idx < 0:
            idx += len(self)

        self._index = idx
        page = self.entry_map[self.entries[idx]]
        return self._create_embed(idx, page)

    def __len__(self):
        return len(self.entries)


class EmbedFieldPages(ListPaginator):
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
