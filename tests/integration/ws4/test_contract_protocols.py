from invoiceflow.contracts import Locator, Normalizer, VendorMatcher
from invoiceflow.locate import Locator as LocatorImpl
from invoiceflow.normalize import Normalizer as NormalizerImpl
from invoiceflow.normalize import VendorMatcher as VendorMatcherImpl


def test_ws4_implementations_satisfy_the_frozen_protocols():
    assert isinstance(VendorMatcherImpl(), VendorMatcher)
    assert isinstance(NormalizerImpl(), Normalizer)
    assert isinstance(LocatorImpl(), Locator)
