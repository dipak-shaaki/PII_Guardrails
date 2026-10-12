import pytest

from pii_shield.core.detector import DetectedEntity
from pii_shield.core.guardrails import InputGuard, OutputGuard
from pii_shield.core.tokenizer import Tokenizer
from pii_shield.core.vault import TokenVault
from pii_shield.exceptions import InputBlockedError
from tests.helpers import StubDetector

CARD = "4111 1111 1111 1111"


def entity(etype: str, value: str, start: int = 0) -> DetectedEntity:
    return DetectedEntity(etype, start, start + len(value), 0.9, value)


def test_input_guard_blocks_credit_card():
    with pytest.raises(InputBlockedError) as exc:
        InputGuard().check([entity("CREDIT_CARD", CARD)])
    assert exc.value.entity_types == ("CREDIT_CARD",)


def test_input_guard_error_never_contains_the_value():
    with pytest.raises(InputBlockedError) as exc:
        InputGuard().check([entity("CREDIT_CARD", CARD)])
    assert CARD not in str(exc.value)


def test_input_guard_allows_other_pii():
    InputGuard().check([entity("PERSON", "Dipak"), entity("EMAIL_ADDRESS", "a@b.com")])


def test_input_guard_allows_clean_text():
    InputGuard().check([])


def make_output_guard(known: dict[str, str]) -> tuple[OutputGuard, TokenVault]:
    detector = StubDetector(known)
    return OutputGuard(detector, Tokenizer(detector)), TokenVault()


def test_output_guard_retokenizes_leak():
    guard, vault = make_output_guard({"9841657581": "PHONE_NUMBER"})
    result = guard.scan("Sure, I'll call 9841657581 now", vault)
    assert result.leaked
    assert result.text == "Sure, I'll call <PHONE_NUMBER_1> now"
    assert "9841657581" not in result.text


def test_output_guard_leaves_clean_text_alone():
    guard, vault = make_output_guard({"9841657581": "PHONE_NUMBER"})
    result = guard.scan("Your meeting is booked.", vault)
    assert not result.leaked
    assert result.text == "Your meeting is booked."


def test_output_guard_ignores_existing_tokens():
    # NER sometimes flags "PERSON_1" inside "<PERSON_1>"; that must not be re-wrapped.
    guard, vault = make_output_guard({"PERSON_1": "ORGANIZATION"})
    result = guard.scan("Hello <PERSON_1>, welcome", vault)
    assert not result.leaked
    assert result.text == "Hello <PERSON_1>, welcome"


def test_output_guard_reuses_vault_token_for_known_value():
    guard, vault = make_output_guard({"Dipak": "PERSON"})
    vault.get_or_create_token("PERSON", "Dipak")
    result = guard.scan("Thanks Dipak", vault)
    assert result.text == "Thanks <PERSON_1>"