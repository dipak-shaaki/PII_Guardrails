import pytest

from pii_shield.core.detector import Detector


@pytest.fixture(scope="module")
def detector() -> Detector:
    # Module scope: loading the spaCy model is slow, so do it once.
    return Detector(spacy_model="en_core_web_lg", threshold=0.4)


def test_detects_email(detector):
    entities = detector.detect("Mail me at john.doe@example.com please")
    assert any(
        e.entity_type == "EMAIL_ADDRESS" and e.text == "john.doe@example.com"
        for e in entities
    )


def test_detects_person(detector):
    entities = detector.detect("My name is Rajesh Sharma")
    assert any(e.entity_type == "PERSON" and "Rajesh" in e.text for e in entities)


def test_detects_phone(detector):
    entities = detector.detect("Call me on +1 415 555 2671")
    assert any(e.entity_type == "PHONE_NUMBER" for e in entities)


def test_empty_and_whitespace_input(detector):
    assert detector.detect("") == []
    assert detector.detect("   ") == []


def test_excluded_entities_are_not_returned(detector):
    entities = detector.detect("Visit https://example.com on 12 October 2026")
    assert not any(e.entity_type in {"URL", "DATE_TIME"} for e in entities)


def test_results_sorted_by_position(detector):
    entities = detector.detect("Email a@b.com, then call Radha Dhakal")
    starts = [e.start for e in entities]
    assert starts == sorted(starts)