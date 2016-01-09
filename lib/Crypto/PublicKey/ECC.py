# ===================================================================
#
# Copyright (c) 2015, Legrandin <helderijs@gmail.com>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in
#    the documentation and/or other materials provided with the
#    distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
# ===================================================================


from Crypto.Math.Numbers import Integer
from Crypto.Random import get_random_bytes

class _Curve(object):
    pass

_curve = _Curve()
_curve.p = Integer(115792089210356248762697446949407573530086143415290314195533631308867097853951)
_curve.order = Integer(115792089210356248762697446949407573529996955224135760342422259061068512044369)
_curve.Gx = Integer(0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296)
_curve.Gy = Integer(0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)


# https://www.nsa.gov/ia/_files/nist-routines.pdf
# http://point-at-infinity.org/ecc/nisttv
# http://www.hyperelliptic.org/EFD/g1p/auto-shortw-jacobian-3.html
# https://en.wikibooks.org/wiki/Cryptography/Prime_Curve/Jacobian_Coordinates
# https://eprint.iacr.org/2013/816.pdf

class EccPoint(object):

    def __init__(self, x, y):
        self._x = Integer(x)
        self._y = Integer(y)

    def __eq__(self, point):
        return self._x == point._x and self._y == point._y

    def __neg__(self):
        if self.is_point_at_infinity():
            return self.point_at_infinity()
        return EccPoint(self._x, _curve.p - self._y)

    def copy(self):
        return EccPoint(self._x, self._y)

    def is_point_at_infinity(self):
        return self._x == 0 and self._y == 0

    @staticmethod
    def point_at_infinity():
        return EccPoint(0, 0)

    @property
    def x(self):
        if self.is_point_at_infinity():
            raise ValueError("Point at infinity")
        return self._x

    @property
    def y(self):
        if self.is_point_at_infinity():
            raise ValueError("Point at infinity")
        return self._y

    def double(self):
        """Return a new point, doubling this one"""

        if self._y == 0:
            return self.point_at_infinity()

        # common = (pow(self._x, 2, _curve.p) * 3 - 3) * (self._y << 1).inverse(_curve.p) % _curve.p
        common = pow(self._x, 2, _curve.p)
        common *= 3
        common -= 3
        common *= (self._y << 1).inverse(_curve.p)
        common %= _curve.p
        # x3 = (pow(common, 2, _curve.p) - 2 * self._x) % _curve.p
        x3 = pow(common, 2, _curve.p)
        x3 -= self._x
        x3 -= self._x
        while x3 < 0:
            x3 += _curve.p
        # y3 = ((self._x - x3) * common - self._y) % _curve.p
        y3 = self._x - x3
        y3 *= common
        y3 -= self._y
        y3 %= _curve.p

        return EccPoint(x3, y3)

    def add(self, point):
        """Return a new point, the addition of this one and another"""

        if self.is_point_at_infinity():
            return point.copy()

        if point.is_point_at_infinity():
            return self.copy()

        if self == point:
            return self.double()

        if self._x == point._x:
            return self.point_at_infinity()

        # common = (point._y - self._y) * (point._x - self._x).inverse(_curve.p) % _curve.p
        common = point._y - self._y
        common *= (point._x - self._x).inverse(_curve.p)
        common %= _curve.p
        # x3 = (pow(common, 2, _curve.p) - self._x - point._x) % _curve.p
        x3 = pow(common, 2, _curve.p)
        x3 -= self._x
        x3 -= point._x
        while x3 < 0:
            x3 += _curve.p
        # y3 = ((self._x - x3) * common - self._y) % _curve.p
        y3 = (self._x - x3)
        y3 *= common
        y3 -= self._y
        y3 %= _curve.p

        return EccPoint(x3, y3)


    def multiply(self, scalar):
        """Return a new point, the scalar product of this one"""

        if scalar < 0:
            raise ValueError("Scalar multiplication only defined for non-negative integers")

        # Trivial results
        if scalar == 0 or self.is_point_at_infinity():
            return self.point_at_infinity()
        elif scalar == 1:
            return self.copy()

        # Convert to NAF
        WINDOW_BITS = 4
        window_high = 1 << WINDOW_BITS
        window_low = 1 << (WINDOW_BITS - 1)
        window_mask = window_high - 1

        scalar_int = int(scalar)
        naf = []
        while scalar_int > 0:
            if scalar_int & 1:
                di = scalar_int & window_mask
                if di >= window_low:
                    di -= window_high
                scalar_int -= di
            else:
                di = 0
            naf.append(di)
            scalar_int >>= 1
        naf.reverse()

        # naf contains d_(i-1), d_(i-2), .. d_1, d_0

        if hasattr(self, "_precomp"):
            precomp = self._precomp
        else:
            # Precompute 1P, 3P, 5P, .. (2**(W-1) - 1)P
            # which is 1P..7P for W=4 (we also add negatives)
            precomp =  [0, self, self.double()]      # 0, 1P, 2P
            precomp += [precomp[2].add(precomp[1])]  # 3P
            precomp += [0]                           # 4P
            precomp += [precomp[2].add(precomp[3])]  # 5P
            precomp += [0]                           # 6P
            precomp += [precomp[2].add(precomp[5])]  # 7P
            precomp += [ -x for x in precomp[:0:-1]]
            self._precomp = precomp

        result = self.point_at_infinity()
        for x in naf:
            result = result.double()
            if x != 0:
                result = result.add(precomp[x])

        return result


