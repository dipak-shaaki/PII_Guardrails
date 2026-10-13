import argparse
import logging
import time
from collections import Counter
from pathlib import Path

from pii_shield.core.detector import Detector
from pii_shield.evaluation.dataset import Example, load_dataset
from pii_shield.evaluation.metrics import micro, score

TYPES = ("PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD")


def run(model: str, threshold: float, examples: list[Example], show_errors: bool) -> None:
    try:
        detector = Detector(spacy_model=model, threshold=threshold)
    except Exception as exc:  # CLI boundary: report and move on to the next model
        print(f"\n== {model}: could not load ({type(exc).__name__}) ==")
        return
    detector.detect("warm up")  # first call is slow; exclude it from timings

    predictions, times_ms = [], []
    for example in examples:
        start = time.perf_counter()
        predictions.append(detector.detect(example.text))
        times_ms.append((time.perf_counter() - start) * 1000)

    lenient, errors = score(examples, predictions, TYPES)
    strict, _ = score(examples, predictions, TYPES, strict=True)

    print(f"\n== {model} | threshold {threshold} | {len(examples)} examples ==")
    print(f"{'type':<15}{'P':>7}{'R':>7}{'F1':>7}{'strict F1':>11}{'support':>9}")
    for t in TYPES:
        c = lenient[t]
        print(f"{t:<15}{c.precision:>7.2f}{c.recall:>7.2f}{c.f1:>7.2f}"
              f"{strict[t].f1:>11.2f}{c.tp + c.fn:>9}")
    m, ms = micro(lenient), micro(strict)
    print(f"{'ALL (micro)':<15}{m.precision:>7.2f}{m.recall:>7.2f}{m.f1:>7.2f}"
          f"{ms.f1:>11.2f}{m.tp + m.fn:>9}")

    ordered = sorted(times_ms)
    print(f"latency per message: median {ordered[len(ordered) // 2]:.0f} ms, "
          f"p95 {ordered[int(0.95 * (len(ordered) - 1))]:.0f} ms")

    others = Counter(
        e.entity_type for preds in predictions for e in preds if e.entity_type not in TYPES
    )
    print(f"other entity types detected (not scored): {dict(others) or 'none'}")

    if show_errors:
        print("\nerrors:")
        for err in errors:
            print(f"  [{err.kind}] {err.entity_type}: {err.value!r}  <-  {err.text}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate PII detection quality.")
    parser.add_argument("--dataset", type=Path, default=Path("eval/dataset.txt"))
    parser.add_argument("--models", nargs="+", default=["en_core_web_lg"])
    parser.add_argument("--threshold", type=float, default=0.4)
    parser.add_argument("--errors", action="store_true", help="print every miss and false positive")
    args = parser.parse_args()

    logging.disable(logging.CRITICAL)  # keep the report readable
    examples = load_dataset(args.dataset)
    for model in args.models:
        run(model, args.threshold, examples, args.errors)


if __name__ == "__main__":
    main()