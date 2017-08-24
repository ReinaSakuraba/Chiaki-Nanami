import asyncio
import contextlib
import discord
import enum
import itertools
import random
import textwrap
import time

from datetime import datetime
from discord.ext import commands
from string import ascii_lowercase, ascii_uppercase

from .manager import SessionManager

from ..utils.converter import ranged
from ..utils.misc import REGIONAL_INDICATORS, duration_units
from ..utils.paginator import BaseReactionPaginator, page


class MinesweeperException(Exception):
    pass


class HitMine(MinesweeperException):
    def __init__(self, x, y):
        self.point = x, y
        super().__init__(f'hit a mine on {x + 1} {y + 1}')


class Level(enum.Enum):
    beginner = enum.auto()
    intermediate = enum.auto()
    expert = enum.auto()
    custom = enum.auto()

    def __str__(self):
        return self.name.title()

    @classmethod
    async def convert(cls, ctx, arg):
        lowered = arg.lower()
        try:
            return cls[lowered]
        except KeyError:
            raise commands.BadArgument(f'No level called {arg}.') from None

class FlagType(enum.Enum):
    default = None
    f = 'flag'
    flag = 'flag'
    u = 'unsure'
    unsure = 'unsure'


class Tile(enum.Enum):
    blank = '\N{WHITE LARGE SQUARE}'
    flag = '\N{TRIANGULAR FLAG ON POST}'
    mine = '\N{EIGHT POINTED BLACK STAR}'
    shown = '\N{BLACK LARGE SQUARE}'
    unsure = '\N{BLACK QUESTION MARK ORNAMENT}'
    boom = '\N{COLLISION SYMBOL}'

    def __str__(self):
        return self.value

    @staticmethod
    def numbered(number):
        return f'{number}\U000020e3'


SURROUNDING = ((-1, -1), (-1,  0), (-1,  1),
               (0 , -1),           (0 ,  1),
               (1 , -1), (1 ,  0), (1 ,  1))


