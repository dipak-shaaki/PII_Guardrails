import re
from dataclasses import dataclass
from pathlib import Path

MARKUP = re.compile(r"\[\[([A-Z_]+)\|(.+?)\]\]")


@dataclass(frozen=True, slots=True)
class GoldSpan:
    entity_type: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Example:
    text: str
    spans: tuple[GoldSpan, ...]


def parse_example(marked: str) -> Example:
    """Turn 'Hi [[PERSON|Sita]]' into plain text plus exact gold spans."""
    parts: list[str] = []
    spans: list[GoldSpan] = []
    last = 0  # position in the marked-up string
    pos = 0  # length of the plain text built so far
    for m in MARKUP.finditer(marked):
        before = marked[last : m.start()]
        parts.append(before)
        pos += len(before)
        value = m.group(2)
        spans.append(GoldSpan(m.group(1), pos, pos + len(value)))
        parts.append(value)
        pos += len(value)
        last = m.end()
    parts.append(marked[last:])
    return Example(text="".join(parts), spans=tuple(spans))


def load_dataset(path: Path) -> list[Example]:
    """One example per line. Blank lines and lines starting with # are ignored."""
    examples = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            examples.append(parse_example(line))
    return examples