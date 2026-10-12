import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pii_shield.core.detector import DetectedEntity
from pii_shield.core.vault import TokenVault

logger = logging.getLogger(__name__)

# Entity types safe to restore in the RAG query. It is used for local
# retrieval only and must never be sent to an LLM provider.
RAG_RESTORABLE_TYPES: frozenset[str] = frozenset({"PERSON"})


class SupportsDetect(Protocol):
    def detect(self, text: str) -> list[DetectedEntity]: ...


@dataclass(frozen=True, slots=True)
class TokenizedText:
    text: str
    entities: tuple[DetectedEntity, ...]

    @property
    def found_pii(self) -> bool:
        return bool(self.entities)


@dataclass(frozen=True, slots=True)
class DualQuery:
    llm_query: str  # fully tokenized, the only version the LLM may see
    rag_query: str  # names restored, for local retrieval only


class Tokenizer:
    def __init__(self, detector: SupportsDetect) -> None:
        self._detector = detector

    def tokenize(self, text: str, vault: TokenVault) -> TokenizedText:
        entities = self._detector.detect(text)  # raises DetectionError: fail closed
        return self.apply(text, entities, vault)

    def apply(
        self, text: str, entities: Sequence[DetectedEntity], vault: TokenVault
    ) -> TokenizedText:
        """Replace already-detected entities with tokens."""
        if not entities:
            return TokenizedText(text=text, entities=())

        tokens = [vault.get_or_create_token(e.entity_type, e.text) for e in entities]

        out = text
        for entity, token in sorted(zip(entities, tokens), key=lambda p: -p[0].start):
            out = out[: entity.start] + token + out[entity.end :]

        logger.info("Tokenized %d PII span(s)", len(entities))
        return TokenizedText(text=out, entities=tuple(entities))

    def create_dual_queries(self, text: str, vault: TokenVault) -> DualQuery:
        tokenized = self.tokenize(text, vault)
        rag = vault.restore(tokenized.text, only_types=RAG_RESTORABLE_TYPES)
        return DualQuery(llm_query=tokenized.text, rag_query=rag)