class Board:
    def __init__(self, width, height, mines):
        if mines >= width * height:
            raise ValueError(f'Too many mines (expected max {width * height}, got {mines})')
        if mines <= 0:
            raise ValueError("A least one mine is required")

        self._mine_count = mines
        
        self._board = [[Tile.blank] * width for _ in range(height)]
        self.visible = set()
        self.flags = set()
        self.unsures = set()
        self.mines = set()

    def __contains__(self, xy):
        return 0 <= xy[0] < self.width and 0 <= xy[1] < self.height

    def __repr__(self):
        return f'{type(self).__name__}({self.width}, {self.height}, {len(self.mines)})'

    def __str__(self):
        padding = len(str(self.width - 1))
        numbers = ''.join(map(str, range(self.height)))
        board_string = ''# f"Mines: {len(self.mines)}\n"#  {numbers :>{padding + 1}}\n"
        board_string += '\n'.join([f"{char} {' '.join(map(str, cells))}"
                                   for char, cells in zip(REGIONAL_INDICATORS, self._board)])
        # print(len(board_string))
        # board_string += f"\n  {numbers}"
        return board_string

    def _place_mines_from(self, x, y):
        surrounding = set(self._get_neighbours(x, y))
        click_area = surrounding | {(x, y)}

        possible_coords = itertools.product(range(self.width), range(self.height))
        coords = [p for p in possible_coords if p not in click_area]

        self.mines = set(random.sample(coords, k=min(self._mine_count, len(coords))))
        self.mines.update(random.sample(surrounding, self._mine_count - len(self.mines)))

        # All mines should be exhausted, unless we somehow made a malformed board.
        assert len(self.mines) == self._mine_count, f"only {len(self.mines)} mines were placed"

    def is_mine(self, x, y):
        return (x, y) in self.mines

    def is_flag(self, x, y):
        return (x, y) in self.flags

    def is_visible(self, x, y):
        return (x, y) in self.visible

    def is_unsure(self, x, y):
        return (x, y) in self.unsures

    def _get_neighbours(self, x, y):
        pairs = ((x + surr_x, y + surr_y) for (surr_x, surr_y) in SURROUNDING)
        return (p for p in pairs if p in self)

    def show(self, x, y):
        if not self.mines:
            self._place_mines_from(x, y)

        if self.is_visible(x, y):
            return

        self.visible.add((x, y))
        if self.is_mine(x, y) and not self.is_flag(x, y):
            raise HitMine(x, y)

        surrounding = sum(self.is_mine(nx, ny) for nx, ny in self._get_neighbours(x, y))
        if not surrounding:
            self._board[y][x] = Tile.shown
            for nx, ny in self._get_neighbours(x, y):
                self.show(nx, ny)
        else:
            self._board[y][x] = Tile.numbered(surrounding)

    def _modify_board(self, x, y, attr):
        if self.is_visible(x, y):
            return

        tup = x, y
        was_thing = getattr(self, f'is_{attr}')(x, y)
        for thing in ('flags', 'unsures'):
            getattr(self, thing).discard(tup)

        if was_thing:
            self._board[y][x] = Tile.blank
        else:
            getattr(self, f'{attr}s').add(tup)
            self._board[y][x] = getattr(Tile, attr)

    def flag(self, x, y):
        self._modify_board(x, y, 'flag')

    def unsure(self, x, y):
        self._modify_board(x, y, 'unsure')

    def reveal_mines(self, success=False):
        tile = Tile.flag if success else Tile.boom
        for mx, my in self.mines:
            self._board[my][mx] = tile

    def hide_mines(self):
        for mx, my in self.mines:
            self._board[my][mx] = Tile.blank

    def explode(self, x, y):
        if not self.is_visible(x, y):
            return
        self._board[y][x] = Tile.boom

    def is_solved(self):
        return len(self.visible) + len(self.mines) == self.width * self.height

    @property
    def width(self):
        return len(self._board[0])

    @property
    def height(self):
        return len(self._board)

    @property
    def mine_count(self):
        return len(self.mines) or self._mine_count

    @property
    def mines_marked(self):
        return len(self.flags)

    @property
    def remaining_flags(self):
        return self.mine_count - self.mines_marked

    @property
    def remaining_mines(self):
        return len(self.mines - self.flags)

    @classmethod
    def beginner(cls):
        """Returns a beginner minesweeper board"""
        return cls(9, 9, 10)

    @classmethod
    def intermediate(cls):
        """Returns a intermediate minesweeper board"""
        return cls(12, 12, 20)

    @classmethod
    def expert(cls):
        """Returns an expert minesweeper board"""
        return cls(13, 13, 40)


