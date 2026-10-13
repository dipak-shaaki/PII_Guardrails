import logging
from collections.abc import Iterable
from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngineProvider

from pii_shield.config import Settings, get_settings
from pii_shield.core.recognizers import register_custom_recognizers
from pii_shield.exceptions import DetectionError

logger = logging.getLogger(__name__)

# Entity types that produce too much noise to tokenize.
EXCLUDED_ENTITIES: frozenset[str] = frozenset(
    {"URL", "US_BANK_NUMBER", "US_DRIVER_LICENSE", "DATE_TIME"}
)


@dataclass(frozen=True, slots=True)
class DetectedEntity:
    entity_type: str
    start: int
    end: int
    score: float
    text: str


class Detector:
    """Thin wrapper around Presidio that returns clean, filtered detections."""

    def __init__(
        self,
        spacy_model: str = "en_core_web_lg",
        threshold: float = 0.4,
        excluded_entities: Iterable[str] = EXCLUDED_ENTITIES,
        language: str = "en",
    ) -> None:
        self.language = language
        self.threshold = threshold
        self.excluded_entities = frozenset(excluded_entities)

        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": language, "model_name":spacy_model}],
            }
        ).create_engine()

        registry = RecognizerRegistry(supported_languages=[language])
        registry.load_predefined_recognizers(
            nlp_engine=nlp_engine, languages=[language]
        )
        register_custom_recognizers(registry)

        self._analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine,
            registry=registry,
            supported_languages=[language],
        )

        # Only run recognizers for entities we actually keep.
        self._entities = [
            e
            for e in self._analyzer.get_supported_entities(language=language)
            if e not in self.excluded_entities
        ]
        logger.info(
            "Detector ready (model=%s, threshold=%.2f, entities=%d)",
            spacy_model,
            threshold,
            len(self._entities),
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> Detector:
        settings = settings or get_settings()
        return cls(
            spacy_model=settings.spacy_model,
            threshold=settings.pii_confidence_threshold,
        )

    def detect(self, text: str) -> list[DetectedEntity]:
        """Return PII entities at or above the confidence threshold, in text order."""
        if not text or not text.strip():
            return []

        try:
            results = self._analyzer.analyze(
                text=text,
                language=self.language,
                entities=self._entities,
            )
        except Exception as exc:
            logger.exception("PII detection failed")
            raise DetectionError("PII detection failed") from exc

        entities = [
            DetectedEntity(
                entity_type=r.entity_type,
                start=r.start,
                end=r.end,
                score=r.score,
                text=text[r.start : r.end],
            )
            for r in results
            if r.score >= self.threshold
        ]
        return sorted(entities, key=lambda e: e.start)
