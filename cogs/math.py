import ast
import inspect
import math
import random
import re

from collections.abc import Sequence
from discord.ext import commands
from operator import itemgetter
from random import randrange

from .utils.errors import InvalidUserArgument
from .utils.misc import usage

try:
    import sympy
except ImportError:
    sympy = None
else:
    from sympy.parsing.sympy_parser import (
        parse_expr, standard_transformations, implicit_multiplication_application
    )
    default_transformations = (implicit_multiplication_application, *standard_transformations)

def _get_context(obj):
    return {attr: func for attr, func in inspect.getmembers(obj) if not attr.startswith('_')}

MATH_CONTEXT = _get_context(math)
sec = lambda x: 1 / math.cos(x)
csc = lambda x: 1 / math.sin(x)
cot = lambda x: 1 / math.tan(x)
sign = lambda x: (x > 0) - (x < 0)
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

# Pure Python Vector class implementation by Gareth Rees
# https://github.com/gareth-rees/geometry/blob/master/vector.py
# TODO: Use numpy
class IncompatibleDimensions(Exception):
    pass

class Vector(tuple):
    def __new__(cls, *args):
        if len(args) == 1: args = args[0]
        return super().__new__(cls, tuple(args))

    def __repr__(self):
        fmt = '{0}({1!r})' if len(self) == 1 else '{0}{1!r}'
        return fmt.format(type(self).__name__, tuple(self))

    def __str__(self):
        return f"[{', '.join(map(str, self))}]"

    def _check_compatibility(self, other):
        if len(self) != len(other):
            raise IncompatibleDimensions(len(self), len(other))

    def _dimension_error(self, name):
        return ValueError(f'.{name}() is not implemented for {len(self)}-dimensional vectors.')

    def __add__(self, other):
        if not isinstance(other, Sequence):
            return NotImplemented
        self._check_compatibility(other)
        return type(self)(v + w for v, w in zip(self, other))

    def __radd__(self, other):
        if not isinstance(other, Sequence):
            return NotImplemented
        self._check_compatibility(other)
        return type(self)(w + v for v, w in zip(self, other))

    def __sub__(self, other):
        if not isinstance(other, Sequence):
            return NotImplemented
        self._check_compatibility(other)
        return type(self)(v - w for v, w in zip(self, other))

    def __rsub__(self, other):
        if not isinstance(other, Sequence):
            return NotImplemented
        self._check_compatibility(other)
        return type(self)(w - v for v, w in zip(self, other))

    def __mul__(self, s):
        return type(self)(v * s for v in self)

    def __rmul__(self, s):
        return type(self)(v * s for v in self)

    def __div__(self, s):
        return type(self)(v / s for v in self)

    def __truediv__(self, s):
        return type(self)(v / s for v in self)

    def __floordiv__(self, s):
        return type(self)(v // s for v in self)

    def __neg__(self):
        return self * -1

    def __pos__(self):
        return self

    def __abs__(self):
        return self.magnitude

    def __bool__(self):
        return self.magnitude_squared != 0

    def dot(self, other):
        """Return the dot product with the other vector."""
        self._check_compatibility(other)
        return sum(v * w for v, w in zip(self, other))

    def cross(self, other):
        """Return the cross product with another vector. For two-dimensional
        and three-dimensional vectors only.
        """
        self._check_compatibility(other)
        if len(self) == 2:
            return self[0] * other[1] - self[1] * other[0]
        elif len(self) == 3:
            return Vector(self[1] * other[2] - self[2] * other[1],
                          self[2] * other[0] - self[0] * other[2],
                          self[0] * other[1] - self[1] * other[0])
        else:
            raise self._dimension_error('cross')

    @property
    def magnitude_squared(self):
        return self.dot(self)

    mag_squared = magnitude_squared

    @property
    def magnitude(self):
        return self.mag_squared ** 0.5

    mag = magnitude

    @property
    def angle(self):
        """The signed angle [-pi, pi] between this vector and the x-axis. For
        two-dimensional vectors only.
        """
        if len(self) == 2:
            return math.atan2(self[1], self[0])
        else:
            raise self._dimension_error('angle')

    def distance(self, other):
        """Return the Euclidean distance to another vector
        (understanding both vectors as points).
        """
        return abs(self - other)

    def taxicab(self, other):
        """Return the taxicab aka Manhattan distance to another vector
        (understanding both vectors as points).
        """
        self._check_compatibility(other)
        return sum(abs(v - w) for v, w in zip(self, other))

    def projected(self, other):
        """Return the projection of another vector onto this vector. If this
        vector has magnitude zero, raise ZeroDivisionError.
        """
        return self * (self.dot(other) / self.magnitude_squared)

    def normalized(self):
        """Return a unit vector in the same direction as this vector. If this
        has magnitude zero, raise ZeroDivisionError.
        """
        return self / abs(self)

    def scaled(self, s):
        """Return a vector of magnitude s in the same direction as this vector.
        If this has magnitude zero, raise ZeroDivisionError.
        """
        return self * (s / abs(self))

    # namedtuple-style hax
    x = property(itemgetter(0), doc='Alias for field number 0')
    y = property(itemgetter(1), doc='Alias for field number 1')
    z = property(itemgetter(2), doc='Alias for field number 2')

    @classmethod
    def zero(cls, dim=2):
        return cls(*((0,) * dim))

VECTOR_CONTEXT = _get_context(Vector)
VECTOR_CONTEXT.update(Vector=Vector, abs=abs, bool=bool, degrees=math.degrees, __builtins__=None)
_vector_sanitize = _sanitize_func(r"[0-9, +-/*()]+", VECTOR_CONTEXT, _is_sane_func(VECTOR_CONTEXT))

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

class Math:
    __prefix__ = ['+', '-', '*', '/', '^', '=']
    def __init__(self, bot):
        self.bot = bot

    async def _result_say(self, input, output):
        return await self.bot.say(f"```css\nInput: \n{input}\n\nOutput:\n{output}```")

    def _calculate(self, fn_str, sanitizer):
        try:
            fn = sanitizer(fn_str)
        except (ValueError, SyntaxError) as e:
            output = f"{type(e).__name__}: {e}"
        else:
            try:
                output = fn()
            except Exception as e:
                output = f"{type(e).__name__}: {e}"
        return output

    @commands.command()
    async def isprime(self, num: int, accuracy: int=40):
        """Determines if a number is probably prime.

        This command uses the Miller-Rabin primality test.
        As a result, it's not certain if a number is a prime, but there's a good chance it is.

        An optional accuracy number can be passed. Defaults to 40.
        """
        result = _probably_prime(num, accuracy)
        prime_or_not = "not " * (not result)
        await self.bot.say(f"**{num}** is {prime_or_not}prime, probably.")

    @commands.command(aliases=['calcfuncs'])
    async def calcops(self):
        """Lists all the math functions that can be used"""
        ops = [key for key, val in MATH_CONTEXT.items() if callable(val)]
        await self.bot.say(f"Available functions: \n```\n{', '.join(ops)}```")

    @commands.command(aliases=['calc'])
    async def calculate(self, *, expr: str):
        """Calculates a mathematical expression"""
        output = self._calculate(expr, _sanitize)
        if '^' in expr:
            output += "\nNote: '^' is the XOR operator. Use '**' for power."
        await self._result_say(expr, output)

    @commands.command(aliases=['leval'])
    async def literaleval(self, *, expr: str):
        """Basically a "safe" eval"""
        output = self._calculate(expr, lambda s: lambda: ast.literal_eval(s))
        await self._result_say(expr, output)

    @commands.command(aliases=['vectorcalculate'])
    async def vectorcalc(self, *, expr: str):
        """Calculator for vector calculations

        Because who doesn't want that? \U0001F61B

        Vectors can be represented either by [x, y, z] or Vector(x, y, z)
        """
        vector_repr_func = lambda s: repr(Vector(ast.literal_eval(s.group(1))))
        vector_expr_string = re.sub(r'(\[[^"]*?\])', vector_repr_func, expr)
        await self._result_say(expr, self._calculate(vector_expr_string, _vector_sanitize))

    @commands.command(aliases=['vectorfuncs'])
    async def vectorops(self):
        """Lists all the functions available for vectors

        These can be called in one of two ways, for a function 'func' and a vector 'vec':
        vec.func() or func(vec)
        """
        vector_funcs = vars(Vector).values()
        def is_vector_func(val):
            return callable(val) and not inspect.isclass(val) and val in vector_funcs
        ops = [key for key, val in VECTOR_CONTEXT.items() if is_vector_func(val)]
        await self.bot.say(f"Available vector functions: \n```\n{', '.join(ops)}```")

    @commands.command()
    async def vectorprops(self):
        """Lists all the properties available for vectors

        These can only be called as vec.func
        """
        ops = [key for key, val in VECTOR_CONTEXT.items() if isinstance(val, property)]
        await self.bot.say(f"Available vector properties: \n```\n{', '.join(ops)}```")

    @commands.command()
    async def vectormisc(self):
        """Lists all the functions available for vectors that aren't in the vector class

        These can only be called as func(vec)
        """

        vector_funcs = vars(Vector).values()
        ops = [key for key, val in VECTOR_CONTEXT.items() if val not in vector_funcs]
        await self.bot.say(f"Available misc vector functions: \n```\n{', '.join(ops)}```")

    if sympy:
        # SymPy related commands
        # Use oo for infinity
        @commands.command(aliases=['derivative'])
        async def differentiate(self, expr: str, n: int=1):
            """Finds the derivative of an equation

            n is the nth derivative you wish to calcuate.
            The expression must be in quotes.
            """
            equation = parse_expr(expr, evaluate=False, transformations=default_transformations)
            symbols = list(equation.free_symbols)
            if len(symbols) > 1:
                raise InvalidArgument("You have too many symbols in your equation")
            result = sympy.pretty(sympy.diff(equation, *(symbols * n)))
            await self._result_say(equation, result)

        @commands.command()
        async def limit(self, expr: str, var: sympy.Symbol, to, dir='+'):
            """Finds the limit of an equation.

            var is the nth derivative you wish to calcuate
            to is where the var will approach
            dir is the side the limit will be approached from

            The expression must be in quotes.
            """
            equation = parse_expr(expr, evaluate=False, transformations=default_transformations)
            result = sympy.pretty(sympy.limit(expr, var, to, dir))
            await self._result_say(equation, result)

        @commands.command(aliases=['integral'])
        async def integrate(self, *, expr: str):
            """Finds the indefinite integral (aka antiderivative of an equation)

            Unlike derivative, the expression does not require quotes
            """
            equation = parse_expr(expr, evaluate=False, transformations=default_transformations)
            symbols = list(equation.free_symbols)
            if len(symbols) > 1:
                raise InvalidArgument("You have too many symbols in your equation")
            result = sympy.pretty(sympy.integrate(equation, symbols[0]))
            await self._result_say(equation, result)

def setup(bot):
    bot.add_cog(Math(bot))
