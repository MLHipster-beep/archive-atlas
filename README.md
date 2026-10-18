# archive-atlas

Index an APT archive once, then ask it dependency questions in milliseconds:
what is broken, what breaks if a package is removed, which packages are in a
cycle, which names exist twice.

```
$ archive-atlas broken demo.db
noble/amd64: 2 unsatisfiable dependencies
  package  version   dependency                     reason
  -------  --------  -----------------------------  -------------------------------------------------
  nginx    1.24.0-1  libnginx-mod-http-js (>= 0.5)  no package provides libnginx-mod-http-js
  oldlib   1.0-1     libssl3 (>= 4.0)               version constraint not satisfied by any candidate
```

## Why this exists

`apt-cache`, `dose-debcheck` and `apt-get install --simulate` all answer
dependency questions, but each of them answers one question at a time, and each
of them needs a live apt configuration pointed at a live mirror. Archive work
is different: you want to ask the same archive fifty questions in a row, across
several series at once, and you want the answers to be scriptable.

`archive-atlas` parses `dists/<series>/<component>/binary-<arch>/Packages`
into SQLite once. After that, the questions are queries:

- **broken** — dependencies no package in the same series and architecture satisfies
- **impact** — the reverse-dependency closure of one package
- **cycles** — dependency cycles, as strongly connected components
- **duplicates** — one name with several versions, or split across components
- **orphans** — packages nothing depends on and nothing marks essential
- **stats** — counts and sizes by series, component and section

The archive never has to be a mirror on disk. Any directory with `dists/` in it
works, including one produced by a build you just ran.

## Quickstart (60 seconds, no download)

```bash
python3 -m pip install .
archive-atlas demo /tmp/demo-archive      # synthetic archive with 5 known defects
archive-atlas index /tmp/demo-archive -o /tmp/demo.db
archive-atlas broken /tmp/demo.db         # exits 1: two unsatisfiable dependencies
archive-atlas cycles /tmp/demo.db
archive-atlas impact /tmp/demo.db libssl3
archive-atlas stats /tmp/demo.db
```

The demo archive is the same fixture the test suite uses: two series, two
components, two architectures, 22 packages, and deliberate copies of the
defects that actually show up in an archive — a missing dependency, an
unreachable version constraint, a two-package cycle, a duplicated name, and an
orphan.

## Commands

| Command | Answers |
|---|---|
| `index ARCHIVE -o DB` | parse the tree into SQLite (`--series` to limit, `--force` to overwrite) |
| `stats DB` | packages, download and installed size, per series/component/section |
| `broken DB` | unsatisfiable dependencies, with the reason and the offending constraint |
| `impact DB NAME` | everything that would lose a dependency if `NAME` disappeared |
| `cycles DB` | strongly connected components with more than one member |
| `duplicates DB` | several versions of one name, or one name in several components |
| `orphans DB` | names with no reverse dependency, excluding Essential and required/important |
| `demo DIR` | write the synthetic archive |

`broken`, `duplicates` and `cycles` exit `1` when they find something, so they
work as archive gates. Everything accepts `--series`, `--arch` and
`--format json`.

## How it works

**The schema keeps alternatives grouped.** A dependency is a *group* of
alternatives, any one of which satisfies it. Flattening `a | b` into two rows
would turn "one of these" into "both of these", which is the single most common
way a hand-written dependency checker gets the wrong answer. `dependencies`
therefore has `(kind, group_no, alt_no)` coordinates.

**Version comparison is the real algorithm**, not a string sort. Policy §5.6.12
compares epoch, then upstream version, then Debian revision, with `~` sorting
before the empty string. This matters constantly: `1.0~rc1 < 1.0`,
`1:0.1 > 2.0`, `1.0 < 1.0a`. The implementation is cross-checked against
`dpkg --compare-versions` on randomly generated version pairs — 800 pairs, zero
disagreements — and the table in `tests/test_debversion.py` includes the cases
where naive comparison inverts the order.

**Virtual packages are first-class.** `mutt` depends on
`mail-transport-agent`, which `postfix` provides. A versioned dependency on a
virtual name is only satisfied by a *versioned* `Provides`, per Policy 7.1.
Reverse dependencies account for providers too, otherwise every provider in the
archive is reported as an orphan — which is exactly backwards.

**Cycle detection is iterative Tarjan.** A real Ubuntu archive is tens of
thousands of nodes; a recursive DFS hits the interpreter's recursion limit on
precisely the archives where the answer matters.

**Scope is one `(series, arch)` universe**, because that is what apt resolves
against. Dependencies do not cross series, and an amd64 package cannot satisfy
an arm64 dependency.

## Correctness

```bash
make test    # 41 tests, standard library only
```

The suite covers the version algebra, relationship parsing (alternatives,
architecture lists, qualifiers, build profiles, versioned Provides), the index
round-trip, and every report against the demo archive — including the negative
cases: the virtual dependency that must *not* be reported broken, the clean
architecture that must report nothing, and the provider that must *not* be
reported as an orphan.

## Limits

- Binary archives only. Source packages, `Build-Depends` and build profiles are
  parsed but not evaluated.
- One architecture at a time; `:any` is treated as satisfiable within the
  selected architecture rather than across all of them.
- No `Release`/`InRelease` signature verification. The index trusts the tree it
  is given; verify the archive before indexing it.
- `Conflicts`/`Breaks` are stored and round-tripped but no report uses them yet.

## Licence

MIT. See `LICENSE`.
