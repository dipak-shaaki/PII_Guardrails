from pii_shield.core.detector import DetectedEntity
from pii_shield.core.tokenizer import Tokenizer
from pii_shield.core.vault import TokenVault


class StubDetector:
    """Finds hardcoded values, so tests don't need spaCy."""

    def __init__(self, known: dict[str, str]) -> None:
        self.known = known  # value -> entity_type

    def detect(self, text: str) -> list[DetectedEntity]:
        found = []
        for value, etype in self.known.items():
            start = text.find(value)
            while start != -1:
                found.append(DetectedEntity(etype, start, start + len(value), 0.9, value))
                start = text.find(value, start + len(value))
        return sorted(found, key=lambda e: e.start)


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
    second = tok.tokenize("Dipak again", vault)
    assert second.text == "<PERSON_1> again"


def test_no_pii_returns_text_unchanged():
    tok, vault = make()
    result = tok.tokenize("What are your loan rates?", vault)
    assert result.text == "What are your loan rates?"
    assert not result.found_pii


def test_restore_round_trip():
    tok, vault = make()
    original = "Call Dipak on 9841657581"
    tokenized = tok.tokenize(original, vault)
    assert vault.restore(tokenized.text) == original


def test_unknown_token_left_untouched():
    vault = TokenVault()
    assert vault.restore("hello <PERSON_9>") == "hello <PERSON_9>"


def test_dual_query_restores_only_names():
    tok, vault = make()
    dual = tok.create_dual_queries("Dipak's number is 9841657581", vault)
    assert dual.llm_query == "<PERSON_1>'s number is <PHONE_NUMBER_1>"
    assert dual.rag_query == "Dipak's number is <PHONE_NUMBER_1>"


def test_vault_survives_serialization():
    tok, vault = make()
    tok.tokenize("Dipak", vault)
    restored = TokenVault.from_dict(vault.to_dict())
    assert restored.get_or_create_token("PERSON", "dipak") == "<PERSON_1>"