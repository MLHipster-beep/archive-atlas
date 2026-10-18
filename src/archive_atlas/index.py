"""Building and reading a SQLite index of an APT archive tree.

The index exists so that repeated questions do not re-parse the archive.  A
real Ubuntu archive is several gigabytes of compressed ``Packages`` files;
parsing it once into a normalised schema makes every later question — "what
breaks if this package is removed", "which packages have unsatisfiable
dependencies" — a query rather than a scan.

The schema keeps relationships in their own table rather than as text blobs,
because the interesting questions are graph questions and the alternatives
inside a single dependency group have to stay grouped.
"""

from __future__ import annotations

import gzip
import lzma
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .packages import Package, parse_packages
from .relations import Relation, RelationGroup

SCHEMA = """
CREATE TABLE packages (
    id             INTEGER PRIMARY KEY,
    series         TEXT NOT NULL,
    component      TEXT NOT NULL,
    arch           TEXT NOT NULL,
    name           TEXT NOT NULL,
    version        TEXT NOT NULL,
    section        TEXT NOT NULL DEFAULT '',
    priority       TEXT NOT NULL DEFAULT '',
    filename       TEXT NOT NULL DEFAULT '',
    size           INTEGER NOT NULL DEFAULT 0,
    installed_size INTEGER NOT NULL DEFAULT 0,
    essential      INTEGER NOT NULL DEFAULT 0,
    maintainer     TEXT NOT NULL DEFAULT '',
    UNIQUE (series, component, arch, name, version)
);

CREATE TABLE dependencies (
    package_id INTEGER NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    group_no   INTEGER NOT NULL,
    alt_no     INTEGER NOT NULL,
    name       TEXT NOT NULL,
    operator   TEXT NOT NULL DEFAULT '',
    version    TEXT NOT NULL DEFAULT '',
    qualifier  TEXT NOT NULL DEFAULT '',
    arches     TEXT NOT NULL DEFAULT '',
    profiles   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX dependencies_by_name ON dependencies(name);
CREATE INDEX dependencies_by_package ON dependencies(package_id);
CREATE INDEX packages_by_name ON packages(series, arch, name);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

KIND_FIELDS = (
    ("Depends", "depends"),
    ("Pre-Depends", "pre_depends"),
    ("Recommends", "recommends"),
    ("Provides", "provides"),
    ("Conflicts", "conflicts"),
    ("Breaks", "breaks"),
)


@dataclass
class IndexSummary:
    series: list[str]
    components: list[str]
    architectures: list[str]
    packages: int
    rows: int
    database: Path


def _open_packages(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    if path.suffix == ".xz":
        return lzma.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("rt", encoding="utf-8", errors="replace")


def discover(archive_root: Path, only_series: set[str] | None = None) -> Iterator[tuple[str, str, str, Path]]:
    """Yield ``(series, component, arch, Packages path)`` for an archive tree."""

    dists = archive_root / "dists"
    if not dists.is_dir():
        raise FileNotFoundError(f"no dists/ directory under {archive_root}")

    for series_dir in sorted(path for path in dists.iterdir() if path.is_dir()):
        series = series_dir.name
        if only_series and series not in only_series:
            continue
        for component_dir in sorted(path for path in series_dir.iterdir() if path.is_dir()):
            if component_dir.name.startswith("."):
                continue
            for binary_dir in sorted(path for path in component_dir.iterdir() if path.is_dir()):
                if not binary_dir.name.startswith("binary-"):
                    continue
                arch = binary_dir.name.removeprefix("binary-")
                plain = binary_dir / "Packages"
                if plain.is_file():
                    yield series, component_dir.name, arch, plain
                    continue
                for suffix in (".xz", ".gz"):
                    compressed = binary_dir / f"Packages{suffix}"
                    if compressed.is_file():
                        yield series, component_dir.name, arch, compressed
                        break


def build_index(
    archive_root: Path,
    database: Path,
    only_series: set[str] | None = None,
    force: bool = False,
) -> IndexSummary:
    """Parse every Packages file into *database*."""

    archive_root = archive_root.resolve()
    database = database.resolve()

    if database.exists():
        if not force:
            raise FileExistsError(f"{database} exists; pass force=True or remove it")
        database.unlink()

    connection = sqlite3.connect(database)
    try:
        connection.executescript(SCHEMA)
        series_seen: set[str] = set()
        components: set[str] = set()
        architectures: set[str] = set()
        package_count = 0
        row_count = 0

        with connection:
            for series, component, arch, path in discover(archive_root, only_series):
                series_seen.add(series)
                components.add(component)
                architectures.add(arch)
                with _open_packages(path) as handle:
                    packages = list(parse_packages(handle.read(), series, component))
                for package in packages:
                    package_id = _insert_package(connection, package)
                    row_count += _insert_relations(connection, package_id, package)
                    package_count += 1

            connection.executemany(
                "INSERT INTO meta(key, value) VALUES (?, ?)",
                [
                    ("archive_root", str(archive_root)),
                    ("built_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
                    ("schema_version", "1"),
                ],
            )

        if package_count == 0:
            raise ValueError(f"no Packages files found under {archive_root}/dists")
    finally:
        connection.close()

    return IndexSummary(
        series=sorted(series_seen),
        components=sorted(components),
        architectures=sorted(architectures),
        packages=package_count,
        rows=row_count,
        database=database,
    )


def _insert_package(connection: sqlite3.Connection, package: Package) -> int:
    cursor = connection.execute(
        """
        INSERT INTO packages
            (series, component, arch, name, version, section, priority,
             filename, size, installed_size, essential, maintainer)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            package.series,
            package.component,
            package.architecture,
            package.name,
            package.version,
            package.section,
            package.priority,
            package.filename,
            package.size,
            package.installed_size,
            int(package.essential),
            package.maintainer,
        ),
    )
    return int(cursor.lastrowid)


