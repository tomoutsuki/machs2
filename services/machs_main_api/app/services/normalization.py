from typing import Optional


def normalize_name(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return " ".join(value.strip().lower().split())


def normalize_cpf(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits or None


def normalize_birthdate(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.strip()
