import unittest

from archive_atlas.debversion import compare, satisfies, split_version, sort_key

# Each pair is (left, right, expected).  These are the cases where a naive
# string comparison gives the wrong answer, which is the whole reason the
# algorithm exists.
CASES = [
    ("1.0", "1.0", 0),
    ("1.0", "1.1", -1),
    ("1.1", "1.0", 1),
    ("1.0-1", "1.0-2", -1),
    ("1.0-1", "1.0-1", 0),
    ("1.0", "1.0-1", -1),
    ("1.0~rc1", "1.0", -1),
    ("1.0~rc1", "1.0~rc2", -1),
    ("1.0~~", "1.0~", -1),
    ("1.0~~a", "1.0~~", 1),
    ("1.0a", "1.0", 1),
    ("1.0", "1.0a", -1),
    ("1.0a", "1.0b", -1),
    ("1:0.1", "2.0", 1),
    ("0:2.0", "2.0", 0),
    ("2.0", "1:0.1", -1),
    ("1.2.3-1", "1.2.3-1ubuntu1", -1),
    ("1.2.3-1ubuntu1", "1.2.3-1ubuntu2", -1),
    ("1:1.3.dfsg-3", "1:1.1.4", 1),
    ("2.39-0ubuntu8", "2.34", 1),
    ("1.0+deb1", "1.0", 1),
    ("1.0.0", "1.0", 1),
]


class VersionComparisonTests(unittest.TestCase):
    def test_case_table(self):
        for left, right, expected in CASES:
            with self.subTest(left=left, right=right):
                self.assertEqual(compare(left, right), expected)
                self.assertEqual(compare(right, left), -expected)

    def test_split_epoch_upstream_revision(self):
        self.assertEqual(split_version("1:2.3-4"), (1, "2.3", "4"))
        self.assertEqual(split_version("2.3"), (0, "2.3", ""))
        self.assertEqual(split_version("2.3-4-5"), (0, "2.3-4", "5"))

    def test_native_version_has_no_revision(self):
        self.assertEqual(split_version("1.0")[2], "")

    def test_satisfies_operators(self):
        self.assertTrue(satisfies("2.39-0ubuntu8", ">=", "2.34"))
        self.assertFalse(satisfies("2.39-0ubuntu8", ">>", "2.39-0ubuntu8"))
        self.assertTrue(satisfies("3.0.13", "=", "3.0.13"))
        self.assertTrue(satisfies("1.0~rc1", "<<", "1.0"))
        self.assertFalse(satisfies("1.0", "<<", "1.0"))

    def test_unversioned_relation_always_satisfies(self):
        self.assertTrue(satisfies("anything", "", ""))

    def test_unknown_operator_is_rejected(self):
        with self.assertRaises(ValueError):
            satisfies("1.0", "==", "1.0")

    def test_sort_key_orders_versions(self):
        versions = ["1.0-1", "1.0~rc1", "1:0.1", "1.0", "0.9"]
        self.assertEqual(sorted(versions, key=sort_key), ["0.9", "1.0~rc1", "1.0", "1.0-1", "1:0.1"])


if __name__ == "__main__":
    unittest.main()
