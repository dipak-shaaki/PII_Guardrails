from collections.abc import Sequence
from dataclasses import dataclass

from pii_shield.core.detector import DetectedEntity
from pii_shield.evaluation.dataset import Example, GoldSpan


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        total = self.tp + self.fp
        return self.tp / total if total else 0.0

    @property
    def recall(self) -> float:
        total = self.tp + self.fn
        return self.tp / total if total else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass(frozen=True, slots=True)
class Error:
    kind: str  # "missed" | "false_positive"
    entity_type: str
    text: str
    value: str


def _matches(gold: GoldSpan, pred: DetectedEntity, strict: bool) -> bool:
    if strict:
        return gold.start == pred.start and gold.end == pred.end
    return gold.start < pred.end and pred.start < gold.end  # any overlap


def score(
    examples: Sequence[Example],
    predictions: Sequence[Sequence[DetectedEntity]],
    types: Sequence[str],
    *,
    strict: bool = False,
) -> tuple[dict[str, Counts], list[Error]]:
    """Entity-level scoring. Each gold span can be matched by at most one prediction."""
    counts = {t: Counts() for t in types}
    errors: list[Error] = []

    for example, preds in zip(examples, predictions, strict=True):
        for t in types:
            unmatched = [g for g in example.spans if g.entity_type == t]
            for pred in (p for p in preds if p.entity_type == t):
                hit = next((g for g in unmatched if _matches(g, pred, strict)), None)
                if hit is not None:
                    unmatched.remove(hit)
                    counts[t].tp += 1
                else:
                    counts[t].fp += 1
                    errors.append(Error("false_positive", t, example.text, pred.text))
            for gold in unmatched:
                counts[t].fn += 1
                errors.append(Error("missed", t, example.text, example.text[gold.start : gold.end]))
    return counts, errors


def micro(counts: dict[str, Counts]) -> Counts:
    total = Counts()
    for c in counts.values():
        total.tp += c.tp
        total.fp += c.fp
        total.fn += c.fn
    return total