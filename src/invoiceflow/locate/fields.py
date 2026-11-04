"""Which extraction fields are located, and the labels that help disambiguate duplicates.

The header list follows the golden fixture's evidence set: the values the review screen and
R01 need a box for. Line items carry their description and amount, the two fields the
arithmetic checks point at.
"""

from __future__ import annotations

LOCATABLE_HEADER_FIELDS: tuple[str, ...] = (
    "invoice_number",
    "invoice_date",
    "due_date",
    "supplier_name",
    "supplier_uen",
    "supplier_gst_reg_no",
    "buyer_name",
    "po_number",
    "currency",
    "venue",
    "subtotal",
    "gst_rate",
    "gst_amount",
    "total",
    "supplier_address",
    "bank_account",
)

LINE_ITEM_FIELDS: tuple[str, ...] = ("description", "amount")

FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "invoice_number": ("invoice no", "invoice number", "inv no"),
    "invoice_date": ("invoice date",),
    "due_date": ("due date",),
    "supplier_name": ("supplier", "seller", "from"),
    "supplier_uen": ("uen", "uen no", "company reg no"),
    "supplier_gst_reg_no": (
        "gst reg no",
        "gst registration no",
        "gst reg",
        "gst no",
    ),
    "buyer_name": ("bill to", "billed to", "buyer", "customer"),
    "buyer_address": ("bill to", "billed to", "buyer address", "address"),
    "po_number": ("po no", "po number", "purchase order", "po"),
    "contract_number": ("contract no", "contract number", "contract"),
    "currency": ("currency",),
    "venue": ("venue",),
    "subtotal": ("subtotal", "sub total", "total"),
    "discount": ("discount",),
    "gst_rate": ("gst rate", "gst"),
    "gst_amount": ("gst amount", "gst", "tax"),
    "total": ("total payable", "amount payable", "total due", "grand total", "total"),
    "amount_due": ("amount due", "total due", "balance due"),
    "sgd_total": ("sgd total", "total sgd", "sgd"),
    "sgd_gst_amount": ("sgd gst", "gst sgd"),
    "original_invoice_ref": ("original invoice", "original invoice no"),
    "bank_account": ("bank account", "account no", "account"),
    "title": ("title",),
    "payment_terms": ("payment terms", "terms"),
    "service_period": ("service period", "event dates"),
}
