"""The single place where computed money is rounded (CLAUDE.md, money rules).

Pure integer / Fraction math. No floats.
"""

from fractions import Fraction

BP = 10_000  # basis points in 100%


def _as_fraction(value: int | Fraction) -> Fraction:
    return value if isinstance(value, Fraction) else Fraction(value)


def round_amount(value: int | Fraction, step: int = 1) -> int:
    """Round half-up to a multiple of `step`. Negative values round symmetrically."""
    if step <= 0:
        raise ValueError("step must be positive")
    v = _as_fraction(value)
    sign = -1 if v < 0 else 1
    q = abs(v) / step
    whole = q.numerator // q.denominator
    if q - whole >= Fraction(1, 2):
        whole += 1
    return sign * whole * step


def floor_to_step(value: int | Fraction, step: int = 1) -> int:
    v = _as_fraction(value)
    if v < 0:
        raise ValueError("floor_to_step expects a non-negative value")
    q = v / step
    return (q.numerator // q.denominator) * step


def percent_of(amount: int, basis_points: int, step: int = 1) -> int:
    """`basis_points` percent of `amount`, rounded half-up to `step`."""
    return round_amount(Fraction(amount * basis_points, BP), step)
