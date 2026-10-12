import re
from collections.abc import Iterable
from dataclasses import dataclass, field

TOKEN_PATTERN = re.compile(r"<([A-Z_]+)_(\d+)>")


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


@dataclass
class TokenVault:
    """Per-session mapping between PII values and their tokens."""

    token_to_value: dict[str, str] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    _lookup: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)

    def get_or_create_token(self, entity_type: str, value: str) -> str:
        """Return the existing token for this value, or mint the next one."""
        key = (entity_type, _normalize(value))
        existing = self._lookup.get(key)
        if existing:
            return existing
        self.counters[entity_type] = self.counters.get(entity_type, 0) + 1
        token = f"<{entity_type}_{self.counters[entity_type]}>"
        self.token_to_value[token] = value
        self._lookup[key] = token
        return token

    def restore(self, text: str, only_types: Iterable[str] | None = None) -> str:
        """Swap tokens back to real values. Unknown tokens are left untouched."""
        allowed = set(only_types) if only_types is not None else None

        def _sub(match: re.Match[str]) -> str:
            token = match.group(0)
            if allowed is not None and match.group(1) not in allowed:
                return token
            return self.token_to_value.get(token, token)

        return TOKEN_PATTERN.sub(_sub, text)

    def to_dict(self) -> dict:
        return {"token_to_value": self.token_to_value, "counters": self.counters}

    @classmethod
    def from_dict(cls, data: dict) -> TokenVault:
        vault = cls(
            token_to_value=dict(data.get("token_to_value", {})),
            counters=dict(data.get("counters", {})),
        )
        for token, value in vault.token_to_value.items():
            match = TOKEN_PATTERN.fullmatch(token)
            if match:
                vault._lookup[(match.group(1), _normalize(value))] = token
        return vault