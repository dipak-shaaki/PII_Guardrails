from pii_shield.core.tokenizer import Tokenizer
from pii_shield.core.vault import TokenVault
from tests.helpers import StubDetector

KNOWN = {"Dipak": "PERSON", "dipak@example.com": "EMAIL_ADDRESS", "9841657581": "PHONE_NUMBER"}


def make() -> tuple[Tokenizer, TokenVault]:
    return Tokenizer(StubDetector(KNOWN)), TokenVault()


def test_replaces_pii_with_tokens():
    tok, vault = make()
    result = tok.tokenize("I am Dipak, mail dipak@example.com", vault)
    assert result.text == "I am <PERSON_1>, mail <EMAIL_ADDRESS_1>"
    assert "Dipak" not in result.text and "@" not in result.text


def test_same_value_reuses_token():
    tok, vault = make()
    result = tok.tokenize("Dipak met Dipak", vault)
    assert result.text == "<PERSON_1> met <PERSON_1>"
    assert vault.counters["PERSON"] == 1


def test_token_reused_across_turns():
    tok, vault = make()
    tok.tokenize("I am Dipak", vault)
    assert tok.tokenize("Dipak again", vault).text == "<PERSON_1> again"


def test_no_pii_returns_text_unchanged():
    tok, vault = make()
    result = tok.tokenize("What are your loan rates?", vault)
    assert result.text == "What are your loan rates?"
    assert not result.found_pii


def test_restore_round_trip():
    tok, vault = make()
    original = "Call Dipak on 9841657581"
    assert vault.restore(tok.tokenize(original, vault).text) == original


def test_unknown_token_left_untouched():
    assert TokenVault().restore("hello <PERSON_9>") == "hello <PERSON_9>"


def test_vault_survives_serialization():
    tok, vault = make()
    tok.tokenize("Dipak", vault)
    restored = TokenVault.from_dict(vault.to_dict())
    assert restored.get_or_create_token("PERSON", "dipak") == "<PERSON_1>"