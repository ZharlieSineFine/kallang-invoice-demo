"""Field confidence comes from the checks, not the model.

- High: found exactly or as an equal number, and no check flags it.
- Medium: found only by fuzzy match, and no check flags it.
- Low: not found, or a check flags it.
"""

from __future__ import annotations

from invoiceflow.contracts import (
    CheckContext,
    Confidence,
    FieldConfidence,
    Finding,
    MatchType,
    Severity,
)

_MATCH_CONFIDENCE = {
    MatchType.EXACT: Confidence.HIGH,
    MatchType.NUMERIC: Confidence.HIGH,
    MatchType.FUZZY: Confidence.MEDIUM,
    MatchType.NONE: Confidence.LOW,
}


def field_confidences(
    ctx: CheckContext, findings: tuple[Finding, ...]
) -> tuple[FieldConfidence, ...]:
    """Confidence for every located field, downgraded to LOW when a check flags it."""
    flagged = {f.field for f in findings if f.field and f.severity.rank >= Severity.FLAG.rank}
    confidences = [
        FieldConfidence(
            field=loc.field,
            confidence=(
                Confidence.LOW
                if loc.field in flagged
                else _MATCH_CONFIDENCE.get(loc.match_type, Confidence.LOW)
            ),
        )
        for loc in ctx.locations
    ]
    return tuple(confidences)
