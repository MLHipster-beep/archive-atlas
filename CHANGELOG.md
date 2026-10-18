# Changelog

## [0.2.0] - 2026-10-18

### Added

- `index` builds a normalised SQLite database from any tree with `dists/`,
  reading `Packages`, `Packages.gz` and `Packages.xz`.
- Reports: `broken`, `impact`, `cycles`, `duplicates`, `orphans`, `stats`.
- `demo` writes a synthetic archive with five known defects; it is the fixture
  used by the test suite.
- Virtual package resolution, including the Policy 7.1 rule that a versioned
  dependency requires a versioned `Provides`.
- JSON output for every report.

### Fixed

- Reverse dependencies now include package *providers*, so a `Provides:` package
  is not reported as an orphan when something depends on the virtual name.

### Verified

- Version comparison agrees with `dpkg --compare-versions` on 800 randomly
  generated version pairs.

## [0.1.0] - 2026-10-10

### Added

- Debian version comparison implementing Policy §5.6.12.
- Relationship field parser: alternatives, version constraints, architecture
  lists, architecture qualifiers and build profiles.
- `Packages` parser and in-memory dependency graph prototype.
