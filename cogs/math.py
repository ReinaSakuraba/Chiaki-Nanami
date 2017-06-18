import discord
import functools
import inspect
import itertools
import math
import operator
import random
import re

from collections import defaultdict, namedtuple, OrderedDict
from collections.abc import Sequence
from discord.ext import commands
from random import randrange

from .utils.converter import item_converter, union
from .utils.database import Database
from .utils.errors import InvalidUserArgument
from .utils.paginator import BaseReactionPaginator, page
from .utils.vector import Vector

try:
    import sympy
except ImportError:
    sympy = None
else:
    from sympy.parsing.sympy_parser import (
        parse_expr as parse_sympy_expr, 
        standard_transformations, implicit_multiplication_application
    )
    default_transformations = standard_transformations + (implicit_multiplication_application,)

def _get_context(obj):
    return {attr: func for attr, func in inspect.getmembers(obj) if not attr.startswith('_')}

MATH_CONTEXT = _get_context(math)
def sec(x): return 1 / math.cos(x)
def csc(x): return 1 / math.sin(x)
def cot(x): return 1 / math.tan(x)
def sign(x): return (x > 0) - (x < 0)
MATH_CONTEXT.update(ln=math.log, arcsin=math.asin, arccos=math.acos, arctan=math.atan,
                    sec=sec, secant=sec, csc=csc, cosecant=csc, cot=cot, cotangent=cot,
                    abs=abs, min=min, max=max, divmod=divmod, round=round, sign=sign,
                    random=random.random, randrange=random.randrange,
                    __builtins__=None
                    )
del sec, csc, cot, sign
OTHER_OPS = {'and', 'or', 'not', }

def _sanitize_func(pat, ctx, sanity_check):
    def sanitize(fn_str):
        words = re.split(pat, fn_str)
        for token in words:
            if not sanity_check(token):
                raise ValueError(f"Unrecognized token: {token}")
        return eval("lambda: " + fn_str, ctx)
    return sanitize

def _is_sane_func(ctx):
    def is_sane(token):
        if not token:
            return True
        elif token == '__builtins__':
            return False
        return token in ctx
    return is_sane

_sanitize = _sanitize_func(r"[0-9.+\-*/^&|<>, ()=]+", MATH_CONTEXT, _is_sane_func(set(MATH_CONTEXT) | OTHER_OPS))

#-----------Vectors-----------

VECTOR_CONTEXT = _get_context(Vector)
VECTOR_CONTEXT.update(Vector=Vector, abs=abs, bool=bool, degrees=math.degrees, __builtins__=None)
_vector_sanitize = _sanitize_func(r"[0-9, +-/*()]+", VECTOR_CONTEXT, _is_sane_func(VECTOR_CONTEXT))

#-----------Primes-----------

# Miller-Rabin primality test written by Gareth Rees
# Wow I use a lot of his code
# http://stackoverflow.com/a/14616936
_small_primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31] # etc.

