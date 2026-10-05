"""Parser and evaluator for the ``q`` (query-by-example) and ``orderBy`` params.

Supported subset of the documented ``q`` syntax::

    q=StatusCd='ORA_SVC_NEW';SeverityCd='ORA_SVC_SEV1'
    q=CreationDate>='2026-09-01T00:00:00Z';QueueName='Billing Support'
    q=Title LIKE '%router%'

* Conditions are separated by ``;`` and combined with AND.
* Operators: ``=``, ``!=`` (or ``<>``), ``>``, ``>=``, ``<``, ``<=``, ``LIKE``.
* String values are single-quoted (``''`` escapes a quote); numbers may be bare.
* ``LIKE`` uses ``%`` as wildcard and is case-insensitive.
* A condition on an empty (null) attribute never matches.
"""

import operator
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .models import ServiceRequest


class QueryError(ValueError):
    """Raised for a malformed or unsupported ``q`` / ``orderBy`` expression."""


# Attribute -> coercion applied to the literal in the expression.
_FILTERABLE: dict[str, Callable[[str], Any]] = {
    "SrNumber": str,
    "Title": str,
    "StatusCd": str,
    "StatusTypeCd": str,
    "SeverityCd": str,
    "QueueId": int,
    "QueueName": str,
    "CategoryName": str,
    "ChannelTypeCd": str,
    "PrimaryContactPartyName": str,
    "AssigneeResourceName": str,
    "CreationDate": lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")),
    "LastUpdateDate": lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")),
    "ResolvedDate": lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")),
}

SORTABLE = frozenset(_FILTERABLE) | {"SrId"}

_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "=": operator.eq,
    "!=": operator.ne,
    "<>": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}

_CONDITION = re.compile(
    r"^\s*(?P<attr>[A-Za-z]\w*)\s*(?P<op>>=|<=|!=|<>|=|>|<|\s(?i:LIKE)\s)\s*(?P<value>.+?)\s*$"
)


@dataclass(frozen=True)
class Condition:
    attr: str
    op: str
    value: Any

    def matches(self, sr: ServiceRequest) -> bool:
        actual = getattr(sr, self.attr)
        if actual is None:
            return False
        if self.op == "LIKE":
            return bool(self.value.fullmatch(str(actual)))
        return _OPS[self.op](actual, self.value)


def _split_conditions(q: str) -> list[str]:
    """Split on ``;`` that are not inside single-quoted literals."""
    parts, buf, in_quote = [], [], False
    for ch in q:
        if ch == "'":
            in_quote = not in_quote
        if ch == ";" and not in_quote:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if in_quote:
        raise QueryError("Unterminated quoted value in q expression")
    parts.append("".join(buf))
    return [p for p in parts if p.strip()]


def _unquote(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    return raw


def parse_q(q: str | None) -> list[Condition]:
    if not q:
        return []
    conditions = []
    for part in _split_conditions(q):
        m = _CONDITION.match(part)
        if not m:
            raise QueryError(f"Cannot parse condition: {part.strip()!r}")
        attr, op, raw = m["attr"], m["op"].strip().upper(), _unquote(m["value"])
        if attr not in _FILTERABLE:
            raise QueryError(f"Attribute {attr!r} is not filterable")
        if op == "LIKE":
            pattern = ".*".join(re.escape(chunk) for chunk in raw.split("%"))
            conditions.append(Condition(attr, op, re.compile(pattern, re.IGNORECASE | re.DOTALL)))
            continue
        try:
            value = _FILTERABLE[attr](raw)
        except ValueError as exc:
            raise QueryError(f"Invalid value for {attr}: {raw!r}") from exc
        conditions.append(Condition(attr, op, value))
    return conditions


def parse_order_by(order_by: str | None) -> list[tuple[str, bool]]:
    """Parse ``Attr[:asc|:desc],...`` into ``[(attr, descending), ...]``."""
    if not order_by:
        return []
    result = []
    for token in order_by.split(","):
        attr, _, direction = token.strip().partition(":")
        direction = direction.lower() or "asc"
        if attr not in SORTABLE:
            raise QueryError(f"Attribute {attr!r} is not sortable")
        if direction not in ("asc", "desc"):
            raise QueryError(f"Invalid sort direction {direction!r}")
        result.append((attr, direction == "desc"))
    return result


def apply_order(items: list[ServiceRequest], order: list[tuple[str, bool]]) -> list[ServiceRequest]:
    # Stable sorts applied from the least to the most significant key.
    # Nulls always sort last, whatever the direction.
    for attr, descending in reversed(order):
        present = [sr for sr in items if getattr(sr, attr) is not None]
        missing = [sr for sr in items if getattr(sr, attr) is None]
        present.sort(key=lambda sr: getattr(sr, attr), reverse=descending)
        items = present + missing
    return items
