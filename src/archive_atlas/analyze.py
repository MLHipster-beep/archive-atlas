"""Dependency analysis over one (series, architecture) universe.

An archive question is almost always a graph question.  The universe here is
one suite's binary packages for one architecture, because that is the set apt
actually resolves against: dependencies never cross series, and an amd64
package cannot satisfy an arm64 dependency.

Two implementation choices are worth stating:

* Virtual packages are first-class.  A dependency on ``mail-transport-agent``
  is satisfied by a provider, and a *versioned* dependency on a virtual name
  is only satisfied by a *versioned* ``Provides`` — the distinction that makes
  dependency resolution correct rather than approximately correct.
* Cycle detection is iterative Tarjan.  A real archive has tens of thousands of
  nodes and recursion would hit the interpreter limit on exactly the archives
  where the answer matters.
"""

from __future__ import annotations

import sqlite3
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

from .packages import Package
from .relations import Relation, RelationGroup, architecture_applies


@dataclass
class BrokenDependency:
    package: str
    version: str
    group: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "package": self.package,
            "version": self.version,
            "dependency": self.group,
            "reason": self.reason,
        }


@dataclass
class Duplicate:
    name: str
    kind: str
    versions: list[str]
    components: list[str]


@dataclass
class Universe:
    series: str
    arch: str
    by_name: dict[str, list[Package]] = field(default_factory=dict)
    providers: dict[str, list[tuple[Package, str | None]]] = field(default_factory=dict)

    @classmethod
    def build(cls, series: str, arch: str, packages: Iterable[Package]) -> "Universe":
        universe = cls(series=series, arch=arch)
        for package in packages:
            universe.by_name.setdefault(package.name, []).append(package)
            for provide in package.provides:
                universe.providers.setdefault(provide.name, []).append(
                    (package, provide.version or None)
                )
        return universe

    # -- resolution ---------------------------------------------------------

    def resolve(self, relation: Relation) -> bool:
        if not architecture_applies(relation, self.arch):
            return False
        for package in self.by_name.get(relation.name, ()):
            if relation.matches(package.version):
                return True
        for provider, provided_version in self.providers.get(relation.name, ()):
            if relation.matches(provided_version):
                return True
        return False

    def group_satisfied(self, group: RelationGroup) -> bool:
        return any(self.resolve(alternative) for alternative in group.alternatives)

    def applicable(self, group: RelationGroup) -> bool:
        """False when every alternative is architecture-restricted away."""

        return any(architecture_applies(alternative, self.arch) for alternative in group.alternatives)

    def why_unsatisfied(self, group: RelationGroup) -> str:
        names = [alternative.name for alternative in group.alternatives]
        if not any(name in self.by_name or name in self.providers for name in names):
            return "no package provides " + " or ".join(sorted(set(names)))
        return "version constraint not satisfied by any candidate"

    # -- reports ------------------------------------------------------------

    def broken(self) -> list[BrokenDependency]:
        broken: list[BrokenDependency] = []
        for name in sorted(self.by_name):
            for package in self.by_name[name]:
                for group in package.hard_dependencies:
                    if not self.applicable(group):
                        continue
                    if not self.group_satisfied(group):
                        broken.append(
                            BrokenDependency(
                                package=package.name,
                                version=package.version,
                                group=group.describe(),
                                reason=self.why_unsatisfied(group),
                            )
                        )
        return broken

    def reverse_graph(self) -> dict[str, set[str]]:
        """Map each package name to the names that depend on it.

        Virtual packages count too: if ``mutt`` depends on
        ``mail-transport-agent`` and ``postfix`` provides it, then postfix has
        a reverse dependency.  Without that edge, every provider in the archive
        would be reported as an orphan, which is exactly backwards.
        """

        reverse: dict[str, set[str]] = {name: set() for name in self.by_name}
        for name, packages in self.by_name.items():
            for package in packages:
                for group in package.hard_dependencies:
                    for alternative in group.alternatives:
                        if alternative.name in reverse:
                            reverse[alternative.name].add(name)
                        for provider, _ in self.providers.get(alternative.name, ()):
                            reverse.setdefault(provider.name, set()).add(name)
        return reverse

    def impact(self, name: str) -> list[str]:
        """Every package that would be left with an unsatisfied dependency."""

        if name not in self.by_name:
            raise KeyError(f"{name} is not in {self.series}/{self.arch}")
        reverse = self.reverse_graph()
        affected: set[str] = set()
        queue: deque[str] = deque([name])
        while queue:
            current = queue.popleft()
            for dependent in reverse.get(current, ()):
                if dependent not in affected and dependent != name:
                    affected.add(dependent)
                    queue.append(dependent)
        return sorted(affected)

    def dependency_graph(self) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = {name: set() for name in self.by_name}
        for name, packages in self.by_name.items():
            for package in packages:
                for group in package.hard_dependencies:
                    for alternative in group.alternatives:
                        if alternative.name in graph and alternative.name != name:
                            graph[name].add(alternative.name)
        return graph

    def cycles(self) -> list[list[str]]:
        components = strongly_connected_components(self.dependency_graph())
        return sorted(
            (sorted(component) for component in components if len(component) > 1),
            key=lambda component: (-len(component), component),
        )

    def duplicates(self) -> list[Duplicate]:
        found: list[Duplicate] = []
        for name in sorted(self.by_name):
            packages = self.by_name[name]
            versions = sorted({package.version for package in packages})
            components = sorted({package.component for package in packages})
            if len(versions) > 1:
                found.append(Duplicate(name=name, kind="multiple versions", versions=versions, components=components))
            elif len(components) > 1:
                found.append(Duplicate(name=name, kind="component overlap", versions=versions, components=components))
        return found

    def orphans(self) -> list[Package]:
        reverse = self.reverse_graph()
        result: list[Package] = []
        for name in sorted(self.by_name):
            if reverse.get(name):
                continue
            for package in self.by_name[name]:
                if package.essential or package.priority in {"required", "important"}:
                    continue
                result.append(package)
        return result

    def find(self, name: str) -> list[Package]:
        return self.by_name.get(name, [])