def _probably_prime(n, k):
    """Return True if n passes k rounds of the Miller-Rabin primality
    test (and is probably prime). Return False if n is proved to be
    composite.

    """
    if n < 2: return False
    for p in _small_primes:
        if n < p * p: return True
        if n % p == 0: return False
    r, s = 0, n - 1
    while s % 2 == 0:
        r += 1
        s //= 2
    for _ in range(k):
        a = randrange(2, n - 1)
        x = pow(a, s, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True

#-----------Unit Conversions-----------

class IncompatibleUnits(Exception):
    pass

Unit = namedtuple('Unit', ['type', 'ratio', 'intercept'])
Unit.__new__.__defaults__ = (0, )
_length = functools.partial(Unit, 'Length')
_mass   = functools.partial(Unit, 'Mass')
_bit    = functools.partial(Unit, 'Data')
_time   = functools.partial(Unit, 'Time')
_temp   = functools.partial(Unit, 'Temperature')

_milli = 1 / 1_000
_nano  = 1 / 1_000_000_000
_pico  = 1 / 1_000_000_000_000
_femto = 1 / 1_000_000_000_000_000
_units = {
    # Lengths
    'pc' : _length(3.085677581e16),        'parsec'           : _length(3.085677581e16),
    'ly' : _length(9_460_730_472_580_800), 'light year'       : _length(9_460_730_472_580_800),
    'au' : _length(149_597_870_700),       'astronomical unit': _length(149_597_870_700),
    'mi' : _length(1609.44),               'mile'      : _length(1609.44),
    'km' : _length(1000),                  'kilometre' : _length(1000),     'kilometer' : _length(1000),
    'hm' : _length(100),                   'hectometre': _length(100),      'hectometer': _length(100),
    'dam': _length(10),                    'decametre' : _length(10),       'decameter' : _length(10),
                                           'fathom'    : _length(1.8288),
    'm'  : _length(1),                     'metre'     : _length(1),        'meter'     : _length(1),
    'yd' : _length(0.9144),                'yard'      : _length(0.9144),
    'ft' : _length(0.304801),              'foot'      : _length(0.304801),
    'in' : _length(0.0254),                'inch'      : _length(0.0254),
    'dm' : _length(0.1),                   'decimetre' : _length(0.1),      'decimeter' : _length(0.1),
    'cm' : _length(0.01),                  'centimetre': _length(0.01),     'centimeter': _length(0.01),
    'mm' : _length(_milli),                'millimetre': _length(_milli),   'millimeter': _length(_milli),
    'nm' : _length(_nano),                 'nanometre' : _length(_nano),    'nanometer' : _length(_nano),
    'pm' : _length(_pico),                 'picometre' : _length(_pico),    'picometer' : _length(_pico),
    'fm' : _length(_femto),                'femtometre': _length(_femto),   'femtometer': _length(_femto),

    # Mass
    'kg'   : _mass(1000),        'kilogram' : _mass(1000),
    'lb'   : _mass(1/0.002_205), 'pound'    : _mass(1/0.002_205),
    'troy' : _mass(1/0.002_679),
    'hg'   : _mass(100),         'hectogram': _mass(100),
    'dag'  : _mass(10),          'decagram' : _mass(10),
    'g'    : _mass(1),           'gram'     : _mass(1),
    'carat': _mass(1/5),
    'mg'   : _mass(_milli),      'milligram': _mass(_milli),
    'ng'   : _mass(_nano),       'nanogram' : _mass(_nano),
    'fg'   : _mass(_femto),      'femtogram': _mass(_femto),

    # Data (bits and bytes)
    'bit'  : _bit(1),
    'byte' : _bit(8),
    'Kb'   : _bit(1 << 10),  'kilobit' : _bit(1 << 10),
    'KB'   : _bit(1 << 13),  'kilobyte': _bit(1 << 13),
    'Mb'   : _bit(1 << 20),  'megabit' : _bit(1 << 20),
    'MB'   : _bit(1 << 23),  'megabyte': _bit(1 << 23),
    'Gb'   : _bit(1 << 30),  'gigabit' : _bit(1 << 30),
    'GB'   : _bit(1 << 33),  'gigabyte': _bit(1 << 33),
    'Tb'   : _bit(1 << 40),  'terabit' : _bit(1 << 40),
    'TB'   : _bit(1 << 43),  'terabyte': _bit(1 << 43),
    'Pb'   : _bit(1 << 50),  'petabit' : _bit(1 << 50),
    'PB'   : _bit(1 << 53),  'petabyte': _bit(1 << 53),
    'Eb'   : _bit(1 << 60),  'exabit'  : _bit(1 << 60),
    'EB'   : _bit(1 << 63),  'exabyte' : _bit(1 << 63),

    # Time
    'fs': _time(_femto),                                'femtosecond': _time(_femto),
    'ps': _time(_pico),                                 'picosecond' : _time(_pico),
    'ns': _time(_nano),                                 'nanosecond' : _time(_nano),
    'ms': _time(0.001),                                 'millisecond': _time(0.001),
    's' : _time(1),     'sec' : _time(1),               'second'     : _time(1),
                        'min' : _time(60),              'minute'     : _time(60),
                        'hr'  : _time(3600),            'hour'       : _time(3600),
                                                        'day'        : _time(3600 * 24),
                        'wk'  : _time(3600 * 24 * 7),   'week'       : _time(3600 * 24 * 7),
                        'yr'  : _time(3600 * 24 * 365), 'year'       : _time(3600 * 24 * 365),
                                                        'decade'     : _time(3600 * 24 * 365 * 10),
                                                        'century'    : _time(3600 * 24 * 365 * 100),
                                                        'millenium'  : _time(3600 * 24 * 365 * 1000),

    # Temperature
    'c': _temp(1, 273.15),     'celsius'   : _temp(1, 273.15),
    'f': _temp(5 / 9, 459.67), 'fahrenheit': _temp(5 / 9, 459.67),
    'k': _temp(1),             'kelvin'    : _temp(1),
    'r': _temp(5 / 9),         'rankine'   : _temp(5 / 9),

}
_reverse_units = {}
# in python 3.6 items in dictionaries are ordered (yay!)
# group units together (yay namedtuples)
for k, v in _units.items():
    _reverse_units.setdefault(v, []).append(k)
for k, v in _reverse_units.items():
    *aliases, name = v
    aliases = f"({', '.join(aliases)})" * bool(aliases)
    _reverse_units[k] = f"{name} {aliases}"
del _length, _mass, _bit, _femto, _nano


def _parse_unit(unit_type):
    unit = _units[unit_type.lower()]
    if unit.type == 'Data':
        return _units.get(unit_type, unit)
    return unit

def _handle_temperature(u1, u2, value):
    kelvin = (value + u1.intercept) * u1.ratio
    return kelvin / u2.ratio - u2.intercept

def convert_unit(from_unit_type, to_unit_type, value):
    from_unit, to_unit = _parse_unit(from_unit_type), _parse_unit(to_unit_type)
    if from_unit.type != to_unit.type:
        raise IncompatibleUnits(f"{from_unit_type} ({from_unit.type}), {to_unit_type} ({to_unit.type})")

    # temperature uses adding along with multiplying
    if from_unit.type == 'Temperature':
        new_value = _handle_temperature(from_unit, to_unit, value)
    else:
        new_value = value * (from_unit.ratio / to_unit.ratio)

    return str(round(new_value, 3)) + to_unit_type


class ConversionPages(BaseReactionPaginator):
    def __init__(self, context, things):
        super().__init__(context)
        self.entries = things

    def _create_embed(self, thing, colour=0):
        return (discord.Embed(colour=colour)
               .set_author(name='List of available units for conversion')
               .add_field(name=thing, value=self.entries[thing])
               )

    default     = page('\N{STRAIGHT RULER}')(functools.partialmethod(_create_embed, 'Length'))
    mass        = page('\N{SCALES}')(functools.partialmethod(_create_embed, 'Mass'))
    storage     = page('\N{PERSONAL COMPUTER}')(functools.partialmethod(_create_embed, 'Data', 0x4CAF50))
    time        = page('\N{ALARM CLOCK}')(functools.partialmethod(_create_embed, 'Time'))
    temperature = page('\N{THERMOMETER}')(functools.partialmethod(_create_embed, 'Temperature', 0xFFC107))


_default_parse_settings = {
    'e_as_E': True,
    '^_as_pow': True,
}

_e_sub_pattern = re.compile('e(?!rf)')
_default_parses = _default_parse_settings.copy
parse_expr = functools.partial(parse_sympy_expr, evaluate=False,
                               transformations=default_transformations)

MAGIC_ERROR_THING = 'error:\x00' # prepend for any errors

class Math:
    def __init__(self, bot):
        self.bot = bot
        self.parsing_configs = Database('math-parsing.json', default_factory=_default_parses)

    @staticmethod
    def _result_embed(ctx, input, output):
        if output.startswith(MAGIC_ERROR_THING):
            color = 0xFF0000
            output = output.replace(MAGIC_ERROR_THING, '', 1)
        else:
            color = 0x00FF00

        return (discord.Embed(colour=color, timestamp=ctx.message.created_at)
               .add_field(name='Input', value=f'```{input}```')
               .add_field(name='Result', value=f'```{output}```', inline=False)
               )

    async def _result_say(self, ctx, input, output, *, output_as_code=True):
        try:
            return await ctx.send(embed=self._result_embed(ctx, input, output))
        except discord.HTTPException:
            return await ctx.send(f"Resulting message is too big for viewing.")

    @staticmethod
    def _calculate(fn_str, sanitizer):
        try:
            fn = sanitizer(fn_str)
        except (ValueError, SyntaxError) as e:
            output = f"{MAGIC_ERROR_THING}{type(e).__name__}: {e}"
        else:
            try:
                output = fn()
            except Exception as e:
                output = f"{MAGIC_ERROR_THING}{type(e).__name__}: {e}"
        return output

    async def _async_calculate(self, fn_str, sanitizer):
        return await self.bot.loop.run_in_executor(None, self._calculate, fn_str, sanitizer)

    @commands.command()
    async def isprime(self, ctx, num: int, accuracy: int=40):
        """Determines if a number is probably prime.

        This command uses the Miller-Rabin primality test.
        As a result, it's not certain if a number is a prime, but there's a good chance it is.

        An optional accuracy number can be passed. Defaults to 40.
        """
        result = _probably_prime(num, accuracy)
        prime_or_not = "not " * (not result)
        await ctx.send(f"**{num}** is {prime_or_not}prime, probably.")

    @commands.command(aliases=['calcfuncs'])
    async def calcops(self, ctx):
        """Lists all the math functions that can be used"""
        ops = [key for key, val in MATH_CONTEXT.items() if callable(val)]
        await ctx.send(f"Available functions: \n```\n{', '.join(ops)}```")

    @commands.command(aliases=['calc'])
    async def calculate(self, ctx, *, expr: str):
        """Calculates a mathematical expression.

        Use `**` for exponents, `^` is the XOR operator.
        """
        output = str(await self._async_calculate(expr, _sanitize))
        await self._result_say(ctx, expr, output)

    @commands.command(aliases=['vectorcalculate'])
    async def vectorcalc(self, ctx, *, expr: str):
        """Calculator for vector calculations

        Because who doesn't want that? \U0001F61B

        Vectors can be represented either by [x, y, z] or Vector(x, y, z)
        """
        vector_repr_func = lambda s: f'Vector({s.group(1)})'
        vector_expr_string = re.sub(r'\[([^"]*?)\]', vector_repr_func, expr)
        output = await self._async_calculate(vector_expr_string, _vector_sanitize)
        await self._result_say(ctx, expr, str(output))

    @commands.command(aliases=['vectorfuncs'])
    async def vectorops(self, ctx):
        """Lists all the functions available for vectors

        These can be called in one of two ways, for a function 'func' and a vector 'vec':
        vec.func() or func(vec)
        """
        vector_funcs = vars(Vector).values()
        def is_vector_func(val):
            return callable(val) and not inspect.isclass(val) and val in vector_funcs
        ops = [key for key, val in VECTOR_CONTEXT.items() if is_vector_func(val)]
        await ctx.send(f"Available vector functions: \n```\n{', '.join(ops)}```")

    @commands.command()
    async def vectorprops(self, ctx):
        """Lists all the properties available for vectors

        These can only be called as vec.func
        """
        ops = [key for key, val in VECTOR_CONTEXT.items() if isinstance(val, property)]
        await ctx.send(f"Available vector properties: \n```\n{', '.join(ops)}```")

    @commands.command()
    async def vectormisc(self, ctx):
        """Lists all the functions available for vectors that aren't in the vector class

        These can only be called as func(vec)
        """

        vector_funcs = vars(Vector).values()
        ops = [key for key, val in VECTOR_CONTEXT.items() if val not in vector_funcs]
        await ctx.send(f"Available misc vector functions: \n```\n{', '.join(ops)}```")

    _unit_or_num = union(float, str)

    @staticmethod
    def _parse_units(arg1, arg2, arg3):
        if isinstance(arg1, float):
            return arg2, arg3, arg1
        if isinstance(arg2, float):
            return arg1, arg3, arg2
        if isinstance(arg3, float):
            return arg1, arg2, arg3
        raise ValueError("You need a number at least...")

    @commands.command()
    async def convert(self, ctx, arg1: _unit_or_num, arg2: _unit_or_num, arg3: _unit_or_num):
        """Converts a value from one unit to another.

        The order of the arguments can be arbitrary. 
        You just need to make sure you have two units and a number.

        The first unit mentioned will always be the "from" unit.
        While the other one will always be the two "to" unit.
        """
        try:
            args = self._parse_units(value, from_unit, to_unit)
            result = convert_unit(*args)
        except ValueError as e:
            result = f'{MAGIC_ERROR_THING}{e}'
        except IncompatibleUnits as e:
            result = f'{MAGIC_ERROR_THING}{type(e).__name__}: {e}'
        except KeyError as e:
            result = f'{MAGIC_ERROR_THING}{e} is not a recognized unit of measurement.'
        await self._result_say(ctx, f'{value} {from_unit} -> {to_unit}', result)

    @commands.command()
    async def conversions(self, ctx):
        """Lists all the available units"""
        grouped = itertools.groupby(_reverse_units.items(), lambda t: t[0].type)
        conversion_fields = {k: '\n'.join([t[1] for t in v]) for k, v in grouped}
        pages = ConversionPages(ctx, conversion_fields)
        await pages.interact()

    def _transform_expr(self, ctx, expr):
        config = self.parsing_configs[ctx.author]
        if config.get('e_as_E'):
            expr = _e_sub_pattern.sub('E', expr)
        if config.get('^_as_pow'):
            expr = expr.replace('^', '**')
        return expr

    if sympy:
        # SymPy related commands
        # Use oo for infinity
        @commands.command(aliases=['derivative'])
        async def differentiate(self, ctx, *, expr: str):
            """Finds the derivative of an equation"""

            equation = parse_expr(self._transform_expr(ctx, expr))
            symbols = list(equation.free_symbols)
            if len(symbols) > 1:
                return await ctx.send("You have too many symbols in your equation")
            result = sympy.pretty(sympy.diff(equation, *symbols))
            await self._result_say(ctx, equation, result, output_as_code=True)

        @commands.command()
        async def limit(self, ctx, expr: str, var: sympy.Symbol, to, dir='+'):
            """Finds the limit of an equation.

            to is where the var will approach
            dir is the side the limit will be approached from

            The expression must be in quotes.
            """
            equation = parse_expr(self._transform_expr(ctx, expr))
            result = sympy.pretty(sympy.limit(expr, var, to, dir))
            await self._result_say(ctx, equation, result, output_as_code=True)

        @commands.command(aliases=['integral'])
        async def integrate(self, ctx, *, expr: str):
            """Finds the indefinite integral (aka antiderivative of an equation)"""
            equation = parse_expr(self._transform_expr(ctx, expr))
            symbols = list(equation.free_symbols)
            if len(symbols) > 1:
                return await ctx.send("You have too many symbols in your equation")
            result = sympy.pretty(sympy.integrate(equation, symbols[0]))
            await self._result_say(ctx, equation, result, output_as_code=True)

    @commands.group()
    async def mathconfig(self, ctx):
        """Command group for all math related configs"""
        pass

    @mathconfig.command(name='e')
    async def e_as_E(self, ctx, bool_: bool):
        """Sets whether or not you want any e's in the expression to be parsed as E

        By default this is True. If this is False, then `e` will not be valid 
        and you have to use E for the constant.
        """
        thing = ['no longer', 'now'][bool_]
        self.parsing_configs[ctx.author]['e_as_E'] = bool_
        await ctx.send('`e` will {thing} be treated as the constant `e` for you.')

    @mathconfig.command(name='pow')
    async def pow_(self, ctx, bool_: bool=None):
        """Sets whether or not you want any ^'s in the expression to be parsed as **

        By default this is True. If this is False, then the ^'s will be treated as XOR.
        """
        thing = ['no longer', 'now'][bool_]
        self.parsing_configs[ctx.author]['^_as_pow'] = bool_
        await ctx.send('`^` will {thing} be treated as the power operator for you.')

def setup(bot):
    bot.add_cog(Math(bot))
