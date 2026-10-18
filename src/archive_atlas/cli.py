"""Command line interface for archive-atlas."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .analyze import Universe, stats
from .demo import create_demo_archive
from .index import build_index, connect, load_packages, meta, series_architectures
from .render import human_bytes, table, to_json

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="archive-atlas",
        description="Index an APT archive and answer dependency questions about it.",
    )
    parser.add_argument("--version", action="version", version=f"archive-atlas {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index = subparsers.add_parser("index", help="parse an archive tree into a SQLite database")
    index.add_argument("archive", help="path containing dists/<series>/<component>/binary-<arch>/")
    index.add_argument("-o", "--output", default="archive.db", help="database path")
    index.add_argument("--series", action="append", default=[], help="limit to a series (repeatable)")
    index.add_argument("--force", action="store_true", help="overwrite an existing database")

    demo = subparsers.add_parser("demo", help="write a small synthetic archive")
    demo.add_argument("directory")

    subparsers.add_parser("stats", help="counts and sizes by series, component and section").add_argument(
        "database"
    )

    impact = subparsers.add_parser("impact", help="packages affected if one package were removed")
    impact.add_argument("database")
    impact.add_argument("name")
    _add_common(impact)

    for name, help_text in (
        ("broken", "dependencies that nothing in the archive satisfies"),
        ("duplicates", "packages with several versions or components"),
        ("cycles", "dependency cycles"),
        ("orphans", "packages nothing depends on"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("database")
        _add_common(command)
        if name == "orphans":
            command.add_argument("--limit", type=int, default=20)

    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--series", help="limit to one series")
    parser.add_argument("--arch", help="limit to one architecture")
    parser.add_argument("--format", choices=("text", "json"), default="text")


def _universes(connection, series: str | None, arch: str | None) -> list[Universe]:
    pairs = series_architectures(connection)
    if series:
        pairs = [pair for pair in pairs if pair[0] == series]
    if arch:
        pairs = [pair for pair in pairs if pair[1] == arch]
    if not pairs:
        raise LookupError("no packages match the selected series/architecture")
    return [Universe.build(item_series, item_arch, load_packages(connection, item_series, item_arch)) for item_series, item_arch in pairs]


def _emit(payload: dict, output_format: str, render_text) -> None:
    if output_format == "json":
        print(to_json(payload))
    else:
        render_text()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "demo":
        root = create_demo_archive(Path(args.directory))
        print(f"wrote synthetic archive to {root}")
        print(f"index it with: archive-atlas index {root} -o demo.db")
        return EXIT_OK

    if args.command == "index":
        try:
            summary = build_index(
                Path(args.archive),
                Path(args.output),
                only_series=set(args.series) or None,
                force=args.force,
            )
        except (FileNotFoundError, FileExistsError, ValueError) as error:
            print(f"archive-atlas: {error}", file=sys.stderr)
            return EXIT_USAGE
        print(
            f"indexed {summary.packages} packages ({summary.rows} relationship rows) "
            f"from {', '.join(summary.series)} into {summary.database}"
        )
        print(
            f"components: {', '.join(summary.components)}; "
            f"architectures: {', '.join(summary.architectures)}"
        )
        return EXIT_OK

    try:
        connection = connect(Path(args.database))
    except FileNotFoundError as error:
        print(f"archive-atlas: {error}", file=sys.stderr)
        return EXIT_USAGE

    try:
        if args.command == "stats":
            return _stats(connection, args)
        if args.command == "broken":
            return _broken(connection, args)
        if args.command == "impact":
            return _impact(connection, args)
        if args.command == "duplicates":
            return _duplicates(connection, args)
        if args.command == "cycles":
            return _cycles(connection, args)
        if args.command == "orphans":
            return _orphans(connection, args)
    except LookupError as error:
        print(f"archive-atlas: {error}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        connection.close()

    return EXIT_USAGE


def _stats(connection, args) -> int:
    payload = stats(connection)
    payload["archive"] = meta(connection)

    def render() -> None:
        print(f"{payload['packages']} packages across {len(payload['by_series'])} series")
        print(f"architectures: {', '.join(payload['architectures'])}")
        print()
        print("by series")
        print(
            table(
                ["series", "packages", "download", "installed"],
                [
                    (
                        row["series"],
                        row["packages"],
                        human_bytes(row["download_bytes"]),
                        f"{row['installed_kib'] / 1024:.1f} MiB",
                    )
                    for row in payload["by_series"]
                ],
            )
        )
        print()
        print("by component")
        print(table(["component", "packages"], [(row["component"], row["packages"]) for row in payload["by_component"]]))
        print()
        print("largest sections")
        print(table(["section", "packages"], [(row["section"], row["packages"]) for row in payload["by_section"]]))

    _emit(payload, "text", render)
    return EXIT_OK


def _broken(connection, args) -> int:
    results = []
    for universe in _universes(connection, args.series, args.arch):
        findings = universe.broken()
        results.append({"series": universe.series, "arch": universe.arch, "findings": [f.as_dict() for f in findings]})

    total = sum(len(result["findings"]) for result in results)

    def render() -> None:
        for result in results:
            if not result["findings"]:
                print(f"{result['series']}/{result['arch']}: clean")
                continue
            print(f"{result['series']}/{result['arch']}: {len(result['findings'])} unsatisfiable dependencies")
            print(
                table(
                    ["package", "version", "dependency", "reason"],
                    [
                        (finding["package"], finding["version"], finding["dependency"], finding["reason"])
                        for finding in result["findings"]
                    ],
                )
            )
        print(f"\n{total} finding(s) across {len(results)} series/arch pair(s)")

    _emit({"command": "broken", "total": total, "results": results}, args.format, render)
    return EXIT_FINDINGS if total else EXIT_OK


def _impact(connection, args) -> int:
    universes = _universes(connection, args.series, args.arch)
    results = []
    for universe in universes:
        if not universe.find(args.name):
            continue
        affected = universe.impact(args.name)
        results.append(
            {
                "series": universe.series,
                "arch": universe.arch,
                "package": args.name,
                "affected": affected,
                "count": len(affected),
            }
        )

    if not results:
        raise LookupError(f"{args.name!r} is not present in the selected universes")

    def render() -> None:
        for result in results:
            print(f"{result['series']}/{result['arch']}: removing {result['package']} affects {result['count']} package(s)")
            if result["affected"]:
                print("  " + ", ".join(result["affected"]))
        covering = ", ".join(f"{r['series']}/{r['arch']}" for r in results)
        print(f"\npresent in: {covering}")

    _emit({"command": "impact", "results": results}, args.format, render)
    return EXIT_OK


def _duplicates(connection, args) -> int:
    results = []
    for universe in _universes(connection, args.series, args.arch):
        found = universe.duplicates()
        results.append(
            {
                "series": universe.series,
                "arch": universe.arch,
                "duplicates": [
                    {
                        "package": item.name,
                        "kind": item.kind,
                        "versions": item.versions,
                        "components": item.components,
                    }
                    for item in found
                ],
            }
        )
    total = sum(len(result["duplicates"]) for result in results)

    def render() -> None:
        for result in results:
            print(f"{result['series']}/{result['arch']}: {len(result['duplicates'])} duplicate package name(s)")
            print(
                table(
                    ["package", "kind", "versions", "components"],
                    [
                        (
                            item["package"],
                            item["kind"],
                            ", ".join(item["versions"]),
                            ", ".join(item["components"]),
                        )
                        for item in result["duplicates"]
                    ],
                )
            )

    _emit({"command": "duplicates", "total": total, "results": results}, args.format, render)
    return EXIT_FINDINGS if total else EXIT_OK


def _cycles(connection, args) -> int:
    results = []
    for universe in _universes(connection, args.series, args.arch):
        found = universe.cycles()
        results.append({"series": universe.series, "arch": universe.arch, "cycles": found})
    total = sum(len(result["cycles"]) for result in results)

    def render() -> None:
        for result in results:
            if not result["cycles"]:
                print(f"{result['series']}/{result['arch']}: no cycles")
                continue
            print(f"{result['series']}/{result['arch']}: {len(result['cycles'])} cycle(s)")
            for cycle in result["cycles"]:
                print("  " + " -> ".join(cycle + [cycle[0]]))

    _emit({"command": "cycles", "total": total, "results": results}, args.format, render)
    return EXIT_FINDINGS if total else EXIT_OK


def _orphans(connection, args) -> int:
    results = []
    for universe in _universes(connection, args.series, args.arch):
        found = universe.orphans()
        results.append(
            {
                "series": universe.series,
                "arch": universe.arch,
                "count": len(found),
                "packages": [
                    {"package": package.name, "version": package.version, "section": package.section}
                    for package in found[: args.limit]
                ],
            }
        )
    total = sum(result["count"] for result in results)

    def render() -> None:
        for result in results:
            print(f"{result['series']}/{result['arch']}: {result['count']} package(s) with no reverse dependency")
            print(
                table(
                    ["package", "version", "section"],
                    [(item["package"], item["version"], item["section"]) for item in result["packages"]],
                )
            )

    _emit({"command": "orphans", "total": total, "results": results}, args.format, render)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
