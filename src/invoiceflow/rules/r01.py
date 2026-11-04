"""R01: every extracted value appears on the page — exactly, as an equal number, or fuzzy >= 90.

The locator (WS4) records how each value was found on the page as a ``FieldLocation``.
R01 trusts that record and flags any field the locator could not place on the page.
"""

from __future__ import annotations

from invoiceflow.contracts import CheckContext, Finding, MatchType, Scope
from invoiceflow.rules.base import BaseRule


def _found(loc: MatchType, score: float, min_score: int) -> bool:
    if loc in (MatchType.EXACT, MatchType.NUMERIC):
        return True
    return loc is MatchType.FUZZY and score >= min_score


class R01(BaseRule):
    rule_id = "R01"

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        min_score = int(self._config["fuzzy_match_min_score"])
        findings: list[Finding] = []
        for loc in ctx.locations:
            if _found(loc.match_type, loc.score, min_score):
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
