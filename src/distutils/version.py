from __future__ import annotations

import re
from functools import total_ordering
from typing import Any

try:
    from packaging.version import InvalidVersion, Version
except Exception:  # pragma: no cover - packaging is present in the current venv
    InvalidVersion = Exception  # type: ignore[assignment]
    Version = None  # type: ignore[assignment]


def _tokenize(value: str) -> tuple[tuple[int, Any], ...]:
    tokens: list[tuple[int, Any]] = []
    for part in re.findall(r"\d+|[a-zA-Z]+|[^a-zA-Z0-9]+", value):
        if part.isdigit():
            tokens.append((0, int(part)))
        elif part.isalpha():
            tokens.append((1, part.lower()))
    return tuple(tokens)


@total_ordering
class LooseVersion:
    def __init__(self, vstring: str | Any = "") -> None:
        self.vstring = str(vstring)
        self.version = self._build_key(self.vstring)

    @staticmethod
    def _build_key(vstring: str) -> tuple[int, Any]:
        if Version is not None:
            try:
                return (0, Version(vstring))
            except InvalidVersion:
                pass
        return (1, _tokenize(vstring))

    def _coerce_other(self, other: Any) -> tuple[int, Any] | NotImplemented:
        if isinstance(other, LooseVersion):
            return other.version
        if isinstance(other, str):
            return self._build_key(other)
        try:
            return self._build_key(str(other))
        except Exception:
            return NotImplemented

    def _compare(self, other: Any, op) -> bool | NotImplemented:
        other_key = self._coerce_other(other)
        if other_key is NotImplemented:
            return NotImplemented
        return op(self.version, other_key)

    def __repr__(self) -> str:
        return f"LooseVersion('{self.vstring}')"

    def __str__(self) -> str:
        return self.vstring

    def __eq__(self, other: Any) -> bool | NotImplemented:
        return self._compare(other, lambda a, b: a == b)

    def __lt__(self, other: Any) -> bool | NotImplemented:
        return self._compare(other, lambda a, b: a < b)


class StrictVersion(LooseVersion):
    pass
