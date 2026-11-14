"""Repair text that was decoded as Latin-1 instead of UTF-8."""

from __future__ import annotations


def repair_text(value: str) -> str:
    """Turn 'Affairâ\\x80\\x94Why' back into an em dash. Leave clean text alone."""
    if not isinstance(value, str) or not value:
        return value if isinstance(value, str) else ""
    current = value
    for _ in range(2):
        if "â" not in current and "Ã" not in current and "Â" not in current:
            break
        try:
            fixed = current.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if fixed == current:
            break
        current = fixed
    return current
