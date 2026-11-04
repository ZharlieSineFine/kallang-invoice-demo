"""Load the fictional master data from ``seeds/``.

The CSVs are the canonical master data for the demo. UENs use year 2099 so they match the
Singapore format but cannot belong to a real company; each vendor's GST number is its UEN.
The thirteenth vendor (V999) is inactive: it exists so an unknown-vendor invoice can still
carry plausible bank details, while the generated master data leaves it out.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from generator.money import money
from invoiceflow.contracts import (
    CodingMaster,
    CompanyProfile,
    CostCenter,
    GLAccount,
    MasterData,
    PurchaseOrder,
    TaxCode,
    Vendor,
    VenueAlias,
)

_UEN_RE = re.compile(r"^2099\d{5}[A-Z]$")


@dataclass(frozen=True)
class VendorSeed:
    vendor_id: str
    sap_vendor_no: str
    name: str
    uen: str
    gst_reg_no: str
    address: str
    bank_name: str
    bank_account: str
    currency: str
    locale: str
    is_overseas: bool
    default_gl: str
    default_cost_center: str | None
    default_tax_code: str
    active: bool

    def to_contract(self) -> Vendor:
        return Vendor(
            vendor_id=self.vendor_id,
            sap_vendor_no=self.sap_vendor_no,
            name=self.name,
            uen=self.uen or None,
            gst_reg_no=self.gst_reg_no or None,
            address=self.address or None,
            bank_name=self.bank_name or None,
            bank_account=self.bank_account or None,
            currency=self.currency,
            locale=self.locale,
            is_overseas=self.is_overseas,
            default_gl=self.default_gl or None,
            default_cost_center=self.default_cost_center or None,
            default_tax_code=self.default_tax_code or None,
            active=self.active,
        )


@dataclass(frozen=True)
class PurchaseOrderSeed:
    po_number: str
    vendor_id: str
    currency: str
    amount: Decimal
    open_amount: Decimal
    gl_account: str
    cost_center: str

    def to_contract(self) -> PurchaseOrder:
        return PurchaseOrder(
            po_number=self.po_number,
            vendor_id=self.vendor_id,
            currency=self.currency,
            amount=self.amount,
            open_amount=self.open_amount,
            gl_account=self.gl_account or None,
            cost_center=self.cost_center or None,
        )


@dataclass(frozen=True)
class Seeds:
    vendors: tuple[VendorSeed, ...]
    purchase_orders: tuple[PurchaseOrderSeed, ...]
    cost_centers: tuple[CostCenter, ...]
    gl_accounts: tuple[GLAccount, ...]
    tax_codes: tuple[TaxCode, ...]
    venue_aliases: tuple[VenueAlias, ...]

    def vendor(self, vendor_id: str) -> VendorSeed:
        found = next((v for v in self.vendors if v.vendor_id == vendor_id), None)
        if found is None:
            raise KeyError(f"unknown vendor in seeds: {vendor_id}")
        return found

    def active_vendors(self) -> tuple[VendorSeed, ...]:
        return tuple(v for v in self.vendors if v.active)

    def purchase_order(self, po_number: str) -> PurchaseOrderSeed:
        found = next((p for p in self.purchase_orders if p.po_number == po_number), None)
        if found is None:
            raise KeyError(f"unknown purchase order in seeds: {po_number}")
        return found

    def gl_name(self, code: str | None) -> str:
        return next((g.name for g in self.gl_accounts if g.code == code), "Purchase")

    def cost_center_for_venue(self, venue: str | None) -> str | None:
        if not venue:
            return None
        folded = " ".join(venue.split()).casefold()
        return next(
            (a.cost_center for a in self.venue_aliases if a.alias.casefold() == folded), None
        )

    def master(self, *, company: CompanyProfile) -> MasterData:
        """The master data a vendor matcher and coder would see: active vendors only."""
        active_ids = {v.vendor_id for v in self.active_vendors()}
        return MasterData(
            company=company,
            vendors=tuple(v.to_contract() for v in self.active_vendors()),
            purchase_orders=tuple(
                p.to_contract() for p in self.purchase_orders if p.vendor_id in active_ids
            ),
            coding=CodingMaster(
                gl_accounts=self.gl_accounts,
                cost_centers=self.cost_centers,
                tax_codes=self.tax_codes,
                venue_aliases=self.venue_aliases,
            ),
        )


def _read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"seed file not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _bool(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "y"}


def load_seeds(root: Path) -> Seeds:
    """Load and validate every seed CSV under ``root``."""
    base = root / "seeds"
    vendors = tuple(
        VendorSeed(
            vendor_id=row["vendor_id"].strip(),
            sap_vendor_no=row["sap_vendor_no"].strip(),
            name=row["name"].strip(),
            uen=row["uen"].strip(),
            gst_reg_no=row["gst_reg_no"].strip(),
            address=row["address"].strip(),
            bank_name=row["bank_name"].strip(),
            bank_account=row["bank_account"].strip(),
            currency=row["currency"].strip(),
            locale=row["locale"].strip(),
            is_overseas=_bool(row["is_overseas"]),
            default_gl=row["default_gl"].strip(),
            default_cost_center=row["default_cost_center"].strip() or None,
            default_tax_code=row["default_tax_code"].strip(),
            active=_bool(row["active"]),
        )
        for row in _read(base / "vendors.csv")
    )
    _validate_vendors(vendors)
    purchase_orders = tuple(
        PurchaseOrderSeed(
            po_number=row["po_number"].strip(),
            vendor_id=row["vendor_id"].strip(),
            currency=row["currency"].strip(),
            amount=money(Decimal(row["amount"])),
            open_amount=money(Decimal(row["open_amount"])),
            gl_account=row["gl_account"].strip(),
            cost_center=row["cost_center"].strip(),
        )
        for row in _read(base / "purchase_orders.csv")
    )
    cost_centers = tuple(
        CostCenter(code=row["code"].strip(), name=row["name"].strip())
        for row in _read(base / "cost_centers.csv")
    )
    gl_accounts = tuple(
        GLAccount(code=row["code"].strip(), name=row["name"].strip())
        for row in _read(base / "gl_accounts.csv")
    )
    tax_codes = tuple(
        TaxCode(
            code=row["code"].strip(),
            rate_percent=Decimal(row["rate_percent"]),
            description=row["description"].strip(),
        )
        for row in _read(base / "tax_codes.csv")
    )
    venue_aliases = tuple(
        VenueAlias(alias=row["alias"].strip(), cost_center=row["cost_center"].strip())
        for row in _read(base / "venue_cost_centers.csv")
    )
    _validate_master(purchase_orders, cost_centers, gl_accounts, tax_codes, venue_aliases)
    return Seeds(
        vendors=vendors,
        purchase_orders=purchase_orders,
        cost_centers=cost_centers,
        gl_accounts=gl_accounts,
        tax_codes=tax_codes,
        venue_aliases=venue_aliases,
    )


def _validate_vendors(vendors: tuple[VendorSeed, ...]) -> None:
    ids = [v.vendor_id for v in vendors]
    if len(ids) != len(set(ids)):
        raise ValueError("vendors.csv has duplicate vendor ids")
    uens = [v.uen for v in vendors if v.uen]
    if len(uens) != len(set(uens)):
        raise ValueError("vendors.csv has duplicate UENs")
    for vendor in vendors:
        if vendor.uen and not _UEN_RE.match(vendor.uen):
            raise ValueError(f"UEN is not a fictional 2099 UEN: {vendor.uen}")
        if vendor.uen and vendor.gst_reg_no and vendor.gst_reg_no != vendor.uen:
            raise ValueError(f"GST number must equal the UEN for {vendor.vendor_id}")
        if vendor.bank_account and not vendor.bank_account.isdigit():
            raise ValueError(f"bank account must be digits only for {vendor.vendor_id}")
    if sum(1 for v in vendors if v.active) != 12:
        raise ValueError("the demo needs exactly 12 active vendors")
    if not any(not v.active for v in vendors):
        raise ValueError("vendors.csv needs one inactive unknown vendor")


def _validate_master(
    purchase_orders: tuple[PurchaseOrderSeed, ...],
    cost_centers: tuple[CostCenter, ...],
    gl_accounts: tuple[GLAccount, ...],
    tax_codes: tuple[TaxCode, ...],
    venue_aliases: tuple[VenueAlias, ...],
) -> None:
    centers = {c.code for c in cost_centers}
    accounts = {g.code for g in gl_accounts}
    taxes = {t.code for t in tax_codes}
    for po in purchase_orders:
        if po.gl_account not in accounts:
            raise ValueError(f"PO {po.po_number} uses unknown GL {po.gl_account}")
        if po.cost_center not in centers:
            raise ValueError(f"PO {po.po_number} uses unknown cost center {po.cost_center}")
        if po.open_amount > po.amount:
            raise ValueError(f"PO {po.po_number} open amount exceeds its amount")
    for alias in venue_aliases:
        if alias.cost_center not in centers:
            raise ValueError(f"venue {alias.alias!r} maps to unknown cost center")
    if not taxes:
        raise ValueError("tax_codes.csv is empty")
