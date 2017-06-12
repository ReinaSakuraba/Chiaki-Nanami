'''Vector operations'''
import math
import operator

from collections.abc import Sequence
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

    def _apply_operation(self, op, typ, other):
        self._check_compatibility(other)
        return typ(map(op, self, other))

    def __add__(self, other):
        if not isinstance(other, Sequence):
            return NotImplemented
        self._check_compatibility(other)
        return type(self)(map(operator.add, self, other))

    def __radd__(self, other):
        if not isinstance(other, Sequence):
            return NotImplemented
        self._check_compatibility(other)
        return type(self)(map(operator.add, other, self))

    def __sub__(self, other):
        if not isinstance(other, Sequence):
            return NotImplemented
        self._check_compatibility(other)
        return type(self)(map(operator.sub, self, other))

    def __rsub__(self, other):
        if not isinstance(other, Sequence):
            return NotImplemented
        self._check_compatibility(other)
        return type(self)(map(operator.sub, other, self))

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
        return sum(map(operator.mul, other, self))

    def cross(self, other):
        """Return the cross product with another vector. For two-dimensional
        and three-dimensional vectors only.
        """
        self._check_compatibility(other)
        if len(self) == 2:
            return self[0] * other[1] - self[1] * other[0]
        elif len(self) == 3:
            return type(self)(self[1] * other[2] - self[2] * other[1],
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

    def rotated(self, theta):
        """Return the vector rotated through theta radians about the
        origin. For two-dimensional and three-dimensional vectors only.
        """
        if len(self) == 2:
            s, c = sin(theta), cos(theta)
            return Vector(self.dot((c, -s)), self.dot((s, c)))
        else:
            raise self._dimension_error('rotated')

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
    x = property(operator.itemgetter(0), doc='Alias for field number 0')
    y = property(operator.itemgetter(1), doc='Alias for field number 1')
    z = property(operator.itemgetter(2), doc='Alias for field number 2')

    @classmethod
    def zero(cls, dim=2):
        return cls(*((0,) * dim))