def _insert_relations(connection: sqlite3.Connection, package_id: int, package: Package) -> int:
    rows: list[tuple] = []
    for kind, attribute in KIND_FIELDS:
        value = getattr(package, attribute)
        if kind == "Provides":
            for alt_no, relation in enumerate(value):  # type: ignore[arg-type]
                rows.append((package_id, kind, 0, alt_no, *_relation_columns(relation)))
            continue
        for group_no, group in enumerate(value):  # type: ignore[arg-type]
            for alt_no, relation in enumerate(group.alternatives):
                rows.append((package_id, kind, group_no, alt_no, *_relation_columns(relation)))

    if not rows:
        return 0
    connection.executemany(
        """
        INSERT INTO dependencies
            (package_id, kind, group_no, alt_no, name, operator, version, qualifier, arches, profiles)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def _relation_columns(relation: Relation) -> tuple[str, str, str, str, str, str]:
    return (
        relation.name,
        relation.operator,
        relation.version,
        relation.qualifier,
        " ".join(relation.arches),
        " ".join(relation.profiles),
    )


def connect(database: Path) -> sqlite3.Connection:
    if not Path(database).is_file():
        raise FileNotFoundError(f"no index at {database}; run 'archive-atlas index' first")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    return connection


def meta(connection: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM meta")}


def load_packages(connection: sqlite3.Connection, series: str, arch: str) -> list[Package]:
    """Reconstruct package objects, with their relationship groups, for analysis."""

    rows = connection.execute(
        """
        SELECT * FROM packages
        WHERE series = ? AND arch = ?
        ORDER BY name, version
        """,
        (series, arch),
    ).fetchall()
    if not rows:
        return []

    relations: dict[int, dict[tuple[str, int], list[Relation]]] = {}
    for row in connection.execute(
        """
        SELECT d.* FROM dependencies d
        JOIN packages p ON p.id = d.package_id
        WHERE p.series = ? AND p.arch = ?
        ORDER BY d.package_id, d.kind, d.group_no, d.alt_no
        """,
        (series, arch),
    ):
        relations.setdefault(row["package_id"], {}).setdefault(
            (row["kind"], row["group_no"]), []
        ).append(
            Relation(
                name=row["name"],
                operator=row["operator"],
                version=row["version"],
                qualifier=row["qualifier"],
                arches=tuple(row["arches"].split()),
                profiles=tuple(row["profiles"].split()),
            )
        )

    packages: list[Package] = []
    for row in rows:
        package = Package(
            name=row["name"],
            version=row["version"],
            architecture=row["arch"],
            series=row["series"],
            component=row["component"],
            section=row["section"],
            priority=row["priority"],
            filename=row["filename"],
            size=row["size"],
            installed_size=row["installed_size"],
            maintainer=row["maintainer"],
            essential=bool(row["essential"]),
        )
        grouped = relations.get(row["id"], {})
        package.depends = _groups(grouped, "Depends")
        package.pre_depends = _groups(grouped, "Pre-Depends")
        package.recommends = _groups(grouped, "Recommends")
        package.conflicts = _groups(grouped, "Conflicts")
        package.breaks = _groups(grouped, "Breaks")
        package.provides = list(grouped.get(("Provides", 0), []))
        packages.append(package)

    return packages


def _groups(grouped: dict[tuple[str, int], list[Relation]], kind: str) -> list[RelationGroup]:
    numbers = sorted({group_no for (name, group_no) in grouped if name == kind})
    return [RelationGroup(alternatives=tuple(grouped[(kind, number)])) for number in numbers]


def series_architectures(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    return [
        (row["series"], row["arch"])
        for row in connection.execute(
            "SELECT DISTINCT series, arch FROM packages ORDER BY series, arch"
        )
    ]
