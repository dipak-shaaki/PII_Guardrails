from pii_shield.core.detector import DetectedEntity
from pii_shield.evaluation.dataset import parse_example
from pii_shield.evaluation.metrics import micro, score

TYPES = ("PERSON", "EMAIL_ADDRESS")


def ent(etype: str, start: int, end: int, text: str) -> DetectedEntity:
    return DetectedEntity(etype, start, end, 0.9, text[start:end])


def test_parse_example_computes_exact_spans():
    ex = parse_example("Hi [[PERSON|Sita Sharma]], mail [[EMAIL_ADDRESS|a@b.com]]!")
    assert ex.text == "Hi Sita Sharma, mail a@b.com!"
    assert [(s.entity_type, ex.text[s.start : s.end]) for s in ex.spans] == [
        ("PERSON", "Sita Sharma"),
        ("EMAIL_ADDRESS", "a@b.com"),
    ]


def test_parse_example_without_markup_has_no_spans():
    ex = parse_example("What are your loan rates?")
    assert ex.text == "What are your loan rates?"
    assert ex.spans == ()


def test_perfect_prediction():
    ex = parse_example("I am [[PERSON|Sita]]")
    counts, errors = score([ex], [[ent("PERSON", 5, 9, ex.text)]], TYPES)
    assert (counts["PERSON"].tp, counts["PERSON"].fp, counts["PERSON"].fn) == (1, 0, 0)
    assert errors == []


def test_missed_entity_is_a_false_negative():
    ex = parse_example("I am [[PERSON|Sita]]")
    counts, errors = score([ex], [[]], TYPES)
    assert counts["PERSON"].fn == 1
    assert errors[0].kind == "missed" and errors[0].value == "Sita"


def test_spurious_entity_is_a_false_positive():
    ex = parse_example("Please mark this")
    counts, errors = score([ex], [[ent("PERSON", 7, 11, ex.text)]], TYPES)
    assert counts["PERSON"].fp == 1
    assert errors[0].kind == "false_positive"


def test_wrong_type_counts_as_miss_and_false_positive():
    ex = parse_example("I am [[PERSON|Sita]]")
    counts, _ = score([ex], [[ent("EMAIL_ADDRESS", 5, 9, ex.text)]], TYPES)
    assert counts["PERSON"].fn == 1
    assert counts["EMAIL_ADDRESS"].fp == 1


def test_partial_overlap_passes_lenient_but_fails_strict():
    ex = parse_example("I am [[PERSON|Sita Sharma]]")
    pred = [[ent("PERSON", 5, 9, ex.text)]]  # only "Sita"
    lenient, _ = score([ex], pred, TYPES)
    strict, _ = score([ex], pred, TYPES, strict=True)
    assert lenient["PERSON"].tp == 1
    assert strict["PERSON"].tp == 0 and strict["PERSON"].fn == 1


def test_f1_and_micro_average():
    ex = parse_example("[[PERSON|Sita]] [[EMAIL_ADDRESS|a@b.com]]")
    preds = [[ent("PERSON", 0, 4, ex.text)]]  # email missed
    counts, _ = score([ex], preds, TYPES)
    total = micro(counts)
    assert (total.tp, total.fn) == (1, 1)
    assert total.recall == 0.5 and total.precision == 1.0