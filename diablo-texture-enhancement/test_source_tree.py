import json
import tempfile
import unittest

import numpy as np

import source_tree
import testkit


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = testkit.make_source(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_reads_the_animations_and_ignores_other_kinds(self):
        source = source_tree.load(self.src)
        self.assertEqual([a.key for a in source.animations],
                         [spec["key"] for spec in testkit.DEFAULT_ANIMS])
        walk = source.animation("monsters/zombie/zombiew.cl2")
        self.assertEqual((walk.kind, walk.groups, len(walk.frames)), ("monster_anim", 2, 8))
        self.assertEqual(walk.variants, (testkit.GREY_TRN,))
        self.assertEqual(walk.frames[4], source_tree.Frame(1, 0, 32, 24, "d1/f000.png",
                                                           "d1/f000.idx.png"))
        self.assertEqual(source.animation("monsters/darkmage/dmagew.cl2").frames, ())

    def test_frame_rgba_applies_the_trn_then_the_palette(self):
        source = source_tree.load(self.src)
        walk = source.animation("monsters/zombie/zombiew.cl2")
        indices, mask = testkit.frame_indices(testkit.DEFAULT_ANIMS[1], 0, 0)
        base = np.asarray(source_tree.frame_rgba(self.src, walk, walk.frames[0]))
        grey = np.asarray(source_tree.frame_rgba(self.src, walk, walk.frames[0], testkit.GREY_TRN))
        np.testing.assert_array_equal(base[..., :3][mask], np.array(testkit.PALETTE)[indices][mask])
        np.testing.assert_array_equal(grey[..., 0][mask], np.array(testkit.GREY_MAP)[indices][mask])
        np.testing.assert_array_equal(base[..., 3], np.where(mask, 255, 0))
        self.assertEqual(int(base[~mask].max()), 0, msg="transparent pixels are all zero")

    def test_bad_output_is_a_source_error(self):
        cases = {
            "no hd_contract": lambda: (self.src / "manifest.json").write_text(
                json.dumps({"assets": []})),
            "frame size disagrees with meta.json": lambda: testkit.rewrite_meta(
                self.src, "missiles/fireba1.cl2",
                lambda meta: meta["frames"][0].update(w=25)),
            "missing palette": lambda: (self.src / "palettes" / f"{testkit.PALETTE_NAME}.json")
            .unlink(),
        }
        for label, breaks in cases.items():
            with self.subTest(label):
                self.tearDown()
                self.setUp()
                breaks()
                with self.assertRaises(source_tree.SourceError):
                    source = source_tree.load(self.src)
                    anim = source.animation("missiles/fireba1.cl2")
                    source_tree.frame_rgba(self.src, anim, anim.frames[0])


@testkit.needs_real_corpus
class RealCorpusTests(unittest.TestCase):
    def test_the_real_manifest(self):
        source = source_tree.load(testkit.REAL_SRC)
        kinds = {}
        for anim in source.animations:
            kinds[anim.kind] = kinds.get(anim.kind, 0) + 1
        self.assertEqual(kinds, {"player_anim": 1056, "monster_anim": 334, "towner_anim": 21,
                                 "missile": 380})
        self.assertEqual(sum(len(a.frames) for a in source.animations), 145560)
        self.assertEqual(sum(1 for a in source.animations if a.variants), 182)


if __name__ == "__main__":
    unittest.main()
