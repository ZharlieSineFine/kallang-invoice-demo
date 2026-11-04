from invoiceflow.contracts import InvoiceExtraction, Vendor
from invoiceflow.normalize import VendorMatcher

STAGECRAFT = Vendor(
    vendor_id="V001",
    sap_vendor_no="100014",
    name="Stagecraft AV Rentals Pte. Ltd.",
    uen="209900123K",
    gst_reg_no="209900123K",
    active=True,
)
OTHER = Vendor(
    vendor_id="V002",
    sap_vendor_no="100015",
    name="Kallang Catering Services",
    uen="200812345M",
    gst_reg_no="200812345M",
    active=True,
)
VENDORS = (STAGECRAFT, OTHER)


def _extraction(**overrides) -> InvoiceExtraction:
    values = {"supplier_name": None, "supplier_uen": None, "supplier_gst_reg_no": None}
    values.update(overrides)
    return InvoiceExtraction(**values)


def test_matcher_implements_the_protocol():
    from invoiceflow.contracts import VendorMatcher as VendorMatcherProtocol

    assert isinstance(VendorMatcher(), VendorMatcherProtocol)


def test_matches_gst_number_before_name():
    extraction = _extraction(
        supplier_name="Entirely Different Name",
        supplier_gst_reg_no="2099 00123 K",
    )

    assert VendorMatcher().match(extraction, VENDORS) == STAGECRAFT


def test_matches_uen_with_hyphens_removed():
    extraction = _extraction(supplier_uen="2099-00123-K")

    assert VendorMatcher().match(extraction, VENDORS) == STAGECRAFT


def test_gst_number_wins_over_a_fuzzy_name_match():
    extraction = _extraction(
        supplier_name="Kallang Catering Services",
        supplier_gst_reg_no="2008-12345-M",
    )

    assert VendorMatcher().match(extraction, VENDORS) == OTHER


def test_falls_back_to_a_fuzzy_name_match():
    extraction = _extraction(supplier_name="Stagecraft AV Rental Pte Ltd")

    assert VendorMatcher().match(extraction, VENDORS) == STAGECRAFT


def test_returns_none_when_nothing_matches():
    extraction = _extraction(
        supplier_name="Completely Unrelated Vendor",
        supplier_uen="999999999X",
    )

    assert VendorMatcher().match(extraction, VENDORS) is None
    assert VendorMatcher().match(_extraction(), VENDORS) is None


def test_inactive_vendors_are_still_compared_by_id():
    inactive = STAGECRAFT.model_copy(update={"active": False})
    extraction = _extraction(supplier_gst_reg_no="209900123K")

    assert VendorMatcher().match(extraction, (inactive,)) == inactive
