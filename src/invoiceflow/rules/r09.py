"""R09: no hidden text, no instruction-like text, and the canary does not appear in the
model output."""

from __future__ import annotations

from invoiceflow.contracts import CheckContext, Finding, Scope
from invoiceflow.rules.base import BaseRule, visible_text

# Prompt-injection canary: WS3 embeds this in the prompt and instructs the model never to
# echo it. If it appears in the output, the document tampered with the model. The value is
# shared through config/rules.yaml (CR-001); this is the fallback if the key is missing.
CANARY = "KALLANG-INTERNAL-CANARY-9f3a"


class R09(BaseRule):
    rule_id = "R09"

    @property
    def _canary(self) -> str:
        return str(self._config.get("canary", CANARY))

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        phrases = [str(p) for p in self._config["instruction_phrases"]]

        # Hidden text (white, tiny, or off-page words) kept as evidence by WS2.
        hidden = ctx.document.hidden_words
        if hidden:
            pages = sorted({page_no for page_no, _ in hidden})
            findings.append(
                self.finding(
                    severity=None,
                    scope=Scope.DOCUMENT,
                    message=f"Hidden text detected on page(s) {', '.join(map(str, pages))}",
                    evidence={
                        "pages": ", ".join(map(str, pages)),
                        "count": str(len(hidden)),
                    },
                )
            )

        # Instruction-like text inside the document is a prompt-injection attempt.
        text = visible_text(ctx.document)
        lowered = text.casefold()
        doc_hits = [p for p in phrases if p.casefold() in lowered]
        if doc_hits:
            findings.append(
                self.finding(
                    severity=None,
                    scope=Scope.DOCUMENT,
                    message="Instruction-like text detected in the document",
                    evidence={"phrases": ", ".join(doc_hits)},
                )
            )

        # Instruction phrases or the canary in the model output.
        raw = (ctx.extraction.raw_output or "").casefold()
        out_hits = [p for p in phrases if p.casefold() in raw]
        if out_hits:
            findings.append(
                self.finding(
                    severity=None,
                    scope=Scope.DOCUMENT,
                    message="Instruction-like text appeared in the model output",
                    evidence={"phrases": ", ".join(out_hits)},
                )
            )
        if self._canary.casefold() in raw:
            findings.append(
                self.finding(
                    severity=None,
                    scope=Scope.DOCUMENT,
                    message="The canary appeared in the model output",
                    evidence={"canary": self._canary},
                )
            )

        return tuple(findings)
