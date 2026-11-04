"""Enumerations shared by every workstream. Values are stored as-is in Postgres."""

from enum import StrEnum


class FileKind(StrEnum):
    PDF = "PDF"
    IMAGE = "IMAGE"
    PEPPOL_XML = "PEPPOL_XML"
    XLSX = "XLSX"
    UNKNOWN = "UNKNOWN"


class TextSource(StrEnum):
    PDF_TEXT = "PDF_TEXT"
    OCR = "OCR"
    EINVOICE = "EINVOICE"


class DocType(StrEnum):
    TAX_INVOICE = "TAX_INVOICE"
    SIMPLIFIED_TAX_INVOICE = "SIMPLIFIED_TAX_INVOICE"
    INVOICE = "INVOICE"  # no GST charged, e.g. a supplier that is not GST-registered
    CREDIT_NOTE = "CREDIT_NOTE"
    DEBIT_NOTE = "DEBIT_NOTE"
    STATEMENT = "STATEMENT"
    QUOTATION = "QUOTATION"
    DELIVERY_ORDER = "DELIVERY_ORDER"
    OTHER = "OTHER"


class DocStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PARSED = "PARSED"
    EXTRACTED = "EXTRACTED"
    AUTO_PASSED = "AUTO_PASSED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ON_HOLD = "ON_HOLD"
    MANUAL_ENTRY = "MANUAL_ENTRY"
    NOT_INVOICE = "NOT_INVOICE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPORTED = "EXPORTED"


class Severity(StrEnum):
    """How serious a finding is. ``rank`` orders them; the router uses the highest."""

    INFO = "INFO"
    FLAG = "FLAG"
    HOLD = "HOLD"
    MANUAL = "MANUAL"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {Severity.INFO: 0, Severity.FLAG: 1, Severity.HOLD: 2, Severity.MANUAL: 3}


class Scope(StrEnum):
    """FIELD findings name a field path such as ``subtotal`` or ``line_items[2].amount``."""

    FIELD = "FIELD"
    DOCUMENT = "DOCUMENT"


class Stage(StrEnum):
    """Where a finding was produced (the AG-121 idea of phase)."""

    INTAKE = "INTAKE"
    REVIEW = "REVIEW"
    EXPORT = "EXPORT"


class MatchType(StrEnum):
    EXACT = "EXACT"
    NUMERIC = "NUMERIC"
    FUZZY = "FUZZY"
    NONE = "NONE"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ValueSource(StrEnum):
    MODEL = "MODEL"
    REVIEWER = "REVIEWER"
    EINVOICE = "EINVOICE"


class CodingSource(StrEnum):
    PO = "PO"
    VENUE = "VENUE"
    VENDOR_DEFAULT = "VENDOR_DEFAULT"
    REVIEWER = "REVIEWER"
    NONE = "NONE"


class LLMMode(StrEnum):
    LIVE = "LIVE"
    REPLAY = "REPLAY"


class ReviewAction(StrEnum):
    CONFIRM = "CONFIRM"
    CORRECT = "CORRECT"
    RECODE = "RECODE"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RELEASE_HOLD = "RELEASE_HOLD"
