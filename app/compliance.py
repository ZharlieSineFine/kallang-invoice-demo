"""Why each check exists. Citations were read from the source on 2026-11-04.

``kind`` separates what a regulator or standard says from PTC's own controls, so the demo never
presents an internal rule as a legal requirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

_IRAS = (
    "https://www.iras.gov.sg/taxes/goods-services-tax-(gst)/basics-of-gst/"
    "invoicing-price-display-and-record-keeping/invoicing-customers"
)
_SPF = (
    "https://www.police.gov.sg/Media-Hub/News/2026/05/"
    "20260520_police_advisory_on_business_email_compromise_scams_involving_requests_to_update_vendors"
)
_OWASP = "https://genai.owasp.org/llmrisk/llm01-prompt-injection/"


@dataclass(frozen=True)
class ComplianceCard:
    rule_id: str
    title: str
    requirement: str
    source: str
    kind: str
    url: str | None = None


def _internal(rule_id: str, title: str, requirement: str, source: str) -> ComplianceCard:
    return ComplianceCard(rule_id, title, requirement, source, "Internal control")


CARDS: dict[str, ComplianceCard] = {
    card.rule_id: card
    for card in (
        ComplianceCard(
            "R01",
            "Every value is on the page",
            "AI output must be grounded in the source document, with validation checks and "
            "human review where necessary.",
            "Kallang Track 10 brief: AI guardrails",
            "Client requirement",
        ),
        ComplianceCard(
            "R02",
            "The amounts add up",
            "A tax invoice must show the total before GST, the GST amount, and the total with "
            "GST. This check confirms that they agree with the line items.",
            "IRAS: Invoicing customers",
            "Regulator",
            _IRAS,
        ),
        ComplianceCard(
            "R03",
            "GST is right",
            "GST is 9%. A simplified tax invoice is allowed only when the total with GST is "
            "S$1,000 or less. A foreign-currency tax invoice must also show its amounts in "
            "Singapore dollars.",
            "IRAS: Invoicing customers",
            "Regulator",
            _IRAS,
        ),
        _internal(
            "R04",
            "Known vendor, right addressee",
            "Pay only vendors in the vendor master, on invoices addressed to a Kallang entity.",
            "PTC control, for Kallang to confirm",
        ),
        _internal(
            "R05",
            "Not a duplicate",
            "The same bill must not be paid twice: same file, same vendor and invoice number, "
            "or same vendor and amount within 7 days.",
            "PTC control, for Kallang to confirm",
        ),
        _internal(
            "R06",
            "SAP can accept it",
            "Every required column, including GL account, cost center, and tax code, must be "
            "filled before export.",
            "Hypothetical SAP layout, to be replaced by Kallang's template",
        ),
        _internal(
            "R07",
            "The file can be read",
            "A document that cannot be read reliably goes to manual entry instead of being "
            "guessed.",
            "PTC control, for Kallang to confirm",
        ),
        ComplianceCard(
            "R08",
            "Bank details match the vendor master",
            "Treat requests to change a vendor's bank account as a red flag and verify them "
            "through another channel. At least 66 cases and at least S$19 million in losses "
            "were reported from 1 January 2026 to the advisory's date.",
            "Singapore Police Force advisory, 20 May 2026",
            "Advisory",
            _SPF,
        ),
        ComplianceCard(
            "R09",
            "No hidden instructions",
            "Files are a source of indirect prompt injection. Separate untrusted content and "
            "keep a person in control of privileged actions.",
            "OWASP LLM01:2025 Prompt Injection",
            "Standard",
            _OWASP,
        ),
        ComplianceCard(
            "R10",
            "Is it really an invoice?",
            "A credit note must show the number and date of the original tax invoice. This "
            "check also keeps statements and quotations out of the export.",
            "IRAS: Invoicing customers",
            "Regulator",
            _IRAS,
        ),
        _internal(
            "R11",
            "The dates make sense",
            "The invoice date is not in the future or over 180 days old, the due date follows "
            "it, and day and month cannot be confused.",
            "PTC control, for Kallang to confirm",
        ),
        _internal(
            "R12",
            "The purchase order covers it",
            "The PO exists, belongs to the same vendor, and has enough open amount left.",
            "PTC control, for Kallang to confirm",
        ),
    )
}


def card_for(rule_id: str) -> ComplianceCard | None:
    return CARDS.get(rule_id)


def card_html(card: ComplianceCard) -> str:
    source = escape(card.source)
    if card.url:
        source = (
            f'<a href="{escape(card.url)}" target="_blank" rel="noopener" '
            f'style="color:#1565c0;">{source}</a>'
        )
    return (
        '<div style="background:#f4f6fb;border-left:4px solid #1565c0;padding:0.6rem 0.9rem;'
        'border-radius:6px;margin-bottom:0.6rem;color:#1f2328;">'
        f'<div style="font-size:0.75rem;color:#5a6068;">Why {escape(card.rule_id)} exists · '
        f"{escape(card.kind)}</div>"
        f'<div style="font-weight:600;color:#1f2328;">{escape(card.title)}</div>'
        f'<div style="margin-top:0.2rem;color:#1f2328;">{escape(card.requirement)}</div>'
        f'<div style="margin-top:0.3rem;font-size:0.85rem;color:#5a6068;">{source}</div></div>'
    )
