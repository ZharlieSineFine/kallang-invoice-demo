"""Money and invoice arithmetic for the synthetic generator.

Everything is ``Decimal`` and rounds half-up to cents, matching
``invoiceflow.contracts.money``. A standard tax invoice adds GST to the net subtotal;
a simplified invoice prints GST-inclusive prices and we derive the net and the GST
portion from the inclusive gross.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
HUNDRED = Decimal("100")


def money(value: Decimal) -> Decimal:
    """Round a Decimal to cents, half-up. Floats are refused."""
    if not isinstance(value, Decimal):
        raise TypeError(f"money() needs a Decimal, got {type(value).__name__}")
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def fmt_money(value: Decimal) -> str:
    """Format an amount the way the templates print it: ``1,080.00``."""
    return f"{money(value):,.2f}"


def fmt_plain(value: Decimal) -> str:
    """Format a quantity without trailing zeros: ``4``, ``1.5``."""
    text = format(value.normalize(), "f")
    return "0" if text in {"-0", ""} else text


def fmt_rate(rate: Decimal) -> str:
    text = format(rate.normalize(), "f")
    return f"{text}%"


@dataclass(frozen=True)
class Totals:
    """The numbers printed on a document and used in its truth file."""

    net: Decimal
    printed_subtotal: Decimal
    gst: Decimal
    total: Decimal

    @property
    def gross(self) -> Decimal:
        return money(self.net + self.gst)


def compute_totals(
    line_amounts: tuple[Decimal, ...],
    *,
    gst_rate_percent: Decimal,
    simplified: bool = False,
    total_override: Decimal | None = None,
) -> Totals:
    """Calculate subtotal, GST, and total from line amounts.

    Standard: ``subtotal = sum(lines)``, ``GST = subtotal * rate``, ``total = subtotal + GST``.
    Simplified: line amounts already include GST, so the printed subtotal is the gross sum
    and the net/GST split is backed out of it.
    """
    if not line_amounts:
        raise ValueError("a document needs at least one line")
    if not isinstance(gst_rate_percent, Decimal):
        raise TypeError("gst_rate_percent must be a Decimal")
    gross_lines = money(sum(line_amounts, Decimal("0")))
    if simplified:
        divisor = HUNDRED + gst_rate_percent
        net = money(gross_lines * HUNDRED / divisor)
        gst = money(gross_lines - net)
        printed = gross_lines
        total = gross_lines
    else:
        net = gross_lines
        printed = gross_lines
        gst = money(net * gst_rate_percent / HUNDRED)
        total = money(net + gst)
    if total_override is not None:
        total = money(total_override)
    return Totals(net=net, printed_subtotal=printed, gst=gst, total=total)


def format_bank_account(digits: str) -> str:
    """Print a ten-digit account as ``000-123456-7``; leave other lengths alone."""
    clean = "".join(ch for ch in digits if ch.isdigit())
    if len(clean) == 10:
        return f"{clean[:3]}-{clean[3:9]}-{clean[9:]}"
    return clean


def digits_only(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())