_curve.G = EccPoint(_curve.Gx, _curve.Gy)


class EccKey(object):

    def __init__(self, **kwargs):
        """Create a new ECC key

        Do not instantiate this object directly.

        Keywords:
          curve : string
            It must be "P-256".
          d : integer
            Only for a private key. It must be in the range [1..order-1].
          point : EccPoint
            Mandatory for a public key. If provided for a private key,
            the implementation will NOT check whether it matches ``d``.
        """

        self.curve = kwargs.pop("curve", None)
        self._d = kwargs.pop("d", None)
        self._point = kwargs.pop("point", None)

        if self.curve != "P-256":
            raise ValueError("Unsupported curve (%s)", self.curve)

        if self._d is None:
            if self._point is None:
                raise ValueError("Either private or public ECC component must be specified")
        else:
            if not 1 <= self._d < _curve.order:
                raise ValueError("Invalid ECC private component")

    def has_private(self):
        return self._d is not None

    def _sign(self, z, k):
        assert 0 < k < _curve.order
        # TODO: add blinding
        r = _curve.G.multiply(k).x % _curve.order
        s = k.inverse(_curve.order) * (z + self._d * r) % _curve.order
        return (r, s)

    def _verify(self, z, rs):
        sinv = rs[1].inverse(_curve.order)
        point1 = _curve.G.multiply((sinv * z) % _curve.order)
        point2 = self.pointQ.multiply((sinv * rs[0])  % _curve.order)
        return (point1.add(point2)).x == rs[0]

    @property
    def d(self):
        if not self.has_private():
            raise ValueError("This is not a private ECC key")
        return self._d

    @property
    def pointQ(self):
        if self._point is None:
            self._point = _curve.G.multiply(self._d)
        return self._point

    def public_key(self):
        return EccKey(curve="P-256", point=self.pointQ)


def generate(**kwargs):
    """Generate a new private key on the given curve.

    :Keywords:
      curve : string
        It must be "P-256".
      randfunc : callable
        The RNG to read randomness from.
        If ``None``, the system source is used.
    """

    curve = kwargs.pop("curve")
    randfunc = kwargs.pop("randfunc", get_random_bytes)

    d = Integer.random_range(min_inclusive=1,
                             max_exclusive=_curve.order,
                             randfunc=randfunc)

    return EccKey(curve=curve, d=d)


if __name__ == "__main__":
    import time
    d = 0xc51e4753afdec1e6b6c6a5b992f43f8dd0c7a8933072708b6522468b2ffb06fd

    point = generate("P-256").pointQ
    start = time.time()
    count = 30
    for x in xrange(count):
        point.multiply(d)
    print (time.time() - start) / count * 1000, "ms"
