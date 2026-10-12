from pii_shield.core.detector import DetectedEntity


class StubDetector:
    """Finds hardcoded values, so tests don't need spaCy."""

    def __init__(self, known: dict[str, str]) -> None:
        self.known = known  # value -> entity_type

    def detect(self, text: str) -> list[DetectedEntity]:
        found = []
        for value, etype in self.known.items():
            start = text.find(value)
            while start != -1:
                found.append(
                    DetectedEntity(etype, start, start + len(value), 0.9, value)
                )
                start = text.find(value, start + len(value))
        return sorted(found, key=lambda e: e.start)
