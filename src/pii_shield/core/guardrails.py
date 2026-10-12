import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pii_shield.core.detector import DetectedEntity
from pii_shield.core.tokenizer import SupportsDetect, Tokenizer
from pii_shield.core.vault import TOKEN_PATTERN, TokenVault
from pii_shield.exceptions import InputBlockedError

logger = logging.getLogger(__name__)

# Data we refuse to process at all, not even in tokenized form.
BLOCKED_INPUT_TYPES: frozenset[str] = frozenset({"CREDIT_CARD"})


class InputGuard:
    """Hard-blocks messages containing forbidden PII before any tokenization."""

    def __init__(self, blocked_types: Iterable[str] = BLOCKED_INPUT_TYPES) -> None:
        self._blocked = frozenset(blocked_types)

    def check(self, entities: Sequence[DetectedEntity]) -> None:
        hits = sorted({e.entity_type for e in entities if e.entity_type in self._blocked})
        if hits:
            logger.warning("Blocked input containing: %s", ", ".join(hits))
            raise InputBlockedError(hits)


@dataclass(frozen=True, slots=True)
class OutputScan:
    text: str
    leaks_found: int

    @property
    def leaked(self) -> bool:
        return self.leaks_found > 0


class OutputGuard:
    """Re-scans LLM output and re-tokenizes any PII that slipped through."""

    def __init__(self, detector: SupportsDetect, tokenizer: Tokenizer) -> None:
        self._detector = detector
        self._tokenizer = tokenizer

    def scan(self, text: str, vault: TokenVault) -> OutputScan:
        entities = self._detector.detect(text)  # raises DetectionError: fail closed

        # Our own tokens (e.g. <PERSON_1>) can look like entities to the NER model.
        # Ignore any detection overlapping an existing token.
        token_spans = [m.span() for m in TOKEN_PATTERN.finditer(text)]
        leaks = [
            e
            for e in entities
            if not any(e.start < t_end and e.end > t_start for t_start, t_end in token_spans)
        ]
        if not leaks:
            return OutputScan(text=text, leaks_found=0)

        logger.warning("LLM output leaked %d PII span(s); re-tokenizing", len(leaks))
        cleaned = self._tokenizer.apply(text, leaks, vault).text
        return OutputScan(text=cleaned, leaks_found=len(leaks))