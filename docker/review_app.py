"""Placeholder review app (WS6). WS7 replaces this with the real ``app/app.py`` UI.

Kept in ``docker/`` so ``make up`` has something to serve on 127.0.0.1:8501 before WS7
ships. It proves the review-app -> ap database path by listing the silver documents.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Kallang invoice review", layout="wide")
st.title("Kallang invoice review")
st.caption("Placeholder served by WS6 — WS7's real review UI lands in ``app/app.py``.")

try:
    from invoiceflow.contracts import DocStatus
    from invoiceflow.store.connection import connect
    from invoiceflow.store.repo import Repo

    with connect(connect_timeout=3) as conn:
        docs = Repo(conn).list_documents(tuple(DocStatus))
    st.metric("documents in silver", len(docs))
    if docs:
        st.table(
            [
                {"doc_id": str(d.doc_id), "status": d.status.value, "vendor": d.vendor_id or ""}
                for d in docs
            ]
        )
    else:
        st.info("No documents yet. Run `make fixtures` or drop a PDF into data/inbox/.")
except Exception as exc:
    st.warning(f"ap database not reachable yet: {exc}")
