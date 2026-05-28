"""Deterministic specs comparison — reject matches whose specs contradict."""

from __future__ import annotations


def specs_compatible(extracted: dict, candidate: dict) -> tuple[bool, list[str]]:
    """
    Return (compatible, conflicts).
    Compares numeric and categorical specs that both sides have.
    """
    conflicts: list[str] = []
    for key, value in extracted.items():
        if key not in candidate or candidate[key] is None or value is None:
            continue
        if isinstance(value, (int, float)) and isinstance(candidate[key], (int, float)):
            if abs(value - candidate[key]) / max(abs(value), 1) > 0.1:
                conflicts.append(f"{key}: extracted={value}, candidate={candidate[key]}")
        else:
            if str(value).lower() != str(candidate[key]).lower():
                conflicts.append(f"{key}: extracted={value}, candidate={candidate[key]}")
    return len(conflicts) == 0, conflicts
