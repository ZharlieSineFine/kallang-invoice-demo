"""The "Check the discarded copy" panel, shared by Demo Step 1 and the Queue page.

Intake discards a file only when its bytes match a file it already stores, so the evidence
is the fingerprint (SHA-256). The panel puts the copy's fingerprint beside the original's
and gives the commands to recompute it outside the app.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Sequence
from uuid import UUID

import pandas as pd
import streamlit as st

from app import ui
from app.formatting import format_time
from app.models import DiscardedCopy

ROW_LABELS = ("File name", "Arrived", "Fingerprint")
_UNKNOWN = "—"


def short_fingerprint(sha256: str) -> str:
    return f"{sha256[:8]}…{sha256[-6:]}"


def comparison_rows(copy: DiscardedCopy) -> dict[str, list[str]]:
    original = copy.original
    return {
        "Discarded copy": [
            copy.name or _UNKNOWN,
            format_time(copy.arrived_at) if copy.arrived_at else _UNKNOWN,
            short_fingerprint(copy.sha256),
        ],
        "Kept original": [
            original.file_name or _UNKNOWN,
            format_time(original.received_at) if original.received_at else _UNKNOWN,
            short_fingerprint(copy.kept_sha256),
        ],
    }


def check_commands(copy: DiscardedCopy) -> tuple[str, str]:
    """(Mac, Windows) commands that print a file's SHA-256 fingerprint."""
    name = copy.name or "the file"
    return f'shasum -a 256 "{name}"', f'certutil -hashfile "{name}" SHA256'


def _open_review(doc_id: UUID) -> None:
    """Runs before widgets are instantiated, so it may legally flip the page key."""
    st.session_state["selected_doc_id"] = doc_id
    st.session_state["page"] = "Review"


def _verdict(copy: DiscardedCopy) -> None:
    if copy.is_identical:
        st.success("Same fingerprint: the two files are identical, byte for byte.")
    else:
        st.warning("The fingerprints do not match, so these two files are not exact copies.")


def _original_actions(copy: DiscardedCopy, key: str) -> None:
    original = copy.original
    number = original.invoice_number or "no invoice number"
    st.caption(f"Kept original: {original.status.value} · invoice {number}")
    if st.button(
        "Open the original in Review",
        key=f"{key}_open",
        on_click=_open_review,
        args=(original.doc_id,),
    ):
        st.rerun()
    path = ui.resolve_path(original.file_path)
    if path is None or not path.is_file():
        st.caption("The stored original is not on this computer, so it cannot be downloaded here.")
        return
    name = original.file_name or path.name  # stored files are named by fingerprint alone
    st.download_button(
        "Download the kept original",
        data=path.read_bytes(),
        file_name=name,
        mime=mimetypes.guess_type(name)[0] or "application/octet-stream",
        key=f"{key}_download",
    )


def _check_yourself(copy: DiscardedCopy) -> None:
    mac, windows = check_commands(copy)
    st.markdown("**Check it yourself.** In the folder that holds the copy, run:")
    st.caption("Mac (Terminal)")
    st.code(mac, language="bash")
    st.caption("Windows (Command Prompt)")
    st.code(windows, language="bat")
    st.caption("The result should be this fingerprint. The downloaded original gives the same.")
    st.code(copy.kept_sha256, language=None)


def _render_copy(copy: DiscardedCopy, key: str) -> None:
    st.table(pd.DataFrame(comparison_rows(copy), index=list(ROW_LABELS)))
    _verdict(copy)
    _original_actions(copy, key)
    _check_yourself(copy)


def render_discarded_copies(copies: Sequence[DiscardedCopy], *, key: str) -> None:
    if not copies:
        return
    noun = "copy" if len(copies) == 1 else "copies"
    with st.expander(f"Check the discarded {noun} ({len(copies)})"):
        st.caption(
            "Intake discards a file only when every byte matches a file it already holds. "
            "The fingerprint is worked out from every byte, so identical fingerprints mean "
            "identical files. A re-scanned or re-saved invoice is not discarded; the "
            "duplicate-number check puts it on hold for a person instead."
        )
        for index, copy in enumerate(copies):
            if index:
                st.divider()
            _render_copy(copy, f"{key}_{index}")
