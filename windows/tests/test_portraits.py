"""Portraits by name, and scientists' names for agents created without one."""
from __future__ import annotations

import random
import sys
import tempfile
import unittest
from pathlib import Path

WINDOWS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS))
from host import portraits  # noqa: E402


class PortraitTest(unittest.TestCase):
    def test_namesake_wears_their_own_portrait(self):
        self.assertIn("Curie", portraits.stems())
        for name in ("Curie", "curie", "CURIE"):
            self.assertEqual(portraits.portrait_stem(name), "Curie")

    def test_other_names_keep_the_hash_the_page_used(self):
        # Values from the former portraitFor() in web/app.js, run in node:
        # agents created before this change keep the face they had.
        for name, small, large in (("tech", 67, 555981), ("Philosophy", 17, 677445),
                                   ("writer", 37, 382594),
                                   ("a-very_long.agent-name-0123456789abcdefghijklmnopqrstuvwxyz",
                                    74, 491843)):
            self.assertEqual((portraits.hash_index(name, 97), portraits.hash_index(name, 1000003)),
                             (small, large), name)
        names = portraits.stems()
        self.assertEqual(portraits.portrait_stem("tech"), names[portraits.hash_index("tech", len(names))])

    def test_no_portraits_no_face(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertIsNone(portraits.portrait_stem("tech", Path(empty)))


class RandomNameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        for stem in ("Bohr", "Curie"):
            (self.base / f"{stem}.png").write_bytes(b"")
        self.rng = random.Random(0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_skips_names_in_use_whatever_their_case(self):
        for _ in range(20):
            self.assertEqual(portraits.random_name({"curie"}, self.base, self.rng), "Bohr")

    def test_numbers_once_every_name_is_used(self):
        self.assertIn(portraits.random_name({"Bohr", "curie"}, self.base, self.rng), {"Bohr2", "Curie2"})
        self.assertEqual(portraits.random_name({"Bohr", "Curie", "bohr2", "Curie2", "Curie3"},
                                               self.base, self.rng), "Bohr3")

    def test_every_scientist_name_is_a_valid_agent_name(self):
        from hub.db import check_name

        for stem in portraits.stems():
            self.assertEqual(check_name(stem), stem)


if __name__ == "__main__":
    unittest.main()
