"""R07: the file is readable (text layer or OCR confidence above threshold) and the model
output is valid after one retry."""

from __future__ import annotations

from invoiceflow.contracts import CheckContext, Finding, Scope, TextSource
from invoiceflow.rules.base import BaseRule


class R07(BaseRule):
    rule_id = "R07"

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        min_chars = int(self._config["scanned_page_min_chars"])
        min_conf = float(self._config["ocr_min_mean_conf"])

        # A page is readable when it has a text layer, or when OCR produced enough
        # characters at a high enough mean confidence.
        for page in ctx.document.pages:
            if page.source is TextSource.OCR:
                chars = sum(len(w.text) for w in page.visible_words)
                conf = page.ocr_mean_conf
                if chars < min_chars or conf is None or conf < min_conf:
                    findings.append(
                        self.finding(
                            severity=None,
                            scope=Scope.DOCUMENT,
                            message=(
                                f"Page {page.page_no} is not readable "
                                f"(OCR, {chars} characters, mean confidence {conf})"
                            ),
                            evidence={
                                "page_no": str(page.page_no),
                                "chars": str(chars),
                                "ocr_mean_conf": "" if conf is None else f"{conf:.1f}",
                            },
                        )
                    )

        # The model output must be valid after the single retry WS3 performs.
        if not ctx.extraction.valid:
            findings.append(
                self.finding(
                    severity=None,
                    scope=Scope.DOCUMENT,
                    message="Model output is invalid after retry",
                    evidence={"error": ctx.extraction.error or ""},
                )
            )

        return tuple(findings)
