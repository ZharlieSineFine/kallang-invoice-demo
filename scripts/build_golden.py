"""Build the two golden fixtures in tests/fixtures/golden/ (run: make golden).

Each fixture is a type A invoice (event equipment rental) rendered to a real PDF, plus:
page-1.png, page-1.words.json, extraction.json (a recorded model response),
locations.json, truth.json, and expected_findings.json. master.json holds the master data.

The twin prints a "Total" (subtotal) of 1,090.00 while its lines add up to 1,080.00;
GST and the amount payable follow the printed subtotal, so only R02 should fire.
All names, numbers, and accounts are fictional.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pdfplumber
import pypdfium2
from jinja2 import Template
from weasyprint import HTML

from invoiceflow.contracts import (
    SCHEMA_VERSION,
    BBox,
    CodingLine,
    CodingMaster,
    CodingSource,
    CompanyProfile,
    CostCenter,
    DocStatus,
    DocType,
    ExtractedLineItem,
    ExtractionResult,
    FieldLocation,
    Finding,
    GLAccount,
    InvoiceExtraction,
    InvoiceTruth,
    LLMMode,
    MasterData,
    MatchType,
    NormalizedInvoice,
    NormalizedLineItem,
    PageText,
    PurchaseOrder,
    Scope,
    Severity,
    TaxCode,
    TextSource,
    Vendor,
    VenueAlias,
    Word,
)
from invoiceflow.settings import golden_dir, load_config, repo_root

RECORDED_AT = datetime(2026, 11, 4, tzinfo=UTC)
LINES = (  # no, description, qty, unit, days, unit price, amount
    ("1", "LED wall panel rental", "4", "pcs", "3", "45.00", "540.00"),
    ("2", "Line array speaker rental", "2", "pcs", "3", "50.00", "300.00"),
    ("3", "AV technician", "4", "hr", None, "40.00", "160.00"),
    ("4", "Transport and setup", "1", "lot", None, "80.00", "80.00"),
)
VENDOR = Vendor(
    vendor_id="V001",
    sap_vendor_no="100014",
    name="Stagecraft AV Rentals Pte. Ltd.",
    uen="209900123K",
    gst_reg_no="209900123K",
    address="18 Fictional Lane #04-12, Singapore 399999",
    bank_name="DBS Bank",
    bank_account="0001234567",
    default_gl="610200",
    default_cost_center="KG2100",
    default_tax_code="TX",
)
PO = PurchaseOrder(
    po_number="4500012345",
    vendor_id="V001",
    amount=Decimal("5000.00"),
    open_amount=Decimal("5000.00"),
    gl_account="610200",
    cost_center="KG1100",
)


@dataclass(frozen=True)
class Spec:
    fixture_id: str
    invoice_number: str
    subtotal: str
    gst: str
    total: str
    expected_status: DocStatus
    findings: tuple[Finding, ...]


SPECS = (
    Spec(
        "golden-a-clean",
        "SAV-2026-0412",
        "1,080.00",
        "97.20",
        "1,177.20",
        DocStatus.AUTO_PASSED,
        (),
    ),
    Spec(
        "golden-a-total-mismatch",
        "SAV-2026-0413",
        "1,090.00",
        "98.10",
        "1,188.10",
        DocStatus.NEEDS_REVIEW,
        (
            Finding(
                rule_id="R02",
                rule_version="golden",
                severity=Severity.FLAG,
                scope=Scope.FIELD,
                field="subtotal",
                message="The line items add up to S$1,080.00, but the subtotal reads S$1,090.00.",
                evidence={"lines_sum": "1080.00", "subtotal": "1090.00"},
            ),
        ),
    ),
)

TEMPLATE = Template("""<!doctype html><html><head><meta charset="utf-8"><style>
@page { size: A4; margin: 18mm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 9.5pt; color: #222; }
.vendor { font-size: 15pt; font-weight: bold; }
.title { font-size: 16pt; font-weight: bold; text-align: right; margin-top: -30px; }
.row { display: flex; justify-content: space-between; margin-top: 14px; }
table { width: 100%; border-collapse: collapse; margin-top: 18px; }
th, td { border-bottom: 1px solid #ccc; padding: 5px 4px; text-align: left; }
td.n, th.n { text-align: right; }
.totals { width: 45%; margin-left: 55%; margin-top: 10px; }
.totals td { border: none; padding: 3px 4px; }
.footer { margin-top: 30px; font-size: 8.5pt; color: #444; }
</style></head><body>
<div class="vendor">{{ v.name }}</div>
<div>{{ v.address }}</div>
<div>UEN: {{ v.uen }} &nbsp; GST Reg No: {{ v.gst_reg_no }}</div>
<div class="title">TAX INVOICE</div>
<div class="row">
 <div><b>Bill To:</b><br>The Kallang Group<br>Kallang, Singapore</div>
 <div>Invoice No: {{ s.invoice_number }}<br>Invoice Date: 15/10/2026<br>
  Due Date: 14/11/2026<br>Terms: 30 days<br>PO No: {{ po }}<br>Currency: SGD</div>
</div>
<div style="margin-top:10px">Event: Concert load-in &nbsp; Venue: National Stadium &nbsp;
 Event dates: 12-14 Oct 2026</div>
<table><tr><th>No</th><th>Description</th><th class="n">Qty</th><th>Unit</th>
<th class="n">Days</th><th class="n">Unit Price</th><th class="n">Amount</th></tr>
{% for l in lines %}<tr><td>{{ l[0] }}</td><td>{{ l[1] }}</td><td class="n">{{ l[2] }}</td>
<td>{{ l[3] }}</td><td class="n">{{ l[4] or "" }}</td><td class="n">{{ l[5] }}</td>
<td class="n">{{ l[6] }}</td></tr>{% endfor %}
</table>
<table class="totals">
<tr><td>Total</td><td class="n">{{ s.subtotal }}</td></tr>
<tr><td>GST 9%</td><td class="n">{{ s.gst }}</td></tr>
<tr><td><b>Total Payable</b></td><td class="n"><b>{{ s.total }}</b></td></tr>
</table>
<div class="footer">Payment by bank transfer to DBS Bank, Account: 000-123456-7<br>
 Please quote the invoice number.</div>
</body></html>""")


def _ids(fixture_id: str) -> tuple:
    return (
        uuid5(NAMESPACE_URL, f"invoiceflow:golden:{fixture_id}:doc"),
        uuid5(NAMESPACE_URL, f"invoiceflow:golden:{fixture_id}:file"),
        uuid5(NAMESPACE_URL, f"invoiceflow:golden:{fixture_id}:extraction"),
    )


def _dump(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _words(pdf_path: Path) -> tuple[float, float, tuple[Word, ...]]:
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        width, height = float(page.width), float(page.height)
        words = tuple(
            Word(
                text=w["text"],
                bbox=BBox(
                    x0=max(0.0, w["x0"] / width),
                    y0=max(0.0, w["top"] / height),
                    x1=min(1.0, w["x1"] / width),
                    y1=min(1.0, w["bottom"] / height),
                ),
            )
            for w in page.extract_words()
        )
    return width, height, words


def _find(
    words,
    value: str,
    after: tuple[str, ...] = (),
    row: float | None = None,
    rightmost: bool = False,
):
    """Return the bbox of the word run equal to ``value`` (a crude locator, fixtures only)."""
    target = value.split()
    hits = []
    for i in range(len(words) - len(target) + 1):
        run = words[i : i + len(target)]
        if [w.text for w in run] != target:
            continue
        if after and [w.text for w in words[max(0, i - len(after)) : i]] != list(after):
            continue
        if row is not None and abs((run[0].bbox.y0 + run[0].bbox.y1) / 2 - row) > 0.006:
            continue
        box = run[0].bbox
        for w in run[1:]:
            box = box.union(w.bbox)
        hits.append(box)
    if not hits:
        return None
    return max(hits, key=lambda b: b.x0) if rightmost else hits[0]


def _locations(words, ext: InvoiceExtraction) -> tuple[FieldLocation, ...]:
    labels = {
        "invoice_number": ("No:",),
        "invoice_date": ("Date:",),
        "due_date": ("Date:",),
        "supplier_uen": ("UEN:",),
        "supplier_gst_reg_no": ("No:",),
        "po_number": ("No:",),
        "currency": ("Currency:",),
        "subtotal": ("Total",),
        "gst_amount": ("9%",),
        "total": ("Payable",),
        "gst_rate": ("GST",),
    }
    out = []
    for name in (
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
    ):
        value = getattr(ext, name)
        box = _find(words, value, labels.get(name, ())) if value else None
        out.append(
            FieldLocation(
                field=name,
                page_no=1 if box else None,
                bbox=box,
                match_type=MatchType.EXACT if box else MatchType.NONE,
                score=100.0 if box else 0.0,
                matched_text=value if box else None,
            )
        )
    for i, item in enumerate(ext.line_items):
        desc_box = _find(words, item.description)
        row = (desc_box.y0 + desc_box.y1) / 2 if desc_box else None
        for attr, rightmost in (("description", False), ("amount", True)):
            value = getattr(item, attr)
            box = (
                desc_box
                if attr == "description"
                else _find(words, value, row=row, rightmost=rightmost)
            )
            out.append(
                FieldLocation(
                    field=f"line_items[{i}].{attr}",
                    page_no=1 if box else None,
                    bbox=box,
                    match_type=MatchType.EXACT if box else MatchType.NONE,
                    score=100.0 if box else 0.0,
                    matched_text=value if box else None,
                )
            )
    return tuple(out)


def _extraction(spec: Spec) -> InvoiceExtraction:
    return InvoiceExtraction(
        document_type=DocType.TAX_INVOICE,
        title="TAX INVOICE",
        invoice_number=spec.invoice_number,
        invoice_date="15/10/2026",
        due_date="14/11/2026",
        payment_terms="30 days",
        currency="SGD",
        supplier_name=VENDOR.name,
        supplier_address=VENDOR.address,
        supplier_uen="209900123K",
        supplier_gst_reg_no="209900123K",
        buyer_name="The Kallang Group",
        buyer_address="Kallang, Singapore",
        po_number=PO.po_number,
        venue="National Stadium",
        service_period="12-14 Oct 2026",
        subtotal=spec.subtotal,
        gst_rate="9%",
        gst_amount=spec.gst,
        total=spec.total,
        bank_name="DBS Bank",
        bank_account="000-123456-7",
        line_items=tuple(
            ExtractedLineItem(
                line_no=n, description=d, quantity=q, unit=u, days=days, unit_price=p, amount=a
            )
            for n, d, q, u, days, p, a in LINES
        ),
    )


def _dec(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _truth(spec: Spec, ext: InvoiceExtraction) -> InvoiceTruth:
    invoice = NormalizedInvoice(
        document_type=DocType.TAX_INVOICE,
        invoice_number=spec.invoice_number,
        invoice_date=date(2026, 10, 15),
        due_date=date(2026, 11, 14),
        currency="SGD",
        supplier_name=VENDOR.name,
        supplier_uen="209900123K",
        supplier_gst_reg_no="209900123K",
        buyer_name="The Kallang Group",
        po_number=PO.po_number,
        venue="National Stadium",
        subtotal=_dec(spec.subtotal),
        gst_rate_percent=Decimal("9"),
        gst_amount=_dec(spec.gst),
        total=_dec(spec.total),
        bank_account="0001234567",
        line_items=tuple(
            NormalizedLineItem(
                line_no=int(n),
                description=d,
                quantity=Decimal(q),
                unit=u,
                days=Decimal(days) if days else None,
                unit_price=Decimal(p),
                amount=Decimal(a),
            )
            for n, d, q, u, days, p, a in LINES
        ),
    )
    coding = CodingLine(
        line_no=1,
        gl_account="610200",
        cost_center="KG1100",
        tax_code="TX",
        net_amount=sum((Decimal(line[6]) for line in LINES), Decimal("0")),
        tax_amount=_dec(spec.gst),
        description="Equipment rental, PO 4500012345",
        source_line_nos=(1, 2, 3, 4),
        coding_source=CodingSource.PO,
    )
    return InvoiceTruth(
        document_id=spec.fixture_id,
        doc_type=DocType.TAX_INVOICE,
        template_id="golden-A",
        set_name="golden",
        printed=ext,
        invoice=invoice,
        vendor_id=VENDOR.vendor_id,
        expected_coding=(coding,),
        anomalies=("lines_vs_subtotal",) if spec.findings else (),
        expected_rules=tuple(f.rule_id for f in spec.findings),
    )


def master_data() -> MasterData:
    company = load_config("company")
    coding = CodingMaster(
        gl_accounts=tuple(
            GLAccount(code=c, name=n)
            for c, n in (
                ("610100", "Event production"),
                ("610200", "Equipment rental"),
                ("620100", "Cleaning services"),
                ("620200", "Security services"),
                ("620300", "M&E maintenance"),
                ("630100", "Repairs and consumables"),
                ("640100", "Catering"),
                ("650100", "Printing and marketing"),
            )
        ),
        cost_centers=tuple(
            CostCenter(code=c, name=n)
            for c, n in (
                ("KG1100", "National Stadium"),
                ("KG1200", "Singapore Indoor Stadium"),
                ("KG1300", "OCBC Aquatic Centre"),
                ("KG1400", "OCBC Arena"),
                ("KG1500", "Kallang Wave Mall"),
                ("KG2100", "Events"),
                ("KG3100", "Facilities Management"),
                ("KG9100", "Corporate"),
            )
        ),
        tax_codes=tuple(
            TaxCode(code=c, rate_percent=Decimal(r), description=d)
            for c, r, d in (
                ("TX", "9", "Standard-rated purchase, 9% input tax"),
                ("ZP", "0", "Zero-rated purchase"),
                ("NR", "0", "Supplier not GST-registered"),
                ("OP", "0", "Out of scope, e.g. overseas services"),
                ("BL", "9", "Input tax not claimable"),
                ("EP", "0", "Exempt purchase"),
            )
        ),
        venue_aliases=tuple(
            VenueAlias(alias=a, cost_center=c)
            for a, c in (
                ("National Stadium", "KG1100"),
                ("Singapore Indoor Stadium", "KG1200"),
                ("Indoor Stadium", "KG1200"),
                ("SIS", "KG1200"),
                ("OCBC Aquatic Centre", "KG1300"),
                ("OCBC Arena", "KG1400"),
                ("Kallang Wave Mall", "KG1500"),
            )
        ),
    )
    return MasterData(
        company=CompanyProfile(
            company_code=company["company_code"],
            currency=company["currency"],
            timezone=company["timezone"],
            entity_names=tuple(company["entity_names"]),
        ),
        vendors=(VENDOR,),
        purchase_orders=(PO,),
        coding=coding,
    )


def build(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    _dump(root / "master.json", master_data().model_dump(mode="json"))
    manifest = []
    for spec in SPECS:
        doc_id, file_id, extraction_id = _ids(spec.fixture_id)
        out = root / spec.fixture_id
        out.mkdir()
        pdf_path = out / "invoice.pdf"
        HTML(string=TEMPLATE.render(v=VENDOR, s=spec, po=PO.po_number, lines=LINES)).write_pdf(
            pdf_path
        )
        pdf = pypdfium2.PdfDocument(str(pdf_path))
        pdf[0].render(scale=150 / 72).to_pil().save(out / "page-1.png")
        pdf.close()

        width, height, words = _words(pdf_path)
        page = PageText(
            page_no=1,
            width_pt=width,
            height_pt=height,
            source=TextSource.PDF_TEXT,
            words=words,
            image_path=str((out / "page-1.png").relative_to(repo_root())),
        )
        ext = _extraction(spec)
        result = ExtractionResult(
            extraction_id=extraction_id,
            doc_id=doc_id,
            model="golden-recorded",
            prompt_version="golden",
            schema_version=SCHEMA_VERSION,
            mode=LLMMode.REPLAY,
            raw_output=ext.model_dump_json(),
            extraction=ext,
            valid=True,
            created_at=RECORDED_AT,
        )
        locations = _locations(words, ext)
        missing = [loc.field for loc in locations if loc.bbox is None]
        sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

        _dump(out / "page-1.words.json", page.model_dump(mode="json"))
        _dump(out / "extraction.json", result.model_dump(mode="json"))
        _dump(out / "locations.json", [loc.model_dump(mode="json") for loc in locations])
        _dump(out / "truth.json", _truth(spec, ext).model_dump(mode="json"))
        _dump(out / "expected_findings.json", [f.model_dump(mode="json") for f in spec.findings])
        manifest.append(
            {
                "fixture_id": spec.fixture_id,
                "doc_id": str(doc_id),
                "file_id": str(file_id),
                "sha256": sha,
                "expected_status": spec.expected_status.value,
            }
        )
        print(f"{spec.fixture_id}: {len(words)} words, not located: {missing or 'none'}")
    _dump(root / "manifest.json", manifest)


if __name__ == "__main__":
    build(golden_dir())
