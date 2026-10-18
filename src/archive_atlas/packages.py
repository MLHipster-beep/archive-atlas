"""The package model and the ``Packages`` file parser.

``Packages`` files are RFC822 paragraphs, one per binary package.  This parser
is deliberately small: it needs fields and continuations, and it needs to
survive the malformed stanzas that exist in real archives rather than abort
the whole index for one bad paragraph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator

from .relations import Relation, RelationGroup, parse_provides, parse_relations


def parse_stanzas(text: str) -> Iterator[dict[str, str]]:
    """Yield one dict per paragraph, folding continuation lines."""

    stanza: dict[str, str] = {}
    current: str | None = None

    for line in text.splitlines():
        if not line.strip():
            if stanza:
                yield stanza
            stanza = {}
            current = None
            continue
        if line[0] in " \t":
            if current is not None:
                stanza[current] += "\n" + line[1:]
            continue
        name, separator, value = line.partition(":")
        if not separator:
            continue
        current = name.strip()
        stanza[current] = value.strip()

    if stanza:
        yield stanza


@dataclass
class Package:
    name: str
    version: str
    architecture: str
    series: str
    component: str
    section: str = ""
    priority: str = ""
    filename: str = ""
    size: int = 0
    installed_size: int = 0
    maintainer: str = ""
    essential: bool = False
    depends: list[RelationGroup] = field(default_factory=list)
    pre_depends: list[RelationGroup] = field(default_factory=list)
    recommends: list[RelationGroup] = field(default_factory=list)
    provides: list[Relation] = field(default_factory=list)
    conflicts: list[RelationGroup] = field(default_factory=list)
    breaks: list[RelationGroup] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.series, self.architecture, self.name, self.version)

    @property
    def hard_dependencies(self) -> list[RelationGroup]:
        return self.depends + self.pre_depends

    def provided_names(self) -> list[str]:
        return [relation.name for relation in self.provides]

    def describe(self) -> str:
        return f"{self.name} {self.version} [{self.series}/{self.architecture}]"


def package_from_stanza(stanza: dict[str, str], series: str, component: str) -> Package | None:
    name = stanza.get("Package", "").strip()
    version = stanza.get("Version", "").strip()
    architecture = stanza.get("Architecture", "").strip()
    if not (name and version and architecture):
        return None

    def as_int(value: str) -> int:
        try:
            return int(value.strip() or 0)
        except ValueError:
            return 0

    return Package(
        name=name,
        version=version,
        architecture=architecture,
        series=series,
        component=component,
        section=stanza.get("Section", "").strip(),
        priority=stanza.get("Priority", "").strip(),
        filename=stanza.get("Filename", "").strip(),
        size=as_int(stanza.get("Size", "0")),
        installed_size=as_int(stanza.get("Installed-Size", "0")),
        maintainer=stanza.get("Maintainer", "").strip(),
        essential=stanza.get("Essential", "").strip().lower() == "yes",
        depends=parse_relations(stanza.get("Depends", "")),
        pre_depends=parse_relations(stanza.get("Pre-Depends", "")),
        recommends=parse_relations(stanza.get("Recommends", "")),
        provides=parse_provides(stanza.get("Provides", "")),
        conflicts=parse_relations(stanza.get("Conflicts", "")),
        breaks=parse_relations(stanza.get("Breaks", "")),
    )


def parse_packages(text: str, series: str, component: str) -> Iterable[Package]:
    for stanza in parse_stanzas(text):
        package = package_from_stanza(stanza, series, component)
        if package is not None:
            yield package
