import pytest

from pii_shield import DetectionError, InputBlockedError, PIIShield, TokenVault
from tests.helpers import StubDetector

CARD = "4111 1111 1111 1111"
KNOWN = {"Dipak": "PERSON", "9841657581": "PHONE_NUMBER", CARD: "CREDIT_CARD"}


class CountingDetector(StubDetector):
    def __init__(self, known):
        super().__init__(known)
        self.calls = 0

    def detect(self, text):
        self.calls += 1
        return super().detect(text)


class BrokenDetector:
    def detect(self, text):
        raise DetectionError("boom")


def make() -> tuple[PIIShield, TokenVault]:
    return PIIShield(StubDetector(KNOWN)), TokenVault()


def test_sanitize_produces_both_queries():
    shield, vault = make()
    safe = shield.sanitize("Dipak's number is 9841657581", vault)
    assert safe.llm_query == "<PERSON_1>'s number is <PHONE_NUMBER_1>"
    assert safe.rag_query == "Dipak's number is <PHONE_NUMBER_1>"
    assert safe.entity_types == ("PERSON", "PHONE_NUMBER")


def test_sanitize_scans_input_only_once():
    detector = CountingDetector(KNOWN)
    PIIShield(detector).sanitize("Dipak", TokenVault())
    assert detector.calls == 1


def test_credit_card_blocked_before_vault_is_touched():
    shield, vault = make()
    with pytest.raises(InputBlockedError):
        shield.sanitize(f"Dipak, my card is {CARD}", vault)
    assert vault.token_to_value == {}  # nothing leaked into the vault


def test_detection_failure_fails_closed():
    shield = PIIShield(BrokenDetector())
    with pytest.raises(DetectionError):
        shield.sanitize("anything", TokenVault())


def test_full_round_trip_across_turns():
    shield, vault = make()
    shield.sanitize("I am Dipak", vault)
    second = shield.sanitize("Call me on 9841657581", vault)
    assert second.llm_query == "Call me on <PHONE_NUMBER_1>"

    llm_reply = "Calling <PHONE_NUMBER_1> for <PERSON_1> now."
    assert shield.restore(llm_reply, vault) == "Calling 9841657581 for Dipak now."


def test_output_leak_is_retokenized_then_restorable():
    shield, vault = make()
    shield.sanitize("I am Dipak", vault)
    scan = shield.sanitize_output("Sure Dipak, ring 9841657581", vault)
    assert scan.leaked
    assert "9841657581" not in scan.text and "Dipak" not in scan.text
    assert shield.restore(scan.text, vault) == "Sure Dipak, ring 9841657581"


def test_clean_text_passes_through():
    shield, vault = make()
    safe = shield.sanitize("What are your loan rates?", vault)
    assert safe.llm_query == "What are your loan rates?"
    assert not safe.found_pii
