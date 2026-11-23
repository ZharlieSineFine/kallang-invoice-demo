"""Draw a ``Notice`` as a card next to the buttons and as a pop-up (user's choice, 2026-11-20).

The card has a thick colored bar, a tinted fill, a large icon, the headline, the invoice's
vendor and total, what happens next, who did it and when, and a tag with the new status.
It stays until the next action. The pop-up slides in at the top right with the headline and
the invoice, then fades after about seven seconds (an error stays longer). It ignores the
mouse, so it never covers a button. The HTML sets its own colors, for the forced light theme.
"""

from __future__ import annotations

from html import escape

from app.notice import Notice, Tone
from invoiceflow.contracts import DocStatus

# (fill, bar and icon, text) per tone
_TONES = {
    Tone.SUCCESS: ("#e8f5e9", "#2e7d32", "#1b5e20"),
    Tone.WARNING: ("#fff4e0", "#ef8f00", "#7a4a00"),
    Tone.ERROR: ("#fdecec", "#c62828", "#8e1414"),
    Tone.INFO: ("#e3f2fd", "#1565c0", "#0d3c7a"),
}
_ICONS = {Tone.SUCCESS: "&#10004;", Tone.WARNING: "!", Tone.ERROR: "&#10006;", Tone.INFO: "i"}
_GOOD = frozenset({DocStatus.APPROVED, DocStatus.AUTO_PASSED, DocStatus.EXPORTED})
_WAITING = frozenset({DocStatus.NEEDS_REVIEW, DocStatus.MANUAL_ENTRY})
_BAD = frozenset({DocStatus.ON_HOLD, DocStatus.REJECTED})
_POPUP_SECONDS = {Tone.ERROR: 14}
_POPUP_DEFAULT_SECONDS = 7
_KEYFRAMES = (
    "<style>@keyframes kallang-notice-in{"
    "0%{opacity:0;transform:translateX(110%);}"
    "6%{opacity:1;transform:translateX(0);}"
    "90%{opacity:1;transform:translateX(0);}"
    "100%{opacity:0;transform:translateX(0);visibility:hidden;}}</style>"
)


def _tag_colors(status: DocStatus) -> tuple[str, str]:
    if status in _GOOD:
        return "#2e7d32", "#ffffff"
    if status in _WAITING:
        return "#ef8f00", "#1f1300"
    if status in _BAD:
        return "#c62828", "#ffffff"
    return "#5a6068", "#ffffff"


def _status_tag(status: DocStatus | None) -> str:
    if status is None:
        return ""
    fill, text = _tag_colors(status)
    return (
        f'<span data-status="{status.value}" style="background:{fill};color:{text};'
        "font-size:0.72rem;font-weight:700;letter-spacing:0.06em;padding:0.2rem 0.55rem;"
        f'border-radius:999px;white-space:nowrap;">{escape(status.value.replace("_", " "))}</span>'
    )


def _icon(tone: Tone, size: float) -> str:
    _, bar, _ = _TONES[tone]
    return (
        f'<div style="flex:none;width:{size}rem;height:{size}rem;border-radius:50%;'
        f"background:{bar};color:#ffffff;display:flex;align-items:center;"
        f'justify-content:center;font-weight:800;font-size:{size * 0.5}rem;">'
        f"{_ICONS[tone]}</div>"
    )


def _line(text: str, style: str) -> str:
    return f'<div style="{style}">{escape(text)}</div>' if text else ""


def card_html(notice: Notice) -> str:
    fill, bar, text = _TONES[notice.tone]
    title = (
        '<div style="display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap;">'
        f'<div style="font-size:1.2rem;font-weight:700;">{escape(notice.headline)}</div>'
        f"{_status_tag(notice.status)}</div>"
    )
    body = (
        title
        + _line(notice.subject, "font-weight:600;margin-top:0.15rem;")
        + _line(notice.detail, "margin-top:0.35rem;")
        + _line(notice.recorded, "margin-top:0.35rem;font-size:0.8rem;opacity:0.75;")
    )
    return (
        f'<div data-notice="card" data-tone="{notice.tone.value}" role="status" '
        f'style="display:flex;gap:0.9rem;align-items:flex-start;background:{fill};color:{text};'
        f"border:1px solid {bar}55;border-left:7px solid {bar};border-radius:10px;"
        f'padding:0.85rem 1.1rem;margin:0.5rem 0 0.9rem;box-shadow:0 2px 8px {bar}22;">'
        f'{_icon(notice.tone, 2.4)}<div style="min-width:0;">{body}</div></div>'
    )


def popup_html(notice: Notice) -> str:
    fill, bar, text = _TONES[notice.tone]
    seconds = _POPUP_SECONDS.get(notice.tone, _POPUP_DEFAULT_SECONDS)
    body = f'<div style="font-weight:700;font-size:1.02rem;">{escape(notice.headline)}</div>'
    body += _line(notice.subject, "font-size:0.88rem;margin-top:0.1rem;")
    return (
        _KEYFRAMES + f'<div data-notice="popup" data-tone="{notice.tone.value}" role="alert" '
        'style="position:fixed;top:4.25rem;right:1.25rem;z-index:1000000;max-width:24rem;'
        f"display:flex;gap:0.75rem;align-items:center;background:{fill};color:{text};"
        f"border:1px solid {bar}66;border-left:7px solid {bar};border-radius:10px;"
        "padding:0.75rem 1rem;box-shadow:0 8px 24px rgba(0,0,0,0.18);pointer-events:none;"
        f'animation:kallang-notice-in {seconds}s ease-out forwards;">'
        f"{_icon(notice.tone, 2)}<div>{body}</div></div>"
    )
