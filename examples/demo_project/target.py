"""Intentionally inefficient example used by the Mock provider demo."""


def count_matches(values: list[int], wanted: list[int]) -> int:
    count = 0
    for value in values:
        if value in wanted:
            count += 1
    return count

