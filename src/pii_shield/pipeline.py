import logging
from dataclasses import dataclass

from pii_shield.config import Settings
from pii_shield.core.detector import DetectedEntity, Detector
from pii_shield.core.guardrails import InputGuard, OutputGuard, OutputScan
from pii_shield.core.tokenizer import RAG_RESTORABLE_TYPES, SupportsDetect, Tokenizer
from pii_shield.core.vault import TokenVault

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SanitizedInput:
    llm_query: str  # fully tokenized, the only version a provider may see
    rag_query: str  # names restored, for local retrieval only
    entities: tuple[DetectedEntity, ...]

    @property
    def found_pii(self) -> bool:
        return bool(self.entities)

    @property
    def entity_types(self) -> tuple[str, ...]:
        return tuple(sorted({e.entity_type for e in self.entities}))


class PIIShield:
    """Single entry point for PII-safe LLM applications.

    Typical use:
        shield = PIIShield.from_settings()
        vault = TokenVault()                      # one per session
        safe = shield.sanitize(user_text, vault)  # -> send safe.llm_query to the LLM
        reply = shield.sanitize_output(llm_text, vault).text
        shown = shield.restore(reply, vault)      # real values, for user or tool
    """

    def __init__(
        self,
        detector: SupportsDetect,
        input_guard: InputGuard | None = None,
    ) -> None:
        self._detector = detector
        self._tokenizer = Tokenizer(detector)
        self._input_guard = input_guard or InputGuard()
        self._output_guard = OutputGuard(detector, self._tokenizer)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> PIIShield:
        return cls(Detector.from_settings(settings))

    def sanitize(self, text: str, vault: TokenVault) -> SanitizedInput:
        """Detect once, hard-block forbidden PII, then tokenize.

        Raises InputBlockedError (e.g. credit card) or DetectionError.
        Both are raised before the vault is touched.
        """
        entities = self._detector.detect(text)
        self._input_guard.check(entities)

        tokenized = self._tokenizer.apply(text, entities, vault)
        rag_query = vault.restore(tokenized.text, only_types=RAG_RESTORABLE_TYPES)
        return SanitizedInput(
            llm_query=tokenized.text,
            rag_query=rag_query,
            entities=tokenized.entities,
        )

    def sanitize_output(self, text: str, vault: TokenVault) -> OutputScan:
        """Re-scan LLM output and re-tokenize anything that leaked."""
        return self._output_guard.scan(text, vault)

    def restore(self, text: str, vault: TokenVault) -> str:
        """Swap tokens back to real values.

        Call this only at the last moment: when executing a tool, or when
        rendering the final reply to the end user. Never before an LLM call.
        """
        return vault.restore(text)