"""A pseudo-random generator written out in full, so that two languages can agree.

The colony's ground is generated on the server, by this code, and in the browser, by its twin
in TypeScript. That is only sound if both produce the same numbers -- and `random.Random` is
CPython's Mersenne Twister with CPython's `gauss`, which would have to be reimplemented in
JavaScript and kept correct for ever. Reimplementing a language's standard library is the
wrong end to start from.

So the algorithm is made portable instead. Mulberry32 is thirty-two-bit integer arithmetic and
nothing else: `Math.imul` in JavaScript and a mask in Python compute it identically, with no
appeal to a floating-point library and no per-implementation choices to get wrong.

Directions come out of sphere point picking rather than out of normalised gaussians. Partly
because it is exactly uniform where normalising three gaussians only approximately is, and
partly because it needs no logarithm: every transcendental call is one more place where two
libm implementations can disagree in the last bit.
"""
from __future__ import annotations

import math

MASK = 0xFFFFFFFF


def seed_int(text: str) -> int:
    """FNV-1a, 32 bit. Spelled out for the same reason as the rest of this module."""
    h = 2166136261
    for byte in text.encode("utf-8"):
        h = ((h ^ byte) * 16777619) & MASK
    return h


class Prng:
    """Mulberry32. One 32-bit word of state, and every step is a 32-bit integer operation."""

    __slots__ = ("state",)

    def __init__(self, seed: int | str):
        self.state = seed_int(seed) if isinstance(seed, str) else seed & MASK

    def next_uint(self) -> int:
        self.state = (self.state + 0x6D2B79F5) & MASK
        t = self.state
        t = ((t ^ (t >> 15)) * (t | 1)) & MASK
        t = (t ^ (t + ((t ^ (t >> 7)) * (t | 61)) & MASK)) & MASK
        return (t ^ (t >> 14)) & MASK

    def random(self) -> float:
        return self.next_uint() / 4294967296.0

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self.random()

    def randint(self, low: int, high: int) -> int:
        """Inclusive at both ends, like `random.randint`."""
        return low + int(self.random() * (high - low + 1))

    def direction(self) -> tuple[float, float, float]:
        """A point picked uniformly on the unit sphere."""
        z = 2.0 * self.random() - 1.0
        phi = 2.0 * math.pi * self.random()
        r = math.sqrt(max(0.0, 1.0 - z * z))
        return (r * math.cos(phi), r * math.sin(phi), z)
