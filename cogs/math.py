import ast
import inspect
import math
import re

from collections.abc import Sequence
from discord.ext import commands

MATH_CONTEXT = {a: getattr(math, a, None) for a in dir(math) if not a.startswith('_')}
sec = lambda x: 1 / math.cos(x)
csc = lambda x: 1 / math.sin(x)
cot = lambda x: 1 / math.tan(x)
sign = lambda x: (x > 0) - (x < 0)
MATH_CONTEXT.update(ln=math.log, arcsin=math.asin, arccos=math.acos, arctan=math.atan,
                    sec=sec, secant=sec, csc=csc, cosecant=csc, cot=cot, cotangent=cot,
                    abs=abs, min=min, max=max, divmod=divmod, round=round, sign=sign,
                    __builtins__=None
                    )
del sec, csc, cot, sign
OTHER_OPS = ['and', 'or', 'not', ]

def _is_sane(token):
    if not token:
        return True
    elif token == '__builtins__':
        return False
    return token in MATH_CONTEXT or token in OTHER_OPS
    
def sanitize(fn_str):
    words = re.split(r"[0-9.+\-*/^&|<>, ()=]+", fn_str)
    for token in words:
        if not _is_sane(token):
            raise ValueError(f"Unrecognized token: {token}")

    return eval("lambda: " + fn_str, MATH_CONTEXT)

class IncompatibleDimensions(Exception):
    pass
    
# Pure Python Vector class implementation by Gareth Rees
# https://github.com/gareth-rees/geometry/blob/master/vector.py
# TODO: Use numpy
class Vector(tuple):
    def __new__(cls, *args):
        if len(args) == 1: args = args[0]
        return super().__new__(cls, tuple(args))
    
    def __repr__(self):
        fmt = '{0}({1!r})' if len(self) == 1 else '{0}{1!r}'
        return fmt.format(type(self).__name__, tuple(self))
        
    def __str__(self):
        return '[{}]'.format(', '.join(map(str, self)))

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

    @property
    def x(self):
        return self[0]

    @property
    def y(self):
        return self[1]

    @property
    def z(self):
        return self[2]
        
    @classmethod
    def zero(cls, dim=2):
        return cls(*((0,) * dim))
        
def _make_vectors(*values):
    length = len(values)
    if length in (2, 3):
        return Vector.zero(length), Vector(*values)
    else:
        half = length // 2
        h1, h2 = values[:half], values[half:]
        return Vector(*h1), Vector(*h2)
        
VECTOR_CONTEXT = {
    'Vector': Vector,
    'angle': Vector.angle, 
    'cross': Vector.cross, 
    'dot': Vector.dot, 
    'magnitude_squared': Vector.magnitude_squared, 
    'mag_squared': Vector.mag_squared,
    'magnitude': Vector.magnitude,
    'mag': Vector.mag,
    'normalized': Vector.normalized,
    'projected': Vector.projected,
    'distance': Vector.distance,
    'scaled': Vector.scaled,
    'taxicab': Vector.taxicab,
    'zero': Vector.zero,
    'x': Vector.x,
    'y': Vector.y,
    'z': Vector.z,
    'abs': abs,
    'bool': bool,
    'degrees': math.degrees,
    '__builtins__': None,
    }

def _vector_is_sane(token):
    if not token:
        return True
    elif token == '__builtins__':
        return False
    return token in VECTOR_CONTEXT
    
def vector_sanitize(fn_str):
    words = re.split(r"[0-9, +-/*()]+", fn_str)
    for token in words:
        if not _vector_is_sane(token):
            raise ValueError(f"Unrecognized token: {token}")
            
    return eval("lambda: " + fn_str, VECTOR_CONTEXT)
    
class Math:
    __prefix__ = ['+', '-', '*', '/']
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(aliases=['calcfuncs'])
    async def calcops(self):
        """Lists all the math functions that can be used"""
        ops = [key for key, val in MATH_CONTEXT.items() if callable(val)]
        await self.bot.say(f"Available functions: \n```\n{', '.join(ops)}```")
        
    @commands.command(aliases=['calc'])
    async def calculate(self, *, expr: str): 
        """Calculates a mathematical expression"""
        try:
            fn = sanitize(expr)
        except (ValueError, SyntaxError) as e: 
            output = f"{type(e).__name__}: {e}"
        else:
            try:
                output = fn()
            except Exception as e:
                output = f"{type(e).__name__}: {e}"
            
        await self.bot.say(f"```css\nInput: \n{expr}\n\nOutput:\n{output}```")
    
    # @commands.group(pass_context=True, aliases=['vec'])
    # async def vector(self, ctx):
        # """Super-command for all vector-related commands"""
        # if ctx.invoked_subcommand is None:
            # subcommands = '\n'.join(ctx.command.commands.keys())
            # await self.bot.say(f"```\nAvailable vector calculations:\n{subcommands}```")
        
    # async def _vector_op(self, op, v1, v2, res_name):
        # try:
            # result = op(v1, v2)
        # except IncompatibleDimensions as e:
            # result = f"{type(e).__name__}: {e}"
        # await self.bot.say(f"```css\nVectors: \n{v1}, {v2}\n\n{res_name}:\n{result}```")
        
    # async def _vector_calc(self, op, *values, name):
        # v1, v2 = _make_vectors(*values)
        # await self._vector_op(op, v1, v2, name)
        
    # @vector.command(aliases=['manhattan'])    
    # async def taxicab(self, *values: float):
        # """Calculates the "taxicab distance" (also known as the Manhattan distance) of two points.
        
        # If only two or three numbers are specified, 
        # the distance is calculated with the origin ([0, 0] or [0, 0, 0])
        # """
        # await self._vector_calc(Vector.taxicab, *values, name='Taxicab Distance')
        
    # @vector.command(aliases=['distance', 'dist'])    
    # async def euclidean(self, *values: float):
        # """Calculates the "Euclidean distance" of two points.
        
        # If only two or three numbers are specified, 
        # The command calculates the magnitude of the vector formed.
        # """
        # await self._vector_calc(Vector.distance, *values, name='Distance')
        
    # @vector.command()    
    # async def dot(self, *values: float):
        # """Calculates the Dot Product of two points.
        # """
        # await self._vector_calc(Vector.dot, *values, name='Dot Product')
        
    # @vector.command()    
    # async def cross(self, *values: float):
        # """Calculates the Cross Product of two points.
        # """
        # await self._vector_calc(Vector.cross, *values, name='Cross Product')
        
    @commands.command(aliases=['vectorcalculate'])
    async def vectorcalc(self, *, expr: str):
        """Calculator for vector calculations
        
        Because who doesn't want that? \U0001F61B
        """
        vector_repr_func = lambda s: repr(Vector(ast.literal_eval(s.group(1))))
        vector_expr_string = re.sub(r'(\[[^"]*?\])', vector_repr_func, expr)
        try:
            fn = vector_sanitize(vector_expr_string)
        except (ValueError, SyntaxError) as e: 
            output = f"{type(e).__name__}: {e}"
        else:
            try:
                output = fn()
            except Exception as e:
                output = f"{type(e).__name__}: {e}"
            
        await self.bot.say(f"```css\nInput: \n{expr}\n\nOutput:\n{output}```")
        
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
        
        
def setup(bot):
    bot.add_cog(Math(bot))