"""Russian wording that depends on a number.

Small, but it lives in one place because the alternative is «81 периодов» in
one document and «2 периода» in another, and the export is what an astrologer
reads instead of the site.
"""

from __future__ import annotations

#: Superscripts for the level of a dasha tree — 9³ reads better than 9^3 in a
#: document meant to be read rather than parsed.
SUPERSCRIPTS = {0: "⁰", 1: "¹", 2: "²", 3: "³", 4: "⁴",
                5: "⁵", 6: "⁶", 7: "⁷", 8: "⁸", 9: "⁹"}


def plural(count: int, one: str, few: str, many: str) -> str:
    """The form of a noun that goes with ``count``: 1 период, 2 периода, 5 периодов.

    The teens are the exception the naive rule gets wrong: 11, 111, 1011 all
    take the ``many`` form even though they end in 1.
    """
    tail_100 = abs(count) % 100
    if 11 <= tail_100 <= 14:
        return many
    tail = abs(count) % 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def counted(count: int, one: str, few: str, many: str) -> str:
    """``count`` and its noun together: ``counted(81, …)`` → «81 период»."""
    return f"{count} {plural(count, one, few, many)}"


def superscript(number: int) -> str:
    return "".join(SUPERSCRIPTS[int(digit)] for digit in str(abs(number)))


def number(value: float, places: int = 1) -> str:
    """A number for a reader: one decimal, and no trailing «.0».

    The soul-path figure is printed twice — as the headline and as the total of
    the table it is made of. Formatting them differently (``:.0f`` against
    ``:.1f``) let 62.5 appear as «62%» above a table whose total said 62.5, and
    Prompt 07 exists precisely so that the number and its table cannot disagree.
    Rounding here is half-up, because «62.5 → 62» surprises everyone who is not
    a numerical analyst.
    """
    from decimal import ROUND_HALF_UP, Decimal

    quantum = Decimal(1).scaleb(-places)
    rounded = Decimal(repr(float(value))).quantize(quantum, rounding=ROUND_HALF_UP)
    text = format(rounded.normalize(), "f")
    return text if text != "-0" else "0"
