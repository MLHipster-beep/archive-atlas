"""Generate a small synthetic archive that exercises every report.

The point of the demo is reproducibility: the same fixture, with the same five
defects, appears in the README, in the test suite and in CI.  A test that
depends on a downloaded Ubuntu archive is not a test, it is a network check.
"""

from __future__ import annotations

from pathlib import Path

# name, version, arch, section, priority, extra fields
NOBLE_MAIN = [
    ("libc6", "2.39-0ubuntu8", "amd64", "libs", "required", {"Essential": "yes"}),
    ("libssl3", "3.0.13-0ubuntu3", "amd64", "libs", "optional", {"Depends": "libc6 (>= 2.34)"}),
    ("zlib1g", "1:1.3.dfsg-3", "amd64", "libs", "optional", {"Depends": "libc6 (>= 2.14)"}),
    ("curl", "8.5.0-2ubuntu1", "amd64", "web", "optional",
     {"Depends": "libc6 (>= 2.34), libssl3 (>= 3.0.0), zlib1g (>= 1:1.1.4)"}),
    ("postfix", "3.8.6-1", "amd64", "mail", "optional",
     {"Depends": "libc6 (>= 2.34)", "Provides": "mail-transport-agent"}),
    ("mutt", "2.2.12-0.1", "amd64", "mail", "optional",
     {"Depends": "libc6 (>= 2.34), mail-transport-agent"}),
    ("mailcap", "3.70+nmu1", "amd64", "utils", "optional",
     {"Depends": "libc6", "Provides": "mime-support"}),
]

# Each entry below exists to trigger exactly one finding.
NOBLE_DEFECTS = [
    # A dependency on a package no component provides.
    ("nginx", "1.24.0-1", "amd64", "web", "optional",
     {"Depends": "libc6 (>= 2.34), libnginx-mod-http-js (>= 0.5)"}),
    # A version constraint no candidate satisfies.
    ("oldlib", "1.0-1", "amd64", "libs", "optional",
     {"Depends": "libssl3 (>= 4.0)"}),
    # A dependency cycle.
    ("cyc-a", "1.0-1", "amd64", "misc", "optional", {"Depends": "cyc-b"}),
    ("cyc-b", "1.0-1", "amd64", "misc", "optional", {"Depends": "cyc-a"}),
    # Two versions of one package inside one component.
    ("dup-tool", "1.0-1", "amd64", "utils", "optional", {"Depends": "libc6"}),
    ("dup-tool", "2.0-1", "amd64", "utils", "optional", {"Depends": "libc6"}),
    # No reverse dependency: the orphan report's subject.
    ("shelfware", "0.1-1", "amd64", "utils", "optional", {"Depends": "libc6"}),
]

JAMMY_MAIN = [
    ("libc6", "2.35-0ubuntu3.8", "amd64", "libs", "required", {"Essential": "yes"}),
    ("libssl3", "3.0.2-0ubuntu1.16", "amd64", "libs", "optional", {"Depends": "libc6 (>= 2.34)"}),
    ("curl", "7.81.0-1ubuntu1.16", "amd64", "web", "optional",
     {"Depends": "libc6 (>= 2.34), libssl3 (>= 3.0.0)"}),
]

UNIVERSE_MAIN = [
    ("slack-cli", "1.2.3-1", "amd64", "net", "optional", {"Depends": "libc6, libssl3"}),
]

ARM64 = [
    ("libc6", "2.39-0ubuntu8", "arm64", "libs", "required", {"Essential": "yes"}),
    ("libssl3", "3.0.13-0ubuntu3", "arm64", "libs", "optional", {"Depends": "libc6 (>= 2.34)"}),
    ("zlib1g", "1:1.3.dfsg-3", "arm64", "libs", "optional", {"Depends": "libc6 (>= 2.14)"}),
    ("curl", "8.5.0-2ubuntu1", "arm64", "web", "optional",
     {"Depends": "libc6 (>= 2.34), libssl3 (>= 3.0.0), zlib1g (>= 1:1.1.4)"}),
]


def render_stanza(entry) -> str:
    name, version, arch, section, priority, extra = entry
    fields = [
        ("Package", name),
        ("Version", version),
        ("Architecture", arch),
        ("Section", section),
        ("Priority", priority),
        ("Maintainer", "Demo Maintainer <demo@example.com>"),
        ("Installed-Size", "128"),
        ("Filename", f"pool/{section}/{name}/{name}_{version}_{arch}.deb"),
        ("Size", "65536"),
    ]
    fields.extend(extra.items())
    fields.append(
        ("Description", f"{name} demo package\n A synthetic package used by archive-atlas fixtures.")
    )
    return "\n".join(f"{key}: {value}" for key, value in fields) + "\n"


def write_packages(path: Path, entries) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(render_stanza(entry) for entry in entries), encoding="utf-8")


def create_demo_archive(root: Path) -> Path:
    root = Path(root)
    write_packages(root / "dists/noble/main/binary-amd64/Packages", NOBLE_MAIN + NOBLE_DEFECTS)
    write_packages(root / "dists/noble/universe/binary-amd64/Packages", UNIVERSE_MAIN)
    write_packages(root / "dists/noble/main/binary-arm64/Packages", ARM64)
    write_packages(root / "dists/jammy/main/binary-amd64/Packages", JAMMY_MAIN)

    release = (
        "Origin: Archive Atlas Demo\n"
        "Label: demo\n"
        "Suite: stable\n"
        "Codename: noble\n"
        "Architectures: amd64 arm64\n"
        "Components: main universe\n"
    )
    (root / "dists/noble/Release").write_text(release, encoding="utf-8")
    (root / "dists/jammy/Release").write_text(release.replace("noble", "jammy"), encoding="utf-8")
    return root
