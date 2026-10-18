"""Output formatting.

Text output is for humans reading a terminal; JSON is the contract for
anything automated.  Both are produced from the same analysis objects, so a
number cannot appear in one and not the other.
"""

from __future__ import annotations

import json
from typing import Iterable, Sequence


def human_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    size = float(value)
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    materialised = [["" if cell is None else str(cell) for cell in row] for row in rows]
    if not materialised:
        return "  (none)"
    widths = [len(header) for header in headers]
    for row in materialised:
        for position, cell in enumerate(row):
            widths[position] = max(widths[position], len(cell))

    lines = ["  " + "  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)).rstrip()]
    lines.append("  " + "  ".join("-" * width for width in widths))
    for row in materialised:
        lines.append("  " + "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(lines)


def to_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=False)


def section(title: str) -> str:
    return f"{title}\n{'-' * len(title)}"