def strongly_connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    """Iterative Tarjan's algorithm.

    Returns every component, including the trivial single-node ones; callers
    that only care about cycles filter by size.
    """

    index_counter = 0
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    stack: list[str] = []
    components: list[list[str]] = []

    for root in sorted(graph):
        if root in indices:
            continue
        indices[root] = lowlink[root] = index_counter
        index_counter += 1
        stack.append(root)
        on_stack[root] = True

        work: list[tuple[str, Iterable[str]]] = [(root, iter(sorted(graph[root])))]
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in graph:
                    continue
                if child not in indices:
                    indices[child] = lowlink[child] = index_counter
                    index_counter += 1
                    stack.append(child)
                    on_stack[child] = True
                    work.append((child, iter(sorted(graph[child]))))
                    advanced = True
                    break
                if on_stack.get(child):
                    lowlink[node] = min(lowlink[node], indices[child])
            if advanced:
                continue

            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])

            if lowlink[node] == indices[node]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack[member] = False
                    component.append(member)
                    if member == node:
                        break
                components.append(component)

    return components


def stats(connection: sqlite3.Connection) -> dict[str, object]:
    """Aggregate counts and sizes with SQL rather than by loading packages."""

    total = connection.execute("SELECT COUNT(*) AS count FROM packages").fetchone()["count"]
    by_series = [
        {
            "series": row["series"],
            "packages": row["count"],
            "download_bytes": row["size"],
            "installed_kib": row["installed"],
        }
        for row in connection.execute(
            """
            SELECT series, COUNT(*) AS count, SUM(size) AS size, SUM(installed_size) AS installed
            FROM packages GROUP BY series ORDER BY series
            """
        )
    ]
    by_component = [
        {"component": row["component"], "packages": row["count"]}
        for row in connection.execute(
            "SELECT component, COUNT(*) AS count FROM packages GROUP BY component ORDER BY count DESC"
        )
    ]
    by_section = [
        {"section": row["section"] or "(none)", "packages": row["count"]}
        for row in connection.execute(
            """
            SELECT section, COUNT(*) AS count FROM packages
            GROUP BY section ORDER BY count DESC, section LIMIT 15
            """
        )
    ]
    architectures = [
        row["arch"] for row in connection.execute("SELECT DISTINCT arch FROM packages ORDER BY arch")
    ]
    return {
        "packages": total,
        "architectures": architectures,
        "by_series": by_series,
        "by_component": by_component,
        "by_section": by_section,
    }
