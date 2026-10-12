import logging
from collections.abc import Iterable

from phonenumbers import Leniency, PhoneNumberMatcher
from presidio_analyzer import EntityRecognizer, RecognizerRegistry, RecognizerResult
from presidio_analyzer.nlp_engine import NlpArtifacts

logger = logging.getLogger(__name__)

# Regions to try when a number has no "+" country code. Make this configurable later.
DEFAULT_REGIONS: tuple[str, ...] = ("NP", "IN", "US", "GB")


class StrictPhoneRecognizer(EntityRecognizer):
    """Phone detection backed by Google's `phonenumbers` library.

    Replaces Presidio's default phone recognizer, which produces more false
    positives. A match must be a valid number for one of the configured regions.
    """

    ENTITY = "PHONE_NUMBER"

    def __init__(
        self,
        regions: Iterable[str] = DEFAULT_REGIONS,
        score: float = 0.85,
        supported_language: str = "en",
    ) -> None:
        self.regions = tuple(regions)
        self.score = score
        super().__init__(
            supported_entities=[self.ENTITY],
            supported_language=supported_language,
            name="StrictPhoneRecognizer",
        )

    def load(self) -> None:
        # Nothing to load; required by the EntityRecognizer interface.
        pass

    def analyze(
        self,
        text: str,
        entities: list[str],
        nlp_artifacts: NlpArtifacts | None = None,
    ) -> list[RecognizerResult]:
        if self.ENTITY not in entities:
            return []

        results: list[RecognizerResult] = []
        seen: set[tuple[int, int]] = set()

        for region in self.regions:
            for match in PhoneNumberMatcher(text, region, leniency=Leniency.VALID):
                span = (match.start, match.end)
                if span in seen:
                    continue
                seen.add(span)
                results.append(
                    RecognizerResult(
                        entity_type=self.ENTITY,
                        start=match.start,
                        end=match.end,
                        score=self.score,
                    )
                )
        return results


def register_custom_recognizers(
    registry: RecognizerRegistry,
    regions: Iterable[str] = DEFAULT_REGIONS,
) -> None:
    """Swap Presidio's built-in phone recognizer for ours."""
    registry.remove_recognizer("PhoneRecognizer")
    registry.add_recognizer(StrictPhoneRecognizer(regions=regions))
    logger.info("Registered StrictPhoneRecognizer for regions: %s", tuple(regions))