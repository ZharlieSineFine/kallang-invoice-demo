"""WS8 coding: assign GL account, cost center, and tax code (build plan section 5.5).

Pure and deterministic: no database or file access. The first precedence rule that
matches wins for the GL account and cost center, and the tax code comes from the
supplier's GST status. The printed GST is authoritative and is split across the coding
lines in proportion to net amount, with any cents of rounding difference placed on the
largest line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from invoiceflow.contracts import (
    CodingLine,
    CodingMaster,
    CodingSource,
    NormalizedInvoice,
    PurchaseOrder,
    Vendor,
    money,
    money_sum,
)

_ZERO = Decimal("0")
_STANDARD_GST = Decimal("9")


def _venue_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _gst_number(invoice: NormalizedInvoice, vendor: Vendor | None) -> str | None:
    if invoice.supplier_gst_reg_no:
        return invoice.supplier_gst_reg_no
    if vendor is not None and vendor.gst_reg_no:
        return vendor.gst_reg_no
    return None


def tax_code_for(invoice: NormalizedInvoice, vendor: Vendor | None) -> str | None:
    """The tax code from the supplier's GST status (build plan section 5.5)."""
    if vendor is not None and vendor.is_overseas:
        return "OP"
    if not _gst_number(invoice, vendor):
        return "NR"
    rate = invoice.gst_rate_percent
    if rate is not None and rate == _ZERO:
        return "ZP"
    if rate is not None and rate == _STANDARD_GST:
        return "TX"
    if vendor is not None and vendor.default_tax_code:
        return vendor.default_tax_code
    return "TX"


def split_gst(total_tax: Decimal, nets: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    """Split an authoritative GST total across lines in proportion to net amounts.

    Rounds each share half-up to cents; any leftover cents go on the largest line so the
    parts always add back up to ``total_tax``.
    """
    if not nets:
        return ()
    total_net = sum(nets, _ZERO)
    if total_net <= 0:
        return (money(total_tax),) + (_ZERO,) * (len(nets) - 1)
    shares = [total_tax * net / total_net for net in nets]
    rounded = [money(share) for share in shares]
    residual = money(total_tax - sum(rounded, _ZERO))
    largest = max(range(len(nets)), key=lambda i: nets[i])
    rounded[largest] = money(rounded[largest] + residual)
    return tuple(rounded)


def _find_venue(
    master: CodingMaster, header_venue: str | None, description: str | None
) -> tuple[str | None, str | None]:
    """Return (cost_center, venue) for a line, from the header venue or the description."""
    if header_venue:
        cost_center = master.cost_center_for_venue(header_venue)
        if cost_center is not None:
            return cost_center, header_venue
    if description:
        key = _venue_key(description)
        for alias in master.venue_aliases:
            alias_key = _venue_key(alias.alias)
            if alias_key and re.search(rf"\b{re.escape(alias_key)}\b", key):
                return alias.cost_center, alias.alias
    return None, None


def _code_item(
    line_no: int,
    description: str | None,
    invoice: NormalizedInvoice,
    vendor: Vendor | None,
    po: PurchaseOrder | None,
    master: CodingMaster,
) -> tuple[str | None, str | None, CodingSource, str | None]:
    """Decide the GL account, cost center, coding source, and venue for one line."""
    if po is not None:
        return po.gl_account, po.cost_center, CodingSource.PO, None

    cost_center, venue = _find_venue(master, invoice.venue, description)
    if cost_center is not None:
        gl = vendor.default_gl if vendor is not None else None
        return gl, cost_center, CodingSource.VENUE, venue

    if vendor is not None and vendor.default_gl and vendor.default_cost_center:
        return vendor.default_gl, vendor.default_cost_center, CodingSource.VENDOR_DEFAULT, None

    return None, None, CodingSource.NONE, None


def _gl_name(master: CodingMaster, code: str | None) -> str | None:
    if code is None:
        return None
    return next((gl.name for gl in master.gl_accounts if gl.code == code), None)


def _describe(
    source: CodingSource,
    gl_code: str | None,
    master: CodingMaster,
    *,
    venue: str | None,
    po_number: str | None,
) -> str | None:
    gl_name = _gl_name(master, gl_code) or gl_code or ""
    if source is CodingSource.PO:
        return f"{gl_name}, PO {po_number}" if po_number else gl_name
    if source is CodingSource.VENUE:
        return f"{gl_name}, {venue}" if venue else gl_name
    if source is CodingSource.VENDOR_DEFAULT:
        return gl_name or None
    return None


def assign(
    invoice: NormalizedInvoice,
    vendor: Vendor | None,
    po: PurchaseOrder | None,
    master: CodingMaster,
) -> tuple[CodingLine, ...]:
    """Assign coding to an invoice. Groups lines by GL, cost center, and tax code."""
    if not invoice.line_items:
        return ()

    tax_code = tax_code_for(invoice, vendor)

    # Decode each line, then group lines that share (GL, cost center, tax code).
    GroupKey = tuple[str | None, str | None, str | None]
    GroupMember = tuple[int, CodingSource, str | None, Decimal]
    groups: dict[GroupKey, list[GroupMember]] = {}
    for item in invoice.line_items:
        gl, cost_center, source, venue = _code_item(
            item.line_no, item.description, invoice, vendor, po, master
        )
        amount = item.amount if item.amount is not None else _ZERO
        groups.setdefault((gl, cost_center, tax_code), []).append(
            (item.line_no, source, venue, amount)
        )

    lines: list[CodingLine] = []
    for (gl, cost_center, tc), members in groups.items():
        source_line_nos = tuple(line_no for line_no, _, _, _ in members)
        source = members[0][1]
        venue = members[0][2]
        net = money_sum(amount for _, _, _, amount in members)
        lines.append(
            CodingLine(
                line_no=len(lines) + 1,
                gl_account=gl,
                cost_center=cost_center,
                tax_code=tc,
                net_amount=net,
                tax_amount=_ZERO,
                description=_describe(
                    source,
                    gl,
                    master,
                    venue=venue,
                    po_number=po.po_number if po is not None else None,
                ),
                source_line_nos=source_line_nos,
                coding_source=source,
            )
        )

    # The printed GST is authoritative. Split it across taxable lines only.
    rate = master.tax_rate(tax_code) if tax_code is not None else None
    nets = tuple(line.net_amount for line in lines)
    if rate is not None and rate > _ZERO:
        taxes = split_gst(invoice.gst_amount if invoice.gst_amount is not None else _ZERO, nets)
    else:
        taxes = (_ZERO,) * len(lines)

    # On a GST-inclusive invoice the line amounts already contain the GST, so take it out.
    included = taxes if invoice.gst_inclusive else (_ZERO,) * len(lines)
    return tuple(
        line.model_copy(update={"net_amount": money(line.net_amount - inside), "tax_amount": tax})
        for line, tax, inside in zip(lines, taxes, included, strict=True)
    )


@dataclass(frozen=True)
class SapCoder:
    """The production ``Coder`` for WS8; a pure function behind a protocol method."""

    def assign(
        self,
        invoice: NormalizedInvoice,
        vendor: Vendor | None,
        po: PurchaseOrder | None,
        master: CodingMaster,
    ) -> tuple[CodingLine, ...]:
        return assign(invoice, vendor, po, master)
