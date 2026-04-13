import re
from typing import Iterable, Set

TOKEN_RE = re.compile(r"^[a-z]+\.[a-z0-9_]+$")


def normalize_attribute(attr: str) -> str:
    token = attr.strip().lower()
    if not TOKEN_RE.match(token):
        raise ValueError("invalid attribute token: {0}".format(attr))
    if "=" in token or ":" in token:
        raise ValueError("invalid attribute syntax")
    return token


def normalize_policy_expression(policy: str) -> str:
    if "=" in policy or ":" in policy:
        raise ValueError("invalid policy syntax: use dot notation")

    compact = policy.replace("(", " ").replace(")", " ")
    parts = re.split(r"\s+(AND|OR)\s+", compact.strip())
    normalized = []
    for part in parts:
        value = part.strip()
        if not value:
            continue
        if value in {"AND", "OR"}:
            normalized.append(value)
        else:
            normalized.append(normalize_attribute(value))
    if not normalized:
        raise ValueError("empty policy")
    return " ".join(normalized)


def evaluate_policy(policy: str, attrs: Iterable[str]) -> bool:
    attrs_set: Set[str] = set(normalize_attribute(a) for a in attrs)
    tokens = policy.replace("(", " ").replace(")", " ").split()

    if len(tokens) == 1:
        return tokens[0] in attrs_set

    result = None
    current_op = None
    for tok in tokens:
        if tok in {"AND", "OR"}:
            current_op = tok
            continue
        current = tok in attrs_set
        if result is None:
            result = current
        elif current_op == "AND":
            result = result and current
        elif current_op == "OR":
            result = result or current
    return bool(result)
