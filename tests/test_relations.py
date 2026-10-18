import unittest

from archive_atlas.packages import parse_packages, parse_stanzas
from archive_atlas.relations import (
    architecture_applies,
    parse_alternative,
    parse_provides,
    parse_relations,
)


class RelationParsingTests(unittest.TestCase):
    def test_simple_name(self):
        (group,) = parse_relations("libc6")
        self.assertEqual(group.alternatives[0].name, "libc6")
        self.assertEqual(group.alternatives[0].operator, "")

    def test_version_constraint(self):
        relation = parse_relations("libssl3 (>= 3.0.0)")[0].alternatives[0]
        self.assertEqual(relation.name, "libssl3")
        self.assertEqual(relation.operator, ">=")
        self.assertEqual(relation.version, "3.0.0")
        self.assertTrue(relation.matches("3.0.13"))
        self.assertFalse(relation.matches("3.0.0~rc1"))

    def test_alternatives_stay_grouped(self):
        groups = parse_relations("libc6, mail-transport-agent | postfix (>= 3.0)")
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[1].alternatives), 2)
        self.assertEqual([a.name for a in groups[1].alternatives], ["mail-transport-agent", "postfix"])

    def test_architecture_restriction(self):
        relation = parse_relations("libc6 [amd64 !i386]")[0].alternatives[0]
        self.assertEqual(relation.arches, ("amd64", "!i386"))
        self.assertTrue(architecture_applies(relation, "amd64"))
        self.assertFalse(architecture_applies(relation, "i386"))
        self.assertFalse(architecture_applies(relation, "arm64"))

    def test_negation_only_list(self):
        relation = parse_relations("libc6 [!arm64]")[0].alternatives[0]
        self.assertTrue(architecture_applies(relation, "amd64"))
        self.assertFalse(architecture_applies(relation, "arm64"))

    def test_architecture_qualifier(self):
        relation = parse_relations("python3:any (>= 3.10)")[0].alternatives[0]
        self.assertEqual(relation.qualifier, "any")
        self.assertEqual(relation.version, "3.10")

    def test_build_profile(self):
        relation = parse_relations("pytest <!nocheck>")[0].alternatives[0]
        self.assertEqual(relation.profiles, ("!nocheck",))

    def test_provides_with_version(self):
        provided = parse_provides("mime-support, mail-transport-agent (= 3.8)")
        self.assertEqual([item.name for item in provided], ["mime-support", "mail-transport-agent"])
        self.assertEqual(provided[1].version, "3.8")

    def test_versioned_dependency_needs_versioned_provides(self):
        relation = parse_alternative("mail-transport-agent (>= 2.0)")
        self.assertFalse(relation.matches(None))
        self.assertTrue(relation.matches("3.8"))

    def test_unversioned_dependency_accepts_unversioned_provides(self):
        relation = parse_alternative("mail-transport-agent")
        self.assertTrue(relation.matches(None))

    def test_malformed_relation_raises(self):
        with self.assertRaises(ValueError):
            parse_alternative("this is not a package name")

    def test_multiline_field_is_flattened(self):
        groups = parse_relations("libc6,\n libssl3 (>= 3.0)")
        self.assertEqual(len(groups), 2)

    def test_describe_round_trip(self):
        relation = parse_alternative("libssl3 (>= 3.0.0)")
        self.assertEqual(relation.describe(), "libssl3 (>= 3.0.0)")


class PackageParsingTests(unittest.TestCase):
    STANZA = """\
Package: demo
Version: 1.0-1
Architecture: amd64
Depends: libc6 (>= 2.34), libssl3
Provides: demo-virtual
Description: a demo
 extended body
"""

    def test_stanza_continuation(self):
        (stanza,) = list(parse_stanzas(self.STANZA))
        self.assertEqual(stanza["Description"], "a demo\nextended body")

    def test_package_fields(self):
        (package,) = list(parse_packages(self.STANZA, "noble", "main"))
        self.assertEqual(package.name, "demo")
        self.assertEqual(package.series, "noble")
        self.assertEqual(len(package.depends), 2)
        self.assertEqual(package.provided_names(), ["demo-virtual"])

    def test_stanza_without_required_fields_is_skipped(self):
        self.assertEqual(list(parse_packages("Package: broken\n", "noble", "main")), [])

    def test_two_stanzas(self):
        text = self.STANZA + "\n" + self.STANZA.replace("demo", "other")
        self.assertEqual(len(list(parse_packages(text, "noble", "main"))), 2)


if __name__ == "__main__":
    unittest.main()
