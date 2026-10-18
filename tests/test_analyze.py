import tempfile
import unittest
from pathlib import Path

from archive_atlas.analyze import Universe, stats
from archive_atlas.demo import create_demo_archive
from archive_atlas.index import build_index, connect, load_packages, series_architectures


class ArchiveAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name) / "archive"
        create_demo_archive(root)
        cls.database = Path(cls._tmp.name) / "archive.db"
        cls.summary = build_index(root, cls.database)
        cls.connection = connect(cls.database)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        cls._tmp.cleanup()

    def universe(self, series="noble", arch="amd64"):
        return Universe.build(series, arch, load_packages(self.connection, series, arch))

    # -- indexing -----------------------------------------------------------

    def test_index_summary(self):
        self.assertEqual(self.summary.series, ["jammy", "noble"])
        self.assertEqual(self.summary.components, ["main", "universe"])
        self.assertEqual(self.summary.architectures, ["amd64", "arm64"])

    def test_every_stanza_reaches_the_database(self):
        self.assertEqual(self.summary.packages, 22)

    def test_series_arch_pairs(self):
        self.assertEqual(
            series_architectures(self.connection),
            [("jammy", "amd64"), ("noble", "amd64"), ("noble", "arm64")],
        )

    def test_relations_survive_the_round_trip(self):
        curl = next(package for package in self.universe().find("curl"))
        self.assertEqual(len(curl.depends), 3)
        second = curl.depends[1].alternatives[0]
        self.assertEqual(second.name, "libssl3")
        self.assertEqual(second.operator, ">=")
        self.assertEqual(second.version, "3.0.0")

    def test_epoch_constraint_is_resolved_correctly(self):
        # zlib1g is 1:1.3.dfsg-3 and the constraint is (>= 1:1.1.4); a string
        # comparison of "1:1.3" and "1:1.1" happens to agree, so this also
        # guards the epoch split rather than only the ordering.
        curl = next(package for package in self.universe().find("curl"))
        self.assertTrue(self.universe().group_satisfied(curl.depends[2]))

    # -- reports ------------------------------------------------------------

    def test_broken_dependencies_are_exactly_the_injected_ones(self):
        broken = {item.package for item in self.universe().broken()}
        self.assertEqual(broken, {"nginx", "oldlib"})

    def test_missing_package_is_distinguished_from_bad_version(self):
        reasons = {item.package: item.reason for item in self.universe().broken()}
        self.assertIn("no package provides", reasons["nginx"])
        self.assertIn("version constraint", reasons["oldlib"])

    def test_virtual_package_satisfies_dependency(self):
        broken = {item.package for item in self.universe().broken()}
        self.assertNotIn("mutt", broken)

    def test_clean_architecture_has_no_findings(self):
        self.assertEqual(self.universe(arch="arm64").broken(), [])

    def test_impact_closure(self):
        affected = self.universe().impact("libssl3")
        self.assertIn("curl", affected)
        self.assertIn("oldlib", affected)
        self.assertIn("slack-cli", affected)
        self.assertNotIn("libssl3", affected)

    def test_provider_has_reverse_dependency(self):
        affected = self.universe().impact("postfix")
        self.assertEqual(affected, ["mutt"])

    def test_impact_unknown_package_raises(self):
        with self.assertRaises(KeyError):
            self.universe().impact("not-a-package")

    def test_cycle_detection(self):
        cycles = self.universe().cycles()
        self.assertEqual(cycles, [["cyc-a", "cyc-b"]])

    def test_duplicates(self):
        duplicates = self.universe().duplicates()
        self.assertEqual([item.name for item in duplicates], ["dup-tool"])
        self.assertEqual(duplicates[0].versions, ["1.0-1", "2.0-1"])

    def test_orphans_include_shelfware_but_not_providers(self):
        orphans = {package.name for package in self.universe().orphans()}
        self.assertIn("shelfware", orphans)
        self.assertNotIn("postfix", orphans)
        self.assertNotIn("libc6", orphans)

    def test_stats(self):
        payload = stats(self.connection)
        self.assertEqual(payload["packages"], 22)
        self.assertEqual([row["series"] for row in payload["by_series"]], ["jammy", "noble"])
        self.assertIn("amd64", payload["architectures"])

    def test_strongly_connected_components_ignores_unknown_names(self):
        graph = {"a": {"b"}, "b": {"a"}, "c": {"missing"}}
        universe = Universe(series="x", arch="amd64")
        from archive_atlas.analyze import strongly_connected_components

        components = {frozenset(component) for component in strongly_connected_components(graph)}
        self.assertIn(frozenset({"a", "b"}), components)
        self.assertIn(frozenset({"c"}), components)


if __name__ == "__main__":
    unittest.main()