class MinesweeperDisplay(BaseReactionPaginator):
    class State(enum.Enum):
        GAME = enum.auto()
        HELP = enum.auto()

    def __init__(self, context, game):
        super().__init__(context)
        context.game_stopped = False
        self.state = None
        self.game = game

    def _board_repr(self):
        top_row = ' '.join(REGIONAL_INDICATORS[:self.board.width])
        # Discord strips any leading and trailing spaces.
        # By putting a zero-width space we bypass that
        return f'\N{BLACK LARGE SQUARE} {top_row}\n{self.board}' 

    @staticmethod
    def _possible_spaces():
        number = random.randint(1, 9)
        return textwrap.dedent(f'''
        {Tile.shown} - Empty tile, reveals other empty or numbered tiles near it

        {Tile.numbered(number)} - Displays the number of mines surrounding it.
        This one shows that they are {number} mines around it.

        {Tile.boom} - BOOM! Selecting a mine makes it explode, causing all other mines to explode 
        and thus ending the game. Avoid mines at any costs!
        \u200b
        ''')

    @property
    def board(self):
        return self.game.board

    @page('\N{INPUT SYMBOL FOR NUMBERS}')
    def default(self):
        """Returns you to the game"""
        self.state = self.State.GAME
        board = self.board
        return (discord.Embed(colour=self.context.bot.colour, description=self._board_repr())
               .set_author(name=f'Minesweeper - {board.width} x {board.height}')
               .add_field(name='Player', value=self.context.author)
               .add_field(name='Mines Marked', value=f'{board.mines_marked} / {board.mine_count}')
               .add_field(name='Flags Remaining', value=board.remaining_flags)
               .add_field(name='\u200b', value='Stuck? Click the \N{INFORMATION SOURCE} reaction for some help.')
               )

    @page('\N{INFORMATION SOURCE}')
    def help_page(self):
        """Shows this page"""
        self.state = self.State.HELP
        text = textwrap.dedent(f'''
        Basically the goal is to reveal all of the board and NOT get hit with a mine!

        To make a move, send a message in this format:
        ```
        <column> <row> [f|flag|u|unsure]
        ```
        Column must be from **A-{ascii_lowercase[self.board.width - 1].upper()}**
        And row must be from **A-{ascii_lowercase[self.board.height - 1].upper()}**
        Typing `f` or `flag` will mark the tile with a flag.
        Typing `u` or `unsure` will mark the tile as unsure.
        Typing nothing, well you know what it will do.

        You **do not** need to include the `<>` or `[]`.

        Note that you can only input it if you're in this actual game.
        (ie typing anything in this screen won't do anything.)
        \u200b
        ''')

        reaction_text = '\n'.join(f'{em} => {getattr(self, f).__doc__}' 
                                  for em, f in self._reaction_map.items())
        return (discord.Embed(colour=self.context.bot.colour, description=text)
               .set_author(name='Welcome to Minesweeper!')
               .add_field(name='If you select a tile, chances are you will hit one of these 3 things', value=self._possible_spaces())
               .add_field(name='Reaction Buttons', value=reaction_text)
               )

    @page('\N{BLACK SQUARE FOR STOP}')
    def stop(self):
        """Stops the game"""
        self.game.stop()
        return super().stop()


class MinesweeperSession:
    def __init__(self, ctx, board):
        self.board = board
        self.ctx = ctx
        self._interaction = None
        self._runner = None
        self._game_screen = MinesweeperDisplay(ctx, self)

    def check_message(self, message):
        if self._game_screen.state != MinesweeperDisplay.State.GAME:
            return False

        return (message.channel == self.ctx.channel and
                message.author == self.ctx.author)

    def parse_message(self, content):
        splitted = content.lower().split()
        chars = len(splitted)

        if chars == 2:
            flag = FlagType.default
        elif chars == 3:
            flag = getattr(FlagType, splitted[2].lower(), FlagType.default)
        else:
            return None

        try:
            x, y = map(ascii_lowercase.index, splitted[:2])
        except ValueError:
            return None
        else: 
            if (x, y) not in self.board:
                return None
            return x, y, flag

    async def edit_board(self, new_colour=None):
        embed = self._game_screen.default()
        if new_colour is not None:
            embed.colour = new_colour

            if not new_colour:
                embed.set_author(name='Minesweeper stopped.')
        
        await self._game_screen.message.edit(embed=embed)

    async def _loop(self):
        start = time.perf_counter() 
        while True:
            colour = None
            try:
                message = await self.ctx.bot.wait_for('message', timeout=120, check=self.check_message)
            except asyncio.TimeoutError:
                await self.ctx.send(f'{self.ctx.author.mention} You took too long!')
                break

            parsed = self.parse_message(message.content)
            if parsed is None:      # garbage input, ignore.
                continue
            x, y, thing = parsed
            with contextlib.suppress(discord.NotFound):
                await message.delete()

            try:
                if thing.value:
                    getattr(self.board, thing.value)(x, y)
                else:
                    self.board.show(x, y)
            except HitMine:
                self.board.explode(x, y)
                await self.edit_board(0xFFFF00)
                await asyncio.sleep(random.uniform(0.5, 1))
                self.board.reveal_mines()
                colour = 0xFF0000
                raise
            except Exception as e:
                await self.ctx.send(f'An error happened.\n```\y\n{type(e).__name__}: {e}```')
                raise
            else:
                if self.board.is_solved():
                    colour = 0x00FF00
                    self.board.reveal_mines(success=True)
                    return time.perf_counter() - start
            finally:
                await self.edit_board(colour)

    async def run_loop(self): 
        try:
           return await self._loop()
        except asyncio.CancelledError:
            await self.edit_board(0)
            raise
        return None

    async def run(self):
        self._interaction = asyncio.ensure_future(self._game_screen.interact(timeout=None, delete_after=False))
        self._runner = asyncio.ensure_future(self.run_loop())
        await self._game_screen.wait_until_ready()
        try:
            return await self._runner
        finally:
            self._interaction.cancel()
       
    def stop(self):
        for task in (self._runner, self._interaction):
            with contextlib.suppress(BaseException):
                task.cancel()


