"""Parsing for Debian relationship fields.

A relationship field is a comma-separated list of groups; a group is a
``|``-separated list of alternatives.  A dependency is satisfied when *any*
alternative in the group is satisfied, which is why the data model is a list
of lists rather than a flat list of names.

Each alternative can carry four kinds of annotation, and all four change its
meaning: an architecture list (``[amd64 !i386]``), an architecture qualifier
(``:any``), a build profile (``<!nocheck>``), and a version constraint.
Build profiles and architecture lists matter for source packages; for a binary
archive the practical ones are the version constraint and the arch qualifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .debversion import satisfies

ALTERNATIVE_RE = re.compile(
    r"""^
    (?P<name>[a-z0-9][a-z0-9+.-]*)
    (?::(?P<qualifier>[a-z0-9-]+))?
    \s*
    (?:\(\s*(?P<operator><<|<=|=|>=|>>)\s*(?P<version>[^)\s]+)\s*\))?
    \s*
    (?:\[(?P<arches>[^\]]*)\])?
    \s*
    (?:<(?P<profiles>[^>]*)>)?
    \s*$""",
    re.VERBOSE,
)


@dataclass(frozen=True)
class Relation:
    name: str
    operator: str = ""
    version: str = ""
    qualifier: str = ""
    arches: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ()

    def matches(self, candidate_version: str | None) -> bool:
        """Does a package (or provider) at *candidate_version* satisfy this?"""

        if not self.operator:
            return True
        if not candidate_version:
            # A versioned dependency can only be satisfied by a versioned
            # Provides, per Policy 7.1.
            return False
        return satisfies(candidate_version, self.operator, self.version)

    def describe(self) -> str:
        parts = [self.name]
        if self.qualifier:
            parts[0] += f":{self.qualifier}"
        if self.operator:
            parts.append(f"({self.operator} {self.version})")
        if self.arches:
            parts.append("[" + " ".join(self.arches) + "]")
        if self.profiles:
            parts.append("<" + " ".join(self.profiles) + ">")
        return " ".join(parts)


@dataclass(frozen=True)
class RelationGroup:
    """One comma-separated entry: a set of alternatives, any of which satisfies."""

    alternatives: tuple[Relation, ...] = field(default_factory=tuple)

    def describe(self) -> str:
        return " | ".join(alternative.describe() for alternative in self.alternatives)


def parse_alternative(text: str) -> Relation:
    match = ALTERNATIVE_RE.match(text.strip())
    if match is None:
        raise ValueError(f"cannot parse relationship alternative: {text!r}")
    return Relation(
        name=match.group("name"),
        operator=match.group("operator") or "",
        version=match.group("version") or "",
        qualifier=match.group("qualifier") or "",
        arches=tuple((match.group("arches") or "").split()),
        profiles=tuple((match.group("profiles") or "").split()),
    )


def parse_relations(value: str) -> list[RelationGroup]:
    """Parse a Depends/Pre-Depends/Recommends-style field."""

    groups: list[RelationGroup] = []
    for chunk in value.replace("\n", " ").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        alternatives = tuple(
            parse_alternative(part) for part in chunk.split("|") if part.strip()
        )
        if alternatives:
            groups.append(RelationGroup(alternatives=alternatives))
    return groups


def parse_provides(value: str) -> list[Relation]:
    """Parse a Provides field into versioned virtual package names."""

    provided: list[Relation] = []
    for chunk in value.replace("\n", " ").split(","):
        chunk = chunk.strip()
        if chunk:
            provided.append(parse_alternative(chunk))
    return provided


def architecture_applies(relation: Relation, architecture: str) -> bool:
    """Evaluate an architecture restriction list for a concrete architecture."""

    if not relation.arches:
        return True
    included = [item for item in relation.arches if not item.startswith("!")]
    excluded = [item[1:] for item in relation.arches if item.startswith("!")]
    if architecture in excluded:
        return False
    if included and architecture not in included and "any" not in included:
        return False
    return True
