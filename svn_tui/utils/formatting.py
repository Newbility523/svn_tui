from __future__ import annotations


def format_byte_size(size: int) -> str:
    one_mib = 1024 * 1024
    one_gib = 1024 * one_mib
    if size < one_mib:
        return format_size(size / 1024, "k")
    if size < one_gib:
        return format_size(size / one_mib, "m")
    return format_size(size / one_gib, "g")


def format_size(value: float, unit: str) -> str:
    number = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{number}{unit}"