class Minesweeper:
    def __init__(self, bot):
        self.bot = bot
        self.manager_bucket = {level: SessionManager() for level in Level}
        # self.leaderboard = Database('minesweeperlb.json')

    async def _do_minesweeper(self, ctx, level, board, *, record_time=True):
        manager = self.manager_bucket[level]
        session = manager.get_session(ctx.author.id)
        if session is not None:
            return await ctx.send(f'You already have a {level} Minesweeper game '
                                  f'in {session.ctx.channel} from {session.ctx.guild}')

        await ctx.send(f'Starting a {level} minesweeper game...')
        with manager.temp_session(ctx.author.id, MinesweeperSession(ctx, board)) as inst:
            time = await inst.run()
            if time is None:
                return

            rounded = round(time, 2)
            text = f'You beat game in {duration_units(rounded)}.'
            win_embed = (discord.Embed(title='A winner is you!', colour=0x00FF00, timestamp=datetime.utcnow(), description=text)
                        .set_thumbnail(url=ctx.author.avatar_url)
                        )

            await ctx.send(embed=win_embed)

    @commands.group(aliases=['msw'], invoke_without_command=True)
    async def minesweeper(self, ctx, level: Level=Level.beginner):
        board = getattr(Board, str(level).lower())()
        """Starts a game of Minesweeper."""
        await self._do_minesweeper(ctx, level, board)

    @minesweeper.command(name='custom')
    async def minesweeper_custom(self, ctx, width: ranged(3, 20), height: ranged(3, 20), mines: int):
        """Starts a custom minesweeper game."""
        if not 9 <= width * height <= 170:
            raise ValueError("Can't have a board of that size due to emoji bugs sorry ;-;")
        board = Board(width, height, mines)
        await self._do_minesweeper(ctx, Level.custom, board, record_time=False)

    @minesweeper.error
    @minesweeper_custom.error
    async def minesweeper_error(self, ctx, error):
        cause = error.__cause__

        if isinstance(cause, ValueError):
            await ctx.send(cause)
        if isinstance(cause, HitMine):
            x, y = cause.point
            await ctx.send(f'You hit a mine on {ascii_uppercase[x]} {ascii_uppercase[y]}... ;-;')
        if isinstance(cause, asyncio.CancelledError):
            await ctx.send(f'Ok, cya later...')

    @minesweeper.command(name='stop')
    async def minesweeper_stop(self, ctx, level: Level):
        """Stops a currently running minesweeper game.

        Ideally, you should not have to call this, because the game already 
        has a stop button in place.
        """
        manager = self.manager_bucket[level]
        session = manager.get_session(ctx.author.id)
        if session is None:
            return await ctx.send("You don't have a {level} minesweeper running...")

        session.stop()

    @minesweeper.command(name='leaderboard', aliases=['lb'])
    async def minesweeper_leaderboard(self, ctx, level: Level):
        pass

    @minesweeper.command(name='rank')
    async def minesweeper_rank(self, ctx, level: Level):
        pass

def setup(bot):
    bot.add_cog(Minesweeper(bot))
