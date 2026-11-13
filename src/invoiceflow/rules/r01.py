"""R01: every extracted value appears on the page — exactly, as an equal number, or fuzzy >= 90.

The locator (WS4) records how each value was found on the page as a ``FieldLocation``.
R01 trusts that record and flags any value the locator could not place on the page. A field
the model left empty has no value to place, so it is not R01's concern: R06 covers the fields
SAP cannot do without.
"""

from __future__ import annotations

import re

from invoiceflow.contracts import CheckContext, Finding, InvoiceExtraction, MatchType, Scope
from invoiceflow.rules.base import BaseRule

_LINE_FIELD = re.compile(r"^line_items\[(\d+)\]\.(\w+)$")


def _extracted_value(extraction: InvoiceExtraction | None, field: str) -> object | None:
    """What the model returned for a located field, header or ``line_items[i].name``."""
    if extraction is None:
        return None
    line = _LINE_FIELD.match(field)
    if line is None:
        return getattr(extraction, field, None)
    index = int(line.group(1))
    if index >= len(extraction.line_items):
        return None
    return getattr(extraction.line_items[index], line.group(2), None)


def _is_empty(value: object | None) -> bool:
    return value is None or str(value).strip() == ""


def _found(loc: MatchType, score: float, min_score: int) -> bool:
    if loc in (MatchType.EXACT, MatchType.NUMERIC):
        return True
    return loc is MatchType.FUZZY and score >= min_score


class R01(BaseRule):
    rule_id = "R01"

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        min_score = int(self._config["fuzzy_match_min_score"])
        findings: list[Finding] = []
        extraction = ctx.extraction.extraction
        for loc in ctx.locations:
            if _found(loc.match_type, loc.score, min_score):
                continue
            if _is_empty(_extracted_value(extraction, loc.field)):
                continue
            if loc.match_type is MatchType.NONE:
                message = f"{loc.field} was not found on the page"
            else:
                message = (
                    f"{loc.field} only matched fuzzily at {loc.score:.0f}%, below {min_score}%"
                )
            findings.append(
                self.finding(
                    severity=None,
                    scope=Scope.FIELD,
                    field=loc.field,
                    message=message,
                    evidence={
                        "match_type": loc.match_type.value,
                        "score": f"{loc.score:.0f}",
                    },
                )
            )
        return tuple(findings)
