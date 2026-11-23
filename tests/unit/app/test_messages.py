"""An action's result pops up in the corner and shows as a colored card next to the button
that was pressed, so a person never scrolls back to the top to read it (user's requests,
2026-11-20). The card names the invoice, its vendor and total, and what happens next."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest
from test_pages import _run, _script, _set_doc

from app.pages import review

_PAGE = """
import streamlit as st
from app import ui
from app.notice import Notice, Tone
if not st.session_state.get("acted"):
    st.session_state["acted"] = True
    ui.flash(Notice(Tone.SUCCESS, "Approved SAV-1"), at=__kwargs.get("at"))
ui.show_flash()
st.markdown("other buttons")
ui.show_result("decision:other")
st.markdown("decision buttons")
ui.show_result("decision:1")
"""


def _page(at_value):
    at = AppTest(_script(_PAGE), default_timeout=30, kwargs={"at": at_value})
    return at.run(timeout=30)


def _markdown(at) -> list[str]:
    return [item.value for item in at.markdown]


def _popups(at) -> list[str]:
    return [value for value in _markdown(at) if 'data-notice="popup"' in value]


def _cards(at) -> list[str]:
    return [value for value in _markdown(at) if 'data-notice="card"' in value]


def _position(at, text: str) -> int:
    return next(i for i, value in enumerate(_markdown(at)) if text in value)


def test_the_message_pops_up_and_sits_under_its_own_buttons():
    at = _page("decision:1")
    assert len(_popups(at)) == 1 and "Approved SAV-1" in _popups(at)[0]
    assert len(_cards(at)) == 1 and "Approved SAV-1" in _cards(at)[0]
    assert _position(at, 'data-notice="card"') > _position(at, "decision buttons")


def test_the_pop_up_shows_once_but_the_card_stays_until_the_next_action():
    at = _page("decision:1")
    at.run(timeout=30)
    assert not _popups(at)
    assert len(_cards(at)) == 1


def test_a_message_with_no_place_of_its_own_shows_at_the_top_once():
    at = _page(None)
    assert _popups(at)
    assert _position(at, 'data-notice="card"') < _position(at, "other buttons")
    at.run(timeout=30)
    assert not _cards(at)


def test_approve_on_review_names_the_invoice(fake_backend, mismatch_bundle):
    doc = mismatch_bundle.document
    at = _set_doc(_run(review, fake_backend), doc.doc_id)
    at.run(timeout=30)
    at.get_by_key("btn_approve").click().run(timeout=30)
    (popup,) = _popups(at)
    (card,) = _cards(at)
    for html in (popup, card):
        assert f"Approved {doc.invoice_number}" in html
        assert doc.vendor_name in html
    assert 'data-tone="success"' in card
    assert "next SAP export" in card


def test_reject_is_green_and_says_it_will_not_be_paid(fake_backend, mismatch_bundle):
    # The user's report: Reject said only "Rejected", without naming what was rejected.
    doc = mismatch_bundle.document
    at = _set_doc(_run(review, fake_backend), doc.doc_id)
    at.run(timeout=30)
    at.get_by_key("btn_reject").click().run(timeout=30)
    (card,) = _cards(at)
    assert f"Rejected {doc.invoice_number}" in card
    assert 'data-tone="success"' in card
    assert 'data-status="REJECTED"' in card
    assert "never exported or paid" in card
    assert "Recorded under demo.reviewer" in card


def test_a_correction_names_the_field_and_what_the_checks_found(fake_backend, mismatch_bundle):
    doc_id = mismatch_bundle.document.doc_id
    at = _set_doc(_run(review, fake_backend), doc_id)
    at.run(timeout=30)
    at.get_by_key("review_field").set_value("subtotal").run()
    at.get_by_key(f"fix_value_{doc_id}_subtotal").set_value("1,080.00").run()
    at.get_by_key("btn_correct").click().run(timeout=30)
    assert _popups(at)
    (card,) = _cards(at)
    assert f"Corrected subtotal on {mismatch_bundle.document.invoice_number}" in card
    assert "Checks rerun" in card


def test_a_refused_action_is_red_and_says_why(on_hold_backend, mismatch_bundle):
    doc_id = mismatch_bundle.document.doc_id
    at = _set_doc(_run(review, on_hold_backend), doc_id)
    at.run(timeout=30)
    at.get_by_key("btn_release").click().run(timeout=30)
    (card,) = _cards(at)
    assert 'data-tone="error"' in card
    assert "Could not release the hold on" in card
    assert "comment" in card
