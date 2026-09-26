import tempfile
import unittest
from pathlib import Path

import characters_file as cf


class SeedTests(unittest.TestCase):
    def test_seed_groups_by_directory_and_missile_stem_and_picks_anchors(self):
        seeded = cf.seed_characters([
            ("monsters/zombie/zombiew.cl2", "monster_anim", 64),
            ("monsters/zombie/zombien.cl2", "monster_anim", 64),
            ("plrgfx/warrior/wlm/wlmwl.cl2", "player_anim", 64),
            ("plrgfx/warrior/wlm/wlmst.cl2", "player_anim", 64),
            ("missiles/acidbf10.cl2", "missile", 8),
            ("missiles/acidbf2.cl2", "missile", 8),
            ("missiles/arrows.cl2", "missile", 16),
            ("towners/smith/smithn.cel", "towner_anim", 16),
            ("@DIABDAT.MPQ/monsters/goatlord/goatld.cl2", "monster_anim", 64),
            ("monsters/darkmage/dmagen.cl2", "monster_anim", 0),      # no frames: never the anchor
            ("monsters/darkmage/dmagew.cl2", "monster_anim", 64),
        ])
        self.assertEqual(seeded, {
            "monsters/zombie": cf.Character(("monsters/zombie/zombien.cl2",
                                             "monsters/zombie/zombiew.cl2"),
                                            "monsters/zombie/zombien.cl2"),
            "plrgfx/warrior/wlm": cf.Character(("plrgfx/warrior/wlm/wlmst.cl2",
                                                "plrgfx/warrior/wlm/wlmwl.cl2"),
                                               "plrgfx/warrior/wlm/wlmst.cl2"),
            "missiles/acidbf": cf.Character(("missiles/acidbf2.cl2", "missiles/acidbf10.cl2"),
                                            "missiles/acidbf2.cl2"),
            "missiles/arrows": cf.Character(("missiles/arrows.cl2",), "missiles/arrows.cl2"),
            "towners/smith": cf.Character(("towners/smith/smithn.cel",),
                                          "towners/smith/smithn.cel"),
            "monsters/darkmage": cf.Character(("monsters/darkmage/dmagew.cl2",
                                               "monsters/darkmage/dmagen.cl2"),
                                              "monsters/darkmage/dmagew.cl2"),
            "@DIABDAT.MPQ/monsters/goatlord": cf.Character(
                ("@DIABDAT.MPQ/monsters/goatlord/goatld.cl2",),
                "@DIABDAT.MPQ/monsters/goatlord/goatld.cl2"),
        })


class CharactersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "characters.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_keeps_a_multi_line_caption(self):
        chars = {"monsters/zombie": cf.Character(("a.cl2", "b.cl2"), "a.cl2",
                                                 "SUBJECT: a zombie  \nCOLOURS: green", ("b.cl2",))}
        cf.save_characters(self.path, chars)
        self.assertIn("caption: >", self.path.read_text())
        loaded = cf.load_characters(self.path)
        self.assertEqual(loaded["monsters/zombie"].caption, "SUBJECT: a zombie\nCOLOURS: green")
        self.assertEqual(loaded["monsters/zombie"].skip, ("b.cl2",))

    def test_bad_entries_are_refused(self):
        cases = {
            "anchor outside": "c:\n  animations: [a.cl2]\n  anchor: b.cl2\n",
            "anchor skipped": "c:\n  animations: [a.cl2]\n  anchor: a.cl2\n  skip: [a.cl2]\n",
            "skip outside": "c:\n  animations: [a.cl2]\n  anchor: a.cl2\n  skip: [z.cl2]\n",
            "unknown field": "c:\n  animations: [a.cl2]\n  anchor: a.cl2\n  style: x\n",
            "no animations": "c:\n  anchor: a.cl2\n",
        }
        for label, text in cases.items():
            with self.subTest(label):
                self.path.write_text(text)
                with self.assertRaises(cf.CharactersFileError):
                    cf.load_characters(self.path)

    def test_coverage_needs_each_animation_exactly_once(self):
        chars = {"x": cf.Character(("a", "b"), "a"), "y": cf.Character(("b",), "b")}
        with self.assertRaisesRegex(cf.CharactersFileError, "b is in both x and y.*no character "
                                                            "for c.*not in the manifest: d"):
            cf.check_coverage({**chars, "z": cf.Character(("d",), "d")}, ["a", "b", "c"])
        cf.check_coverage({"x": cf.Character(("a", "b"), "a")}, ["a", "b"])


class ReviewsTests(unittest.TestCase):
    def test_round_trip_and_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reviews.yaml"
            reviews = {"monsters/zombie/zombiew.cl2/@trn/monsters/zombie/grey.trn/s02":
                       cf.Review(3, False, ("cell 4 bleeds into cell 5",), "review")}
            cf.save_reviews(path, reviews)
            self.assertEqual(cf.load_reviews(path), reviews)
            self.assertEqual(cf.load_reviews(Path(tmp) / "none.yaml", optional=True), {})
            for text in ("a.cl2:\n  attempt: 1\n  accepted: true\n  issues: []\n",
                         "a.cl2/s01:\n  attempt: 1\n  accepted: true\n  issues: [x]\n"):
                with self.subTest(text=text):
                    path.write_text(text)
                    with self.assertRaises(cf.CharactersFileError):
                        cf.load_reviews(path)


if __name__ == "__main__":
    unittest.main()
