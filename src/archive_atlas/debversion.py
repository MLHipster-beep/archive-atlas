"""Debian version comparison, implementing Policy §5.6.12.

This is the piece of an archive tool that cannot be approximated.  Version
comparison decides whether a dependency is satisfied, whether an upgrade is
an upgrade, and whether two packages in the same suite are the same thing.
Getting ``~`` wrong by one position silently inverts pre-release ordering, and
getting the epoch wrong makes ``1:0.1`` sort below ``2.0`` when it must sort
above it.

The algorithm compares three fields in order — epoch, upstream version,
Debian revision — and the latter two are compared by alternating non-digit and
digit runs, where ``~`` sorts before the empty string and letters sort before
punctuation.
"""

from __future__ import annotations

OPERATORS = ("<<", "<=", "=", ">=", ">>")


def split_version(version: str) -> tuple[int, str, str]:
    """Split ``[epoch:]upstream[-revision]`` into its three parts."""

    epoch = 0
    rest = version.strip()

    head, separator, tail = rest.partition(":")
    if separator:
        if head.isdigit():
            epoch = int(head)
            rest = tail
        # A non-numeric epoch means the colon belongs to the upstream version,
        # which is legal (if unwise) and must not be reinterpreted.

    upstream, separator, revision = rest.rpartition("-")
    if not separator:
        return epoch, rest, ""
    return epoch, upstream, revision


def _order(character: str) -> int:
    """Collation order for a single character.

    ``~`` sorts before everything, including the end of the string; letters
    sort before punctuation, which is represented by offsetting non-alnum
    characters by 256.
    """

    if character.isdigit():
        return 0
    if character.isalpha():
        return ord(character)
    if character == "~":
        return -1
    if character:
        return ord(character) + 256
    return 0


def _compare_part(left: str, right: str) -> int:
    """Compare two version fragments using dpkg's alternating-run algorithm."""

    i = j = 0
    left_len, right_len = len(left), len(right)

    while i < left_len or j < right_len:
        # Non-digit run.  The loop runs while either side is still in a
        # non-digit character, so a run that ends early compares against the
        # empty string — which is what makes "1.0" sort before "1.0a".
        while (i < left_len and not left[i].isdigit()) or (j < right_len and not right[j].isdigit()):
            left_order = _order(left[i]) if i < left_len else 0
            right_order = _order(right[j]) if j < right_len else 0
            if left_order != right_order:
                return -1 if left_order < right_order else 1
            i += 1
            j += 1

        # Leading zeros never affect the numeric value.
        while i < left_len and left[i] == "0":
            i += 1
        while j < right_len and right[j] == "0":
            j += 1

        # Digit run: the longer run is the larger number.  Equal-length runs
        # are compared lexicographically and remembered in case the lengths
        # differ later.
        first_difference = 0
        while i < left_len and j < right_len and left[i].isdigit() and right[j].isdigit():
            if first_difference == 0 and left[i] != right[j]:
                first_difference = -1 if left[i] < right[j] else 1
            i += 1
            j += 1

        if i < left_len and left[i].isdigit():
            return 1
        if j < right_len and right[j].isdigit():
            return -1
        if first_difference:
            return first_difference

    return 0


def compare(left: str, right: str) -> int:
    """Return -1, 0 or 1 as *left* sorts before, equal to, or after *right*."""

    left_epoch, left_upstream, left_revision = split_version(left)
    right_epoch, right_upstream, right_revision = split_version(right)

    if left_epoch != right_epoch:
        return -1 if left_epoch < right_epoch else 1

    upstream = _compare_part(left_upstream, right_upstream)
    if upstream:
        return upstream

    return _compare_part(left_revision, right_revision)


def satisfies(version: str, operator: str, constraint: str) -> bool:
    """Does *version* satisfy ``operator constraint``?"""

    if not operator:
        return True
    result = compare(version, constraint)
    if operator == "<<":
        return result < 0
    if operator == "<=":
        return result <= 0
    if operator == "=":
        return result == 0
    if operator == ">=":
        return result >= 0
    if operator == ">>":
        return result > 0
    raise ValueError(f"unknown relation operator: {operator!r}")


def sort_key(version: str):
    """A key usable with :func:`sorted` that follows Debian ordering."""

    class _Key:
        __slots__ = ("value",)

        def __init__(self, value: str) -> None:
            self.value = value

        def __lt__(self, other: "_Key") -> bool:
            return compare(self.value, other.value) < 0

        def __eq__(self, other: object) -> bool:
            return isinstance(other, _Key) and compare(self.value, other.value) == 0

    return _Key(version